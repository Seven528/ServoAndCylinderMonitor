"""Offline descriptive and condition screening for servo/cylinder runtime exports.

The input is a periodic PLC snapshot, not a cycle-level event table. Findings are
therefore screening signals and must be interpreted with the process context.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


LTIME_COLUMNS = [
    "ACTTIME", "AVGTIME", "MINTIME", "MAXTIME", "TOTTIME",
    "MOVETOTBASTIME", "MOVETOWORKTIME",
]
SERVO_NUMERIC = ["ACTPOS", "ACTVEL", "ACTTORQUE", "SPEED", "TARGETPOS"]
DIAG_COLUMNS = ["CLASS1DIAG", "CLASS2DIAG", "CLASS3DIAG"]
ASSET_COLUMNS = ["PRODUCTTEAM", "MACHINETYPE", "LINENAME", "STATIONNAME", "MESSAGENAME"]


@dataclass
class AnalysisResult:
    enriched: pd.DataFrame
    asset_summary: pd.DataFrame
    anomaly_events: pd.DataFrame
    data_quality: dict
    interpretation: list[str]


def parse_ltime_ms(value: object, byteorder: str = "little") -> float:
    """Convert an exported 8-byte PLC LTIME value (signed nanoseconds) to ms."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return np.nan
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return np.nan
        value = ast.literal_eval(value)
    if not isinstance(value, (list, tuple, bytes, bytearray)) or len(value) != 8:
        return np.nan
    try:
        raw = bytes(int(x) for x in value)
        return int.from_bytes(raw, byteorder=byteorder, signed=True) / 1_000_000
    except (ValueError, TypeError, OverflowError):
        return np.nan


def robust_outlier(values: pd.Series, min_samples: int = 20) -> tuple[pd.Series, pd.Series]:
    """Return robust z scores and flags, using MAD with a std fallback."""
    x = pd.to_numeric(values, errors="coerce")
    valid = x.dropna()
    if len(valid) < min_samples:
        return pd.Series(np.nan, index=x.index), pd.Series(False, index=x.index)
    median = valid.median()
    mad = (valid - median).abs().median()
    scale = 1.4826 * mad
    if not np.isfinite(scale) or scale <= 0:
        scale = valid.std(ddof=0)
    if not np.isfinite(scale) or scale <= 0:
        return pd.Series(0.0, index=x.index), pd.Series(False, index=x.index)
    z = (x - median) / scale
    return z, z.abs().gt(3.5).fillna(False)


def _asset_key(df: pd.DataFrame) -> pd.Series:
    cols = [c for c in ASSET_COLUMNS if c in df]
    if not cols:
        return pd.Series("unknown_asset", index=df.index)
    return df[cols].fillna("NA").astype(str).agg(" / ".join, axis=1)


def _first_true_count(df: pd.DataFrame, columns: Iterable[str]) -> int:
    count = 0
    for col in columns:
        if col in df:
            count += int(df[col].fillna(False).astype(bool).sum())
    return count


def _markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "（无记录）"
    columns = [str(c) for c in frame.columns]
    rows = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for values in frame.itertuples(index=False, name=None):
        cells = [str(value).replace("|", "\\|").replace("\n", " ") for value in values]
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(rows)


