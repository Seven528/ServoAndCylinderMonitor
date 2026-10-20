"""Evidence-backed analysis orchestration for servo/cylinder CSV exports."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.analysis_agent import analyze_dataframe


PREDICTOR_COLUMNS = {
    "asset": ("ASSET_ID", "DEVICE_ID", "EQUIPMENT_ID", "CYLINDER_ID", "AXIS_ID"),
    "age": ("AGE_CYCLES", "AGE_HOURS", "AGE_DAYS", "OPERATING_HOURS", "MOVEMENTCOUNTER"),
    "event": ("FAILURE_EVENT", "FAILED", "FAILURE_FLAG", "REPLACED"),
}


def _json_value(value):
    if value is None:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if pd.isna(value):
        return None
    return value


def _records(frame, limit=100):
    if frame.empty:
        return []
    return [
        {str(k).lower(): _json_value(v) for k, v in row.items()}
        for row in frame.head(limit).to_dict(orient="records")
    ]


def _descriptive(raw, result):
    df = result.enriched
    out = {
        "assets": _records(result.asset_summary),
        "top_level": {
            "rows": len(df),
            "duplicate_rows": result.data_quality.get("duplicate_rows", 0),
            "asset_groups": result.data_quality.get("asset_count", 0),
            "first_timestamp": _json_value(df["MSG_TIMESTAMP"].min()) if "MSG_TIMESTAMP" in df else None,
            "last_timestamp": _json_value(df["MSG_TIMESTAMP"].max()) if "MSG_TIMESTAMP" in df else None,
            "window_hours": result.data_quality.get("time_window_hours"),
            "sample_interval_seconds": result.data_quality.get("timestamp_interval_median_seconds"),
        },
        "quality": result.data_quality,
        "charts": [],
    }
    if "MSG_TIMESTAMP" in df:
        for column, label in [("ACTTORQUE", "伺服实际转矩"), ("ACTVEL", "伺服实际速度"),
                              ("POSITION_ERROR", "伺服目标/实际位置差"),
                              ("MOVETOTBASTIME_MS", "气缸回程时间"), ("MOVETOWORKTIME_MS", "气缸工作行程时间")]:
            if column not in df:
                continue
            series = df.set_index("MSG_TIMESTAMP")[column].resample("1min").agg(["median", "max"]).dropna()
            if len(series) > 360:
                series = series.tail(360)
            out["charts"].append({"key": column.lower(), "label": label,
                                  "points": [{"time": _json_value(t), "median": _json_value(r["median"]),
                                              "max": _json_value(r["max"])} for t, r in series.iterrows()]})
    return out


def _diagnostic(result):
    df = result.enriched
    flags = df.loc[df["ANOMALY_FLAGS"].ne("")].copy()
    counts = flags["ANOMALY_FLAGS"].str.split(";").explode().value_counts()
    categories = []
    for key, count in counts.items():
        categories.append({"flag": key, "records": int(count), "share": round(float(count / max(len(df), 1)), 5)})
    selected = [c for c in ["MSG_TIMESTAMP", "ASSET_KEY", "ANOMALY_FLAGS", "ACTTORQUE", "ACTVEL", "POSITION_ERROR",
                            "ACTTIME_MS", "MOVETOTBASTIME_MS", "MOVETOWORKTIME_MS", "DIAGNO", "MOVEMENTCOUNTER"] if c in flags]
    events = flags.sort_values("MSG_TIMESTAMP", ascending=False) if "MSG_TIMESTAMP" in flags else flags
    status_bits = {}
    for col in ("CLASS1DIAG", "CLASS2DIAG", "CLASS3DIAG"):
        if col in df:
            status_bits[col.lower()] = int(df[col].astype(str).str.lower().isin(["true", "1"]).sum())
    return {
        "event_record_count": int(len(flags)),
        "flag_counts": categories,
        "events": _records(events[selected], 100),
        "diagnostic_status_bits": status_bits,
        "notes": [
            "异常阈值由本次导出窗口的稳健统计量生成，用于筛查，尚未按机型/工艺阶段校准。",
            "连续快照逐行计数，不代表独立故障次数。",
            "CLASS 诊断位和 DIAGNO 尚未关联驱动手册编码表，按原始状态展示，不自动解释为故障原因。",
        ],
    }


def _lifecycle(result):
    assets = result.asset_summary.copy()
    output = []
    screened = result.enriched["ANOMALY_FLAGS"].map(
        lambda text: any(flag and not flag.startswith("CLASS") for flag in str(text).split(";"))
    )
    screened_rate = float(screened.mean()) if len(screened) else 0.0
    for row in assets.to_dict(orient="records"):
        rate = screened_rate
        # Health score measures statistical deviation share only; unverified diagnostic bits are excluded.
        score = max(0.0, min(100.0, 100.0 - 100.0 * rate))
        state = "critical" if score < 50 else "degradation" if score < 70 else "watch" if score < 90 else "normal"
        output.append({
            "asset_key": row["asset_key"], "signal_score": round(score, 1), "state": state,
            "screened_record_rate": round(rate, 5),
            "movement_counter_max": _json_value(row.get("movementcounter_max")),
            "observation_hours": result.data_quality.get("time_window_hours"),
            "evidence": ["异常筛查行占比"],
        })
    return {
        "assets": output,
        "method": "健康分 = 100 × (1 − 当前数据窗中含已实现统计异常标记的快照比例)。此为可解释的筛查分，不是可靠性概率或安全评级。",
        "notes": [
            "状态只表示当前数据窗内的信号偏离程度，不代表部件真实生命周期阶段。",
            "必须按同设备、负载、配方和动作阶段积累多周/多月历史，并结合检修确认来校准状态迁移。",
        ],
    }


def _predictive(raw, result):
    cols = {name: next((c for c in candidates if c in raw.columns), None) for name, candidates in PREDICTOR_COLUMNS.items()}
    assets = raw[cols["asset"]].nunique(dropna=True) if cols["asset"] else result.data_quality.get("asset_count", 0)
    event_column = cols["event"]
    event_count = 0
    if event_column:
        event_count = int(raw[event_column].astype(str).str.lower().isin(["true", "1", "yes", "failed", "replaced"]).sum())
    return predictive_summary(cols,int(assets or 0),event_count,result.data_quality.get('time_window_hours',0))


def predictive_summary(cols,assets,event_count,window_hours):
    event_column=cols["event"]
    reasons = []
    if not cols["asset"]:
        reasons.append("缺少能区分单个伺服轴/气缸的资产唯一 ID。")
    if not cols["age"]:
        reasons.append("缺少设备累计循环数、运行小时或明确的生命周期年龄字段。")
    if not event_column:
        reasons.append("缺少失效/更换/维护事件标签，无法监督拟合寿命分布。")
    elif event_count < 30:
        reasons.append(f"事件标签只有 {event_count} 条；当前流程至少要求 30 个确认事件作为初筛门槛。")
    if window_hours < 24 * 30:
        reasons.append("本次时间覆盖不足 30 天，暂不拟合时间退化或阈值到达趋势。")
    return {
        "status": "not_ready" if reasons else "eligible_for_model_review",
        "rul_estimate": None,
        "detected_columns": cols,
        "distinct_assets": int(assets or 0),
        "confirmed_event_rows": event_count,
        "reasons": reasons or ["字段满足最小检查；仍需验证失效定义、删失规则与按设备分组的时间外验证。"],
        "candidate_models": [
            {"model": "Weibull 生存分析", "requires": "每台设备的使用年龄、失效/删失状态、多个设备生命周期"},
            {"model": "健康指标阈值到达时间", "requires": "长期连续健康指标趋势、经维护确认的阈值"},
            {"model": "XGBoost/时序模型", "requires": "多设备、多种失效模式、无泄漏的时间切分和足量失效样本"},
        ],
        "message": "当前不输出剩余寿命数值。满足数据条件后再选择模型并进行时间外验证，避免伪精确预测。",
    }


def analyze_dataset(csv_path: Path, dictionary_path: Path | None = None, sheet=None,progress=None,cancel=None) -> dict:
    """Analyze a selected CSV export and return compact, serializable views."""
    # Use the known PLC dictionary as metadata only; it does not define fault thresholds.
    from .local_source import local_stream
    csv_path=Path(csv_path).resolve()
    stream,source=local_stream(csv_path,sheet)
    name=csv_path.name+(f" · {source['sheet']}" if source['sheet'] else '')
    return analyze_stream(stream,name,dictionary_path,csv_path.stat().st_size,source,progress,cancel)


def analyze_stream(stream,dataset_name,dictionary_path=None,source_bytes=None,source=None,progress=None,cancel=None):
    from .disk_analysis import DiskAnalysis
    from src.web_logging import get_logger
    engine=DiskAnalysis(progress,cancel)
    try:
        for frame in stream:
            if cancel is not None and cancel.is_set():raise ValueError('分析已取消，未返回部分结果。')
            engine.add(frame)
        if not engine.rows:raise ValueError('所选数据范围没有记录。')
        engine.prepare()
        if cancel is not None and cancel.is_set():raise ValueError('分析已取消，未返回部分结果。')
        result=engine.result(dataset_name,dictionary_path,source or {},source_bytes)
        get_logger().write_log('INFO','web.analysis',f'FULL_ANALYSIS_COMPLETE | rows={engine.rows} | disk_statistics=True')
        return result
    finally:
        close=getattr(stream,'close',None)
        if close:close()
        engine.close()


def analyze_frame(raw, dataset_name, dictionary_path=None, source_bytes=None, source=None):
    """Shared pipeline for bounded database reads and local exports."""
    raw = raw.copy()
    raw.columns = [str(c).strip().upper() for c in raw.columns]
    if raw.columns.duplicated().any():
        raise ValueError('字段名大小写归一化后重复，请调整源字段。')
    result = analyze_dataframe(raw)
    dictionary = []
    if dictionary_path and dictionary_path.exists():
        lookup = pd.read_excel(dictionary_path)
        dictionary = _records(lookup, 200)
    return {
        "run_id": uuid.uuid4().hex,
        "dataset": dataset_name,
        "source_bytes": source_bytes,
        "source": source or {"kind": "csv"},
        "dictionary": dictionary,
        "descriptive": _descriptive(raw, result),
        "diagnostic": _diagnostic(result),
        "lifecycle": _lifecycle(result),
        "predictive": _predictive(raw, result),
        "engine": "local-statistical-v1",
    }


def save_result(result: dict, output_root: Path) -> Path:
    run_dir = output_root / result["run_id"]
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return run_dir
