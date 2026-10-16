
import ast
import pandas as pd


def parse_ltime(value, byteorder="little"):
    """
    解析 PLC LTIME 字节数组。

    Parameters
    ----------
    value : list | str | bytes
        例如 [92,157,102,84,0,0,0,0]
        或 '[92,157,102,84,0,0,0,0]'
    byteorder : str
        little 或 big

    Returns
    -------
    tuple
        (nanoseconds, milliseconds, ltime_string)
    """

    if value is None or value is pd.NA:
        return None, None, None

    # 支持字符串格式的数组
    if isinstance(value, str):
        if not value.strip():
            return None, None, None
        value = ast.literal_eval(value)

    # 检查字节数量及范围
    if (
        not isinstance(value, (list, tuple, bytes, bytearray))
        or len(value) != 8
    ):
        raise ValueError(f"无效的 LTIME 数据: {value}")

    raw_bytes = bytes(value)

    # 8字节转换成有符号64位整数，单位ns
    ns = int.from_bytes(
        raw_bytes,
        byteorder=byteorder,
        signed=True
    )

    ms = ns / 1_000_000

    # 转换成 LTIME 展示格式
    sign = "-" if ns < 0 else ""
    absolute_ns = abs(ns)

    seconds, remainder = divmod(absolute_ns, 1_000_000_000)
    milliseconds, remainder = divmod(remainder, 1_000_000)
    microseconds, nanoseconds = divmod(remainder, 1_000)

    ltime_str = (
        f"LTIME#{sign}{seconds}s"
        f"{milliseconds}ms"
        f"{microseconds}us"
        f"{nanoseconds}ns"
    )

    return ns, ms, ltime_str


def convert_ltime_columns(
    df: pd.DataFrame,
    columns: list[str],
    byteorder: str = "little",
    include_ns: bool = False
) -> pd.DataFrame:
    """
    批量转换 DataFrame 中的 LTIME 字段。

    原始列保留，新增:
        {col}_ms
        {col}_LTIME
        {col}_ns (可选)
    """

    result = df.copy()

    for col in columns:
        if col not in result.columns:
            raise KeyError(f"DataFrame 中不存在字段: {col}")

        parsed = result[col].apply(
            lambda x: parse_ltime(x, byteorder)
        )

        if include_ns:
            result[f"{col}_ns"] = pd.array(
                parsed.map(lambda x: x[0]),
                dtype="Int64"
            )

        result[f"{col}_ms"] = parsed.map(
            lambda x: x[1]
        )

        result[f"{col}_LTIME"] = parsed.map(
            lambda x: x[2]
        )

    return result