def analyze_dataframe(raw: pd.DataFrame) -> AnalysisResult:
    """Prepare data, calculate interpretable screens, summaries, and quality."""
    df = raw.copy()
    df.columns = [str(c).strip().upper() for c in df.columns]
    if "MSG_TIMESTAMP" in df:
        df["MSG_TIMESTAMP"] = pd.to_datetime(df["MSG_TIMESTAMP"], errors="coerce", utc=True).dt.tz_convert("Asia/Shanghai")
        df = df.sort_values("MSG_TIMESTAMP", kind="stable").reset_index(drop=True)

    for col in LTIME_COLUMNS:
        if col in df:
            df[f"{col}_MS"] = df[col].map(parse_ltime_ms)
    for col in SERVO_NUMERIC:
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if {"TARGETPOS", "ACTPOS"}.issubset(df.columns):
        df["POSITION_ERROR"] = df["TARGETPOS"] - df["ACTPOS"]

    df["ASSET_KEY"] = _asset_key(df)
    df["ANOMALY_FLAGS"] = ""

    def add_flag(mask: pd.Series, name: str) -> None:
        mask = mask.reindex(df.index, fill_value=False).fillna(False).astype(bool)
        df.loc[mask, "ANOMALY_FLAGS"] = df.loc[mask, "ANOMALY_FLAGS"].map(
            lambda old: f"{old};{name}" if old else name
        )

    # PLC/drive state checks: treat diagnostic booleans as asserted only when true.
    for col in DIAG_COLUMNS:
        if col in df:
            add_flag(df[col].astype(str).str.lower().isin(["true", "1"]), f"{col}_ASSERTED")
    if "DRIVEENABLED" in df and "DRIVEREADYFORMOVEMENT" in df:
        add_flag(
            df["DRIVEENABLED"].astype(str).str.lower().isin(["true", "1"])
            & ~df["DRIVEREADYFORMOVEMENT"].astype(str).str.lower().isin(["true", "1"]),
            "DRIVE_ENABLED_NOT_READY_FOR_MOVEMENT",
        )
    if "AXISINREFERENCE" in df:
        add_flag(~df["AXISINREFERENCE"].astype(str).str.lower().isin(["true", "1"]), "AXIS_NOT_REFERENCED")

    # Context-aware robust screens. Limit scores to movement / execution snapshots.
    moving = pd.Series(True, index=df.index)
    if "EXEUTE" in df:
        moving &= df["EXEUTE"].astype(str).str.lower().isin(["true", "1"])
    if "ACTVEL" in df:
        moving |= pd.to_numeric(df["ACTVEL"], errors="coerce").fillna(0).abs().gt(0)
    # Compare signals within like operating phases when PLC state tags are present.
    # This reduces false alerts caused by mixing idle, acceleration, deceleration,
    # and opposite travel directions into one global baseline.
    phase = pd.DataFrame(index=df.index)
    for col in ("EXEUTE", "ACCELERATING", "DECELERATING"):
        if col in df:
            phase[col] = df[col].astype(str).str.lower()
    if "ACTVEL" in df:
        phase["ACTVEL_DIRECTION"] = np.sign(pd.to_numeric(df["ACTVEL"], errors="coerce").fillna(0)).astype(int)
    if "SPEED" in df and df["SPEED"].nunique(dropna=True) <= 12:
        phase["SPEED"] = df["SPEED"].astype(str)
    context_groups = [idx for _, idx in phase.groupby(list(phase.columns), dropna=False).groups.items()] if len(phase.columns) else []

    def context_outliers(column: str) -> tuple[pd.Series, pd.Series]:
        values = pd.to_numeric(df[column], errors="coerce")
        z, outliers = robust_outlier(values.loc[moving], min_samples=30)
        score = pd.Series(np.nan, index=df.index)
        flags = pd.Series(False, index=df.index)
        score.loc[z.index] = z
        flags.loc[outliers.index] = outliers
        for indices in context_groups:
            indices = pd.Index(indices).intersection(values.index[moving])
            if len(indices) < 30:
                continue
            local_z, local_outliers = robust_outlier(values.loc[indices], min_samples=30)
            score.loc[local_z.index] = local_z
            flags.loc[local_outliers.index] = local_outliers
        return score, flags

    for col, flag in [("ACTTORQUE", "SERVO_TORQUE_OUTLIER"), ("POSITION_ERROR", "SERVO_POSITION_ERROR_OUTLIER"),
                      ("ACTTIME_MS", "SERVO_ACTTIME_OUTLIER"),
                      ("MOVETOTBASTIME_MS", "CYLINDER_TO_BASE_TIME_OUTLIER"),
                      ("MOVETOWORKTIME_MS", "CYLINDER_TO_WORK_TIME_OUTLIER")]:
        if col not in df:
            continue
        z, outlier = context_outliers(col)
        z_col = col.replace("_MS", "") + "_ROBUST_Z"
        df[z_col] = np.nan
        df.loc[z.index, z_col] = z
        # Timing anomalies are directional: unusually long travel is actionable.
        if "TIME" in col:
            x = pd.to_numeric(df[col], errors="coerce")
            baseline_values = x.loc[moving].dropna()
            upper = pd.Series(np.inf, index=df.index)
            baseline = baseline_values.median()
            mad = (baseline_values - baseline).abs().median() if len(baseline_values) else 0
            upper.loc[moving] = baseline + max(5.2 * mad, abs(baseline) * 0.1)
            for indices in context_groups:
                indices = pd.Index(indices).intersection(x.index[moving])
                subset = x.loc[indices].dropna()
                if len(subset) < 30:
                    continue
                local_median = subset.median()
                local_mad = (subset - local_median).abs().median()
                upper.loc[indices] = local_median + max(5.2 * local_mad, abs(local_median) * 0.1)
            add_flag(moving & x.gt(upper), flag)
        else:
            add_flag(moving & outlier, flag)

    assets = []
    for key, group in df.groupby("ASSET_KEY", dropna=False):
        row = {"asset_key": key, "records": len(group)}
        if "MSG_TIMESTAMP" in group:
            row["first_timestamp"] = group["MSG_TIMESTAMP"].min()
            row["last_timestamp"] = group["MSG_TIMESTAMP"].max()
        for col in ["ACTTORQUE", "ACTVEL", "POSITION_ERROR", "ACTTIME_MS", "MOVETOTBASTIME_MS", "MOVETOWORKTIME_MS", "MOVEMENTCOUNTER"]:
            if col in group:
                s = pd.to_numeric(group[col], errors="coerce")
                row[f"{col.lower()}_median"] = s.median()
                row[f"{col.lower()}_p95"] = s.quantile(0.95)
                row[f"{col.lower()}_max"] = s.max()
        row["diagnostic_assertions"] = _first_true_count(group, DIAG_COLUMNS)
        row["screened_records"] = int(group["ANOMALY_FLAGS"].ne("").sum())
        row["screened_record_rate"] = row["screened_records"] / len(group) if len(group) else np.nan
        row["lifecycle_state"] = (
            "needs_review" if row["diagnostic_assertions"] else
            "watch" if row["screened_record_rate"] >= 0.01 else "no_major_signal_in_window"
        )
        assets.append(row)
    asset_summary = pd.DataFrame(assets)

    anomaly_events = df.loc[df["ANOMALY_FLAGS"].ne("")].copy()
    quality: dict = {
        "rows": int(len(df)),
        "columns": int(len(df.columns)),
        "duplicate_rows": int(df.duplicated().sum()),
        "timestamp_missing": int(df["MSG_TIMESTAMP"].isna().sum()) if "MSG_TIMESTAMP" in df else None,
        "asset_count": int(df["ASSET_KEY"].nunique()),
        "missing_by_column": {k: int(v) for k, v in df.isna().sum().items() if v},
    }
    if "MSG_TIMESTAMP" in df:
        delta = df["MSG_TIMESTAMP"].diff().dt.total_seconds().dropna()
        quality["timestamp_interval_median_seconds"] = float(delta.median()) if len(delta) else None
        quality["timestamp_interval_p95_seconds"] = float(delta.quantile(.95)) if len(delta) else None
        quality["time_window_hours"] = float((df["MSG_TIMESTAMP"].max() - df["MSG_TIMESTAMP"].min()).total_seconds() / 3600)
    interpretation = [
        "Outlier flags are statistical screening signals based on this export window, not confirmed faults.",
        "Lifecycle labels are heuristic and do not represent a calibrated failure probability.",
        "RUL is not estimated: this short snapshot does not provide confirmed failures, maintenance outcomes, or enough degradation history.",
    ]
    return AnalysisResult(df, asset_summary, anomaly_events, quality, interpretation)


