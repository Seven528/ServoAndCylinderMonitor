"""Read explicitly selected local CSV/XLSX files with bounded row counts."""
from __future__ import annotations

from pathlib import Path
from zipfile import BadZipFile, ZipFile

import pandas as pd

MAX_FILE_BYTES = 1024 * 1024 * 1024
MAX_XLSX_BYTES = 64 * 1024 * 1024
MAX_EXPANDED_BYTES = 256 * 1024 * 1024
MAX_LOCAL_ROWS = 100_000
MAX_COLUMNS = 500


def validate_file(path):
    path = Path(path).expanduser()
    if not path.is_absolute():
        raise ValueError('请输入完整的绝对文件路径，或点击选择文件。')
    path = path.resolve()
    if path.suffix.lower() not in ('.csv', '.xlsx'):
        raise ValueError('本地分析支持 CSV 或 XLSX 文件。')
    if not path.is_file():
        raise ValueError('该文件不存在或不是普通文件，请检查文件路径。')
    limit = MAX_XLSX_BYTES if path.suffix.lower() == '.xlsx' else MAX_FILE_BYTES
    if path.stat().st_size > limit:
        raise ValueError('文件超过大小限制：CSV 1 GiB，XLSX 64 MiB。请按时间/设备拆分。')
    return path


def inspect_file(path):
    path = validate_file(path)
    sheets = []
    if path.suffix.lower() == '.xlsx':
        try:
            with ZipFile(path) as archive:
                if sum(info.file_size for info in archive.infolist()) > MAX_EXPANDED_BYTES:
                    raise ValueError('XLSX 展开后的内容超过 256 MiB，请拆分文件。')
            with pd.ExcelFile(path, engine='openpyxl') as book:
                sheets = book.sheet_names
        except (BadZipFile, KeyError, OSError):
            raise ValueError('无法打开 XLSX，请确认文件格式正确、没有加密且未损坏。') from None
        if not sheets or len(sheets) > 100:
            raise ValueError('工作表数量须为 1–100 个。')
    return {'name': path.name, 'bytes': path.stat().st_size, 'sheets': sheets}


def load_frame(path, sheet=None):
    path = validate_file(path)
    details = inspect_file(path)
    if path.suffix.lower() == '.xlsx':
        selected = sheet if sheet is not None else details['sheets'][0]
        if selected not in details['sheets']:
            raise ValueError('所选工作表不存在，请重新选择文件。')
        frame = pd.read_excel(path, sheet_name=selected, engine='openpyxl', nrows=MAX_LOCAL_ROWS+1)
        kind = 'xlsx'
    else:
        if sheet is not None:
            raise ValueError('CSV 文件不支持工作表选择。')
        frame = None
        for encoding in ('utf-8-sig', 'gb18030'):
            try:
                frame = pd.read_csv(path, encoding=encoding, low_memory=False, nrows=MAX_LOCAL_ROWS+1)
                break
            except UnicodeDecodeError:
                continue
        if frame is None:
            raise ValueError('无法识别 CSV 编码，请另存为 UTF-8 CSV。')
        kind, selected = 'csv', None
    if frame.empty:
        raise ValueError('文件或工作表没有数据。')
    if len(frame) > MAX_LOCAL_ROWS:
        raise ValueError('本地文件超过 100,000 行，请按设备/时间拆分，或使用 ClickHouse 范围查询；不会截断分析。')
    if len(frame.columns) > MAX_COLUMNS:
        raise ValueError('数据超过 500 列，请选择运行数据工作表。')
    return frame, {'kind': kind, 'filename': path.name, 'sheet': selected}
