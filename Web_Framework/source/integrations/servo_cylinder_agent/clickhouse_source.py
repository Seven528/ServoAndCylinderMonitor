"""Streaming ClickHouse HTTP reads; credentials live only in the server session."""
from __future__ import annotations

import http.client
import json
import re
import socket
import ssl
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

import pandas as pd

from src.web_logging import get_logger

BATCH_ROWS = 10_000
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
    158: ('TOO_MANY_ROWS', '数据库仍限制扫描行数；应用已请求不限行数，请管理员检查账号/集群不可覆盖的 max_rows_to_read 或 leaf 限制。'),
    159: ('TIMEOUT_EXCEEDED', '数据库执行超时；应用未设置总执行时限，请管理员检查账号或代理的执行时间限制。'),
    164: ('READONLY', '账号不允许修改查询设置，请让管理员检查账号配置；应用不会修改表数据。'),
    241: ('MEMORY_LIMIT_EXCEEDED', '数据库查询超过内存上限，请缩小查询范围。'),
    307: ('TOO_MANY_ROWS_OR_BYTES', '数据库账号仍限制结果数量/大小；应用已请求不限，请管理员检查不可覆盖的设置。'),
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

    def iter_rows(self,sql,params=None,byte_limit=None):
        u=urlsplit(self.endpoint)
        # Zero means unrestricted in ClickHouse. Do not inherit the former
        # application caps, including distributed leaf limits.
        settings={'database':self.database,'readonly':'2',
                  'max_rows_to_read':'0','max_bytes_to_read':'0',
                  'max_rows_to_read_leaf':'0','max_bytes_to_read_leaf':'0',
                  'max_result_rows':'0','max_result_bytes':'0',
                  'max_execution_time':'0','max_execution_time_leaf':'0',
                  'result_overflow_mode':'throw','read_overflow_mode':'throw',
                  'output_format_json_quote_64bit_integers':'0'}
        settings.update(params or {})
        path=(u.path or '/')+'?'+urlencode(settings)
        conn_class=http.client.HTTPSConnection if u.scheme=='https' else http.client.HTTPConnection
        # An inactivity timeout, not a total query-duration or record limit.
        conn=conn_class(u.hostname,u.port,timeout=300)
        try:
            conn.request('POST',path,body=sql.encode('utf-8'),headers={
                'X-ClickHouse-User':self.username,'X-ClickHouse-Key':self.password,
                'Content-Type':'text/plain; charset=utf-8','Accept-Encoding':'identity'})
            response=conn.getresponse()
            if response.status!=200:
                code=response.getheader('X-ClickHouse-Exception-Code') if hasattr(response,'getheader') else None
                raise ClickHouseError(response.status,response.read(8192),code)
            total=0
            while True:
                line=response.readline()
                if not line:break
                total+=len(line)
                # Only metadata probes opt into a byte bound. Data reads do not.
                if byte_limit is not None and total>byte_limit:
                    raise ValueError('连接检查返回的元数据过大。')
                if not line.strip():continue
                try:row=json.loads(line)
                except (ValueError,UnicodeError):raise ClickHouseError(200,line) from None
                if not isinstance(row,dict):raise ValueError('API 需返回 ClickHouse JSONEachRow 数据。')
                yield row
        except (OSError,socket.timeout,ssl.SSLError,http.client.HTTPException,UnicodeError):
            raise ValueError('ClickHouse 连接中断或长时间没有响应；请检查网络、地址和代理超时。未返回截断分析结果。') from None
        finally:conn.close()

    def query(self,sql,params=None,byte_limit=None):
        """For small metadata responses; data analysis uses iter_rows."""
        return list(self.iter_rows(sql,params,byte_limit))

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
    if end<=start:
        raise ValueError('结束时间须晚于开始时间。')
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
            'EXEUTE','EXECUTE','ACCELERATING','DECELERATING','DRIVEENABLED','DRIVEREADYFORMOVEMENT','AXISINREFERENCE',
            'ASSET_ID','DEVICE_ID','EQUIPMENT_ID','CYLINDER_ID','AXIS_ID','AGE_CYCLES','AGE_HOURS','AGE_DAYS',
            'OPERATING_HOURS','FAILURE_EVENT','FAILED','FAILURE_FLAG','REPLACED'}
    projection = ', '.join(identifier(name) for name in known if name.upper() in used)
    projection = (projection + ', ') if projection else ''
    # Sorting is done by the shared local pipeline. Avoid an expensive warehouse
    # ORDER BY. All matching records are streamed without LIMIT.
    sql = (f"SELECT {projection}toString({time_id}, 'UTC') AS __agent_timestamp_utc "
           f'FROM {identifier(connection.database)}.{identifier(connection.table)} WHERE {where} '
           'FORMAT JSONEachRow')
    metadata = {'kind': 'clickhouse', 'database': connection.database, 'table': connection.table,
                'start': start.isoformat(), 'end_exclusive': end.isoformat(), 'time_column': time_column,
                'station_column': station_column if station else None, 'station': station or None, 'unlimited': True}
    return sql, params, metadata


def normalize_frame(frame):
    if '__agent_timestamp_utc' in frame:
        timestamp=pd.to_datetime(frame.pop('__agent_timestamp_utc'),utc=True,errors='coerce')
    elif '__agent_timestamp_ms' in frame:
        timestamp=pd.to_datetime(frame.pop('__agent_timestamp_ms'),unit='ms',utc=True,errors='coerce')
    else:raise ValueError('API 返回数据缺少标准化时间字段。')
    if timestamp.isna().any():raise ValueError('返回数据包含无效时间戳，请核对时间字段。')
    frame=frame.drop(columns=[c for c in frame if c.upper()=='MSG_TIMESTAMP'])
    frame['MSG_TIMESTAMP']=timestamp
    return frame


def read_stream(connection,columns,options,batch_rows=BATCH_ROWS):
    sql,params,metadata=build_read(connection,columns,options)
    def chunks():
        count=0;batch=[]
        get_logger().write_log('INFO','web.clickhouse',f"READ_START | table={connection.database}.{connection.table} | unlimited=True")
        for row in connection.iter_rows(sql,params):
            batch.append(row)
            if len(batch)>=batch_rows:
                count+=len(batch)
                yield normalize_frame(pd.DataFrame(batch));batch=[]
        if batch:
            count+=len(batch);yield normalize_frame(pd.DataFrame(batch))
        if not count:raise ValueError('所选时间与站点范围没有数据，请调整筛选条件。')
        metadata['rows']=count
        get_logger().write_log('INFO','web.clickhouse',f'READ_COMPLETE | rows={count} | unlimited=True')
    return chunks(),metadata


def read_frame(connection,columns,options):
    """Compatibility helper, not used by the production streaming pipeline."""
    stream,metadata=read_stream(connection,columns,options)
    return pd.concat(stream,ignore_index=True),metadata