def write_analysis(input_csv: Path, output_dir: Path, parameter_dictionary: Path | None = None) -> AnalysisResult:
    """Run the offline analysis and write reusable CSV/Markdown outputs."""
    raw = pd.read_csv(input_csv, encoding="utf-8-sig", low_memory=False)
    result = analyze_dataframe(raw)
    output_dir.mkdir(parents=True, exist_ok=True)
    result.asset_summary.to_csv(output_dir / "asset_summary.csv", index=False, encoding="utf-8-sig")
    result.anomaly_events.to_csv(output_dir / "anomaly_events.csv", index=False, encoding="utf-8-sig")
    result.enriched.to_csv(output_dir / "enriched_data.csv", index=False, encoding="utf-8-sig")

    dictionary_note = "参数字典未提供或未读取。"
    dictionary_table = ""
    if parameter_dictionary and parameter_dictionary.exists():
        try:
            dictionary = pd.read_excel(parameter_dictionary)
            dictionary_note = f"参数字典记录数：{len(dictionary)}；字段：{', '.join(map(str, dictionary.columns))}。"
            dictionary_table = _markdown_table(dictionary)
        except Exception as exc:  # noqa: BLE001 - preserve analysis even if optional metadata is unreadable
            dictionary_note = f"参数字典读取失败：{exc}"
    q = result.data_quality
    flag_counts = (
        result.anomaly_events["ANOMALY_FLAGS"].str.split(";").explode().value_counts()
        if not result.anomaly_events.empty else pd.Series(dtype="int64")
    )
    flag_table = pd.DataFrame({"flag": flag_counts.index, "records": flag_counts.values})
    report = [
        "# 伺服与气缸离线监控分析", "",
        f"- 输入文件：`{input_csv.name}`", f"- 数据行数：{q['rows']:,}",
        f"- 时间范围：{q.get('time_window_hours', 0):.2f} 小时",
        f"- 识别资产组数：{q['asset_count']}", f"- 重复行：{q['duplicate_rows']:,}",
        f"- 异常筛查记录：{len(result.anomaly_events):,}", f"- {dictionary_note}", "",
        "## 资产状态摘要", "",
        _markdown_table(result.asset_summary), "",
        "## 参数字典", "", dictionary_table or "未读取到参数字典。", "",
        "## 异常筛查信号", "", _markdown_table(flag_table), "",
        "## 数据质量与建模边界", "",
        f"- 时间戳中位采样间隔：{q.get('timestamp_interval_median_seconds', float('nan')):.3f} 秒。",
        f"- 时间戳间隔 P95：{q.get('timestamp_interval_p95_seconds', float('nan')):.3f} 秒。",
        "- 气缸动作时间和伺服反馈值来自周期快照，异常表示相对本次样本分布偏离。",
        "- 同一异常连续多个 100 ms 快照会逐行计数；上表是记录数，不是独立故障次数。",
        "- CLASS1/2/3DIAG 的 TRUE 仅按状态位筛出，尚未用设备手册确认其告警语义；请先对照诊断位定义和 DIAGNO 编码表。",
        "- 当前文件只有有限时间窗，缺少确认故障、维修与换件标签；RUL 暂不建模。", "",
        "## 解读限制", "", *[f"- {note}" for note in result.interpretation], "",
        "筛查明细见 `anomaly_events.csv`；全部转换数据见 `enriched_data.csv`。",
    ]
    (output_dir / "analysis_report.md").write_text("\n".join(report), encoding="utf-8")
    return result
