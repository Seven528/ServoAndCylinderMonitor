"""Bounded ClickHouse HTTP reads; credentials live only in the server session."""
from __future__ import annotations

import http.client
import json
import re
import socket
import ssl
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

import pandas as pd

from src.web_logging import get_logger

MAX_ROWS = 100_000
MAX_BYTES = 64 * 1024 * 1024
MAX_LINE = 2 * 1024 * 1024
IDENTIFIER = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


ERRORS = {
    8: ('THERE_IS_NO_COLUMN', '字段不存在，请重新检查连接并选择字段。'),
    16: ('NO_SUCH_COLUMN_IN_TABLE', '字段不存在，请重新检查目标表。'),
    41: ('CANNOT_PARSE_DATETIME', '时间转换失败，请核对时间字段的类型。'),
    43: ('ILLEGAL_TYPE_OF_ARGUMENT', '字段类型不兼容，请确认时间字段为 DateTime/DateTime64。'),
    46: ('UNKNOWN_FUNCTION', '数据库版本不支持查询中的函数，请联系维护人员检查版本兼容性。'),
    47: ('UNKNOWN_IDENTIFIER', '查询字段不存在，请重新检查连接以刷新字段列表。'),
    60: ('UNKNOWN_TABLE', '目标表不存在或没有访问权限，请核对库表。'),
    62: ('SYNTAX_ERROR', '数据库不支持当前查询语法，请检查版本及 HTTP 网关。'),
    81: ('UNKNOWN_DATABASE', '数据库不存在，请核对库名。'),
    115: ('UNKNOWN_SETTING', '数据库不支持某个查询限制设置，请检查服务器版本。'),
    158: ('TOO_MANY_ROWS', '扫描行数超过上限（与返回行数不同）；请缩短时间范围并选择站点。'),
    159: ('TIMEOUT_EXCEEDED', '查询超过执行时间上限，请缩短时间范围并选择站点。'),
    164: ('READONLY', '账号不允许修改查询设置，请让管理员检查账号配置；应用不会修改表数据。'),
    241: ('MEMORY_LIMIT_EXCEEDED', '数据库查询超过内存上限，请缩小查询范围。'),
    307: ('TOO_MANY_ROWS_OR_BYTES', '返回结果超过数据库行数或大小限制，请缩小范围。'),
    452: ('SETTING_CONSTRAINT_VIOLATION', '查询设置超出账号允许范围，请由管理员检查账号限制。'),
    497: ('ACCESS_DENIED', '账号缺少目标表的 SELECT 权限，请联系管理员。'),
    516: ('AUTHENTICATION_FAILED', '账号认证失败，请检查用户名和密码。'),
}


class ClickHouseError(ValueError):
    def __init__(self, status, body=b'', code_header=None):
        text = body.decode('utf-8', errors='replace')
        match = re.search(r'\bCode:\s*(\d+)', text)
        code = str(code_header or (match.group(1) if match else ''))
        self.code = int(code) if code.isdigit() else None
        name, hint = ERRORS.get(self.code, ('', '服务器拒绝查询，请提供异常码给维护人员核对。'))
        if status in (401, 403) and self.code is None:
            hint = '账号认证或访问权限不足，请检查连接配置。'
        label = f'Code {self.code}' if self.code is not None else '未返回异常码'
        super().__init__(f'ClickHouse HTTP {status} · {label}' + (f' · {name}' if name else '') + f'：{hint}')


def identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError('库、表与字段名仅支持英文字母、数字、下划线，且不能以数字开头。')
    return '`' + value + '`'


