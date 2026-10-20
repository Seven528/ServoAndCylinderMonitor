"""Bounded ClickHouse HTTP reads; credentials live only in the server session."""
from __future__ import annotations

import http.client
import json
import re
import socket
import ssl
import time
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

import pandas as pd

MAX_ROWS = 100_000
MAX_BYTES = 64 * 1024 * 1024
MAX_LINE = 2 * 1024 * 1024
IDENTIFIER = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


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
                # Do not echo remote errors: these may contain query details or credentials.
                raise ValueError(f'ClickHouse 返回 HTTP {response.status}；请检查认证、库表权限与服务器查询限制。')
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
                    raise ValueError('ClickHouse 未返回完整 JSONEachRow 数据；查询可能超时或超过服务器限制。') from None
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
    params = {'param_start': str(int(start.timestamp()*1000)), 'param_end': str(int(end.timestamp()*1000))}
    time_id = identifier(time_column)
    where = f'{time_id} >= fromUnixTimestamp64Milli({{start:Int64}}) AND {time_id} < fromUnixTimestamp64Milli({{end:Int64}})'
    station_column = options.get('station_column', '')
    station = options.get('station', '')
    if not isinstance(station, str) or len(station) > 200:
        raise ValueError('站点筛选值无效。')
    if station:
        if station_column not in known:
            raise ValueError('请为站点筛选选择有效字段。')
        where += f' AND toString({identifier(station_column)}) = {{station:String}}'
        params['param_station'] = station
    sql = (f'SELECT *, toUnixTimestamp64Milli(toDateTime64({time_id}, 3)) AS __agent_timestamp_ms '
           f'FROM {identifier(connection.database)}.{identifier(connection.table)} WHERE {where} '
           f'ORDER BY {time_id} LIMIT {limit+1} FORMAT JSONEachRow')
    metadata = {'kind': 'clickhouse', 'database': connection.database, 'table': connection.table,
                'start': start.isoformat(), 'end_exclusive': end.isoformat(), 'time_column': time_column,
                'station_column': station_column if station else None, 'station': station or None, 'max_rows': limit}
    return sql, params, metadata


def read_frame(connection, columns, options):
    sql, params, metadata = build_read(connection, columns, options)
    rows = connection.query(sql, params)
    if len(rows) > metadata['max_rows']:
        raise ValueError('查询结果超过最大行数；为避免截断造成误判，请缩小时间范围或增加站点筛选。')
    if not rows:
        raise ValueError('所选时间与站点范围没有数据，请调整筛选条件。')
    frame = pd.DataFrame(rows)
    if '__agent_timestamp_ms' not in frame:
        raise ValueError('API 返回数据缺少标准化时间字段。')
    frame = frame.drop(columns=[c for c in frame if c.upper() == 'MSG_TIMESTAMP'])
    frame['MSG_TIMESTAMP'] = pd.to_datetime(frame.pop('__agent_timestamp_ms'), unit='ms', utc=True)
    metadata['rows'] = len(frame)
    return frame, metadata
