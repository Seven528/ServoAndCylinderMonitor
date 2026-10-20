"""Connector boundary checks without warehouse access."""
import io
import json
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from integrations.servo_cylinder_agent.clickhouse_source import Connection, build_read, read_frame
CONFIG={'endpoint':'https://warehouse.example:8443/','database':'KAFKA','table':'runtime','username':'reader','password':'test-secret'}
COLUMNS=[{'name':'msg_timestamp','type':'DateTime64(3)'},{'name':'STATIONNAME','type':'String'}]
OPTIONS={'time_column':'msg_timestamp','start':'2026-10-20T08:00','end':'2026-10-20T09:00','max_rows':100,'station_column':'STATIONNAME','station':"ST401' OR 1=1 --"}
class FakeHTTP:
 payload=b'{"ok":1}\n'; status=200; last=None
 def __init__(self,*args,**kwargs): type(self).last=self; self.closed=False
 def request(self,method,path,body,headers): self.request_data=(method,path,body,headers)
 def getresponse(self):
  response=io.BytesIO(type(self).payload);response.status=type(self).status;return response
 def close(self): self.closed=True
class ConnectorTests(unittest.TestCase):
 def setUp(self):
  self.connection=Connection.parse(CONFIG);FakeHTTP.payload=b'{"ok":1}\n';FakeHTTP.status=200
 def test_parameterized_filter_and_half_open_window(self):
  sql,params,meta=build_read(self.connection,COLUMNS,OPTIONS)
  self.assertNotIn(OPTIONS['station'],sql);self.assertEqual(params['param_station'],OPTIONS['station'])
  self.assertIn('< fromUnixTimestamp64Milli',sql);self.assertIn('LIMIT 101',sql)
  self.assertTrue(meta['start'].endswith('+08:00'));self.assertEqual(int(params['param_end'])-int(params['param_start']),3600000)
 def test_bad_identifiers(self):
  for key in ('database','table'):
   with self.assertRaises(ValueError):Connection.parse({**CONFIG,key:'a; DROP TABLE x'})
 def test_bad_endpoints(self):
  for url in ('file:///tmp/data','http://u:p@example.com','https://example.com/?x=1','http://example.com:bad','http://example.com\r\nX:1'):
   with self.subTest(url=url),self.assertRaises(ValueError):Connection.parse({**CONFIG,'endpoint':url})
 def test_no_credentials_in_repr(self):
  self.assertNotIn(CONFIG['password'],repr(self.connection));self.assertNotIn(CONFIG['username'],repr(self.connection))
 def test_bad_limits_and_time_fields(self):
  for change in ({'max_rows':100001},{'max_rows':True},{'max_rows':1.5},{'start':OPTIONS['end']},{'end':'2027-01-01T00:00'},{'time_column':'STATIONNAME'}):
   with self.subTest(change=change),self.assertRaises(ValueError):build_read(self.connection,COLUMNS,{**OPTIONS,**change})
 @patch('integrations.servo_cylinder_agent.clickhouse_source.http.client.HTTPSConnection',FakeHTTP)
 def test_http_headers_limits_and_close(self):
  self.assertEqual(self.connection.query('SELECT 1 FORMAT JSONEachRow'),[{'ok':1}])
  method,path,body,headers=FakeHTTP.last.request_data
  self.assertEqual(method,'POST');self.assertEqual(headers['X-ClickHouse-Key'],CONFIG['password']);self.assertNotIn(CONFIG['password'],path)
  self.assertEqual(parse_qs(urlsplit(path).query)['readonly'],['2']);self.assertTrue(FakeHTTP.last.closed)
 @patch('integrations.servo_cylinder_agent.clickhouse_source.http.client.HTTPSConnection',FakeHTTP)
 def test_remote_error_not_reflected(self):
  FakeHTTP.status=401;FakeHTTP.payload=CONFIG['password'].encode()
  with self.assertRaises(ValueError) as caught:self.connection.query('SELECT 1')
  self.assertNotIn(CONFIG['password'],str(caught.exception));self.assertTrue(FakeHTTP.last.closed)
 @patch('integrations.servo_cylinder_agent.clickhouse_source.http.client.HTTPSConnection',FakeHTTP)
 def test_mid_stream_error_rejects_partial_results(self):
  FakeHTTP.payload=b'{"ok":1}\nCode: 159 query timed out\n'
  with self.assertRaises(ValueError):self.connection.query('SELECT 1')
 @patch('integrations.servo_cylinder_agent.clickhouse_source.http.client.HTTPSConnection',FakeHTTP)
 def test_byte_limit(self):
  with self.assertRaises(ValueError):self.connection.query('SELECT 1',byte_limit=3)
 def test_truncation_rejected(self):
  with patch.object(Connection,'query',return_value=[{}]*101):
   with self.assertRaisesRegex(ValueError,'超过最大行数'):read_frame(self.connection,COLUMNS,OPTIONS)
 def test_empty(self):
  with patch.object(Connection,'query',return_value=[]):
   with self.assertRaisesRegex(ValueError,'没有数据'):read_frame(self.connection,COLUMNS,OPTIONS)
 def test_timestamp_normalization(self):
  row={'msg_timestamp':'2026-10-20 08:00:00','__agent_timestamp_ms':1792454400000,'ACTTORQUE':1}
  with patch.object(Connection,'query',return_value=[row]):frame,meta=read_frame(self.connection,COLUMNS,OPTIONS)
  self.assertNotIn('msg_timestamp',frame);self.assertEqual(str(frame['MSG_TIMESTAMP'].dtype),'datetime64[ns, UTC]');self.assertEqual(meta['rows'],1)
  self.assertNotIn('password',json.dumps(meta))
if __name__=='__main__':unittest.main()