@dataclass(frozen=True)
class Connection:
    endpoint: str
    database: str
    table: str
    username: str = field(repr=False)
    password: str = field(repr=False)

    @classmethod
    def parse(cls, data):
        if not isinstance(data, dict):
            raise ValueError('请填写 ClickHouse 连接信息。')
        endpoint = str(data.get('endpoint', '')).strip()
        try:
            u = urlsplit(endpoint)
            valid = u.scheme in ('http', 'https') and u.hostname and u.port != 0
        except ValueError:
            valid = False
        if not valid or u.username or u.password or u.query or u.fragment or any(c.isspace() for c in endpoint):
            raise ValueError('请输入 HTTP/HTTPS API 地址；地址中不能包含账号、密码、查询参数或空白。')
        values = {}
        for key in ('database', 'table', 'username', 'password'):
            value = data.get(key, 'default' if key == 'username' else '')
            if not isinstance(value, str) or len(value) > 1024 or any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise ValueError('连接字段格式无效。')
            values[key] = value.strip() if key != 'password' else value
        identifier(values['database']); identifier(values['table'])
        if not values['username']:
            raise ValueError('请填写 ClickHouse 用户名。')
        return cls(endpoint, **values)

    def query(self, sql, params=None, byte_limit=MAX_BYTES):
        u = urlsplit(self.endpoint)
        settings = {'database': self.database, 'readonly': '2', 'max_execution_time': '30',
                    'max_result_rows': str(MAX_ROWS + 1), 'result_overflow_mode': 'throw',
                    'max_rows_to_read': '5000000', 'read_overflow_mode': 'throw',
                    'max_result_bytes': str(MAX_BYTES), 'output_format_json_quote_64bit_integers': '0'}
        settings.update(params or {})
        path = (u.path or '/') + '?' + urlencode(settings)
        conn_class = http.client.HTTPSConnection if u.scheme == 'https' else http.client.HTTPConnection
        conn = conn_class(u.hostname, u.port, timeout=35)
        started = time.monotonic()
        try:
            conn.request('POST', path, body=sql.encode('utf-8'), headers={
                'X-ClickHouse-User': self.username, 'X-ClickHouse-Key': self.password,
                'Content-Type': 'text/plain; charset=utf-8', 'Accept-Encoding': 'identity'})
            response = conn.getresponse()
            if response.status != 200:
                code_header = response.getheader('X-ClickHouse-Exception-Code') if hasattr(response, 'getheader') else None
                raise ClickHouseError(response.status, response.read(8192), code_header)
            rows, total = [], 0
            while True:
                if time.monotonic() - started > 40:
                    raise ValueError('查询超过 40 秒，请缩小时间范围。')
                line = response.readline(MAX_LINE + 1)
                if not line:
                    break
                total += len(line)
                if len(line) > MAX_LINE or total > byte_limit:
                    raise ValueError('返回数据超过大小限制，请缩小时间范围或按站点筛选。')
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except (ValueError, UnicodeError):
                    raise ClickHouseError(200, line) from None
                if not isinstance(row, dict):
                    raise ValueError('API 返回格式无效，需支持 ClickHouse HTTP JSONEachRow。')
                rows.append(row)
                if len(rows) > MAX_ROWS + 1:
                    raise ValueError('返回行数超过限制，请缩小查询范围。')
            return rows
        except (OSError, socket.timeout, ssl.SSLError, http.client.HTTPException, UnicodeError):
            raise ValueError('无法连接 ClickHouse API，请检查网络、地址、端口和 HTTPS 证书。') from None
        finally:
            conn.close()

    def check(self):
        if self.query('SELECT 1 AS ok FORMAT JSONEachRow', byte_limit=1024) != [{'ok': 1}]:
            raise ValueError('API 连接检查未通过。')
        columns = self.query(f'DESCRIBE TABLE {identifier(self.database)}.{identifier(self.table)} FORMAT JSONEachRow', byte_limit=1024*1024)
        if not columns:
            raise ValueError('目标表没有可见字段。')
        return [{'name': row['name'], 'type': row['type']} for row in columns]


def build_read(connection, columns, options):
    if not isinstance(options, dict):
        raise ValueError('请填写查询范围。')
    known = {row['name']: row['type'] for row in columns}
    time_column = options.get('time_column', '')
    if time_column not in known or 'DateTime' not in known[time_column]:
        raise ValueError('时间字段须选择 DateTime 或 DateTime64 类型。')
    identifier(time_column)
    times = []
    for key in ('start', 'end'):
        try:
            value = datetime.fromisoformat(str(options.get(key, '')))
            if value.tzinfo is None:
                value = value.replace(tzinfo=ZoneInfo('Asia/Shanghai'))
            times.append(value)
        except (ValueError, OverflowError):
            raise ValueError('请输入有效的开始与结束时间（北京时间）。') from None
    start, end = times
    if not 0 < (end - start).total_seconds() <= 31 * 86400:
        raise ValueError('结束时间须晚于开始时间，单次时间跨度最多 31 天。')
    raw_limit = options.get('max_rows', 10000)
    if isinstance(raw_limit, bool) or not isinstance(raw_limit, int) or not 100 <= raw_limit <= MAX_ROWS:
        raise ValueError(f'最大行数须为 100–{MAX_ROWS:,} 之间的整数。')
    limit = raw_limit
    params = {'param_start': start.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')[:23],
              'param_end': end.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')[:23]}
    time_id = identifier(time_column)
    where = f"{time_id} >= toDateTime64({{start:String}}, 3, 'UTC') AND {time_id} < toDateTime64({{end:String}}, 3, 'UTC')"
    station_column = options.get('station_column', '')
    station = options.get('station', '')
    if not isinstance(station, str) or len(station) > 200:
        raise ValueError('站点筛选值无效。')
    if station:
        if station_column not in known:
            raise ValueError('请为站点筛选选择有效字段。')
        where += f' AND toString({identifier(station_column)}) = {{station:String}}'
        params['param_station'] = station
    # Only load fields consumed by analysis, excluding large raw Kafka payloads.
    used = {'MSG_TIMESTAMP','PRODUCTTEAM','MACHINETYPE','LINENAME','STATIONNAME','MESSAGENAME',
            'ACTPOS','ACTVEL','ACTTORQUE','SPEED','TARGETPOS','ACTTIME','AVGTIME','MINTIME','MAXTIME','TOTTIME',
            'MOVETOTBASTIME','MOVETOWORKTIME','MOVEMENTCOUNTER','CLASS1DIAG','CLASS2DIAG','CLASS3DIAG','DIAGNO',
            'EXEUTE','EXECUTE','ACCELERATING','DECELERATING','DRIVEENABLED','DRIVEREADYFORMOVEMENT',
            'ASSET_ID','DEVICE_ID','EQUIPMENT_ID','CYLINDER_ID','AXIS_ID','AGE_CYCLES','AGE_HOURS','AGE_DAYS',
            'OPERATING_HOURS','FAILURE_EVENT','FAILED','FAILURE_FLAG','REPLACED'}
    projection = ', '.join(identifier(name) for name in known if name.upper() in used)
    projection = (projection + ', ') if projection else ''
    # Sorting is done by the shared local pipeline. Avoid an expensive warehouse
    # ORDER BY before LIMIT; request one extra row to reject truncated windows.
    sql = (f"SELECT {projection}toString({time_id}, 'UTC') AS __agent_timestamp_utc "
           f'FROM {identifier(connection.database)}.{identifier(connection.table)} WHERE {where} '
           f'LIMIT {limit+1} FORMAT JSONEachRow')
    metadata = {'kind': 'clickhouse', 'database': connection.database, 'table': connection.table,
                'start': start.isoformat(), 'end_exclusive': end.isoformat(), 'time_column': time_column,
                'station_column': station_column if station else None, 'station': station or None, 'max_rows': limit}
    return sql, params, metadata


def read_frame(connection, columns, options):
    sql, params, metadata = build_read(connection, columns, options)
    get_logger().write_log('INFO', 'web.clickhouse', f"READ_START | table={connection.database}.{connection.table} | start={metadata['start']} | end={metadata['end_exclusive']} | limit={metadata['max_rows']}")
    rows = connection.query(sql, params)
    if len(rows) > metadata['max_rows']:
        raise ValueError('查询结果超过最大行数；为避免截断造成误判，请缩小时间范围或增加站点筛选。')
    if not rows:
        raise ValueError('所选时间与站点范围没有数据，请调整筛选条件。')
    frame = pd.DataFrame(rows)
    # Legacy alias is accepted for older cached/mocked responses.
    if '__agent_timestamp_utc' in frame:
        timestamp = pd.to_datetime(frame.pop('__agent_timestamp_utc'), utc=True, errors='coerce')
    elif '__agent_timestamp_ms' in frame:
        timestamp = pd.to_datetime(frame.pop('__agent_timestamp_ms'), unit='ms', utc=True, errors='coerce')
    else:
        raise ValueError('API 返回数据缺少标准化时间字段。')
    if timestamp.isna().any():
        raise ValueError('返回数据包含无效时间戳，请核对时间字段。')
    frame = frame.drop(columns=[c for c in frame if c.upper() == 'MSG_TIMESTAMP'])
    frame['MSG_TIMESTAMP'] = timestamp
    metadata['rows'] = len(frame)
    get_logger().write_log('INFO', 'web.clickhouse', f'READ_COMPLETE | rows={len(frame)}')
    return frame, metadata
