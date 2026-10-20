"""Connector boundary checks without warehouse access."""
import io
import json
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from integrations.servo_cylinder_agent.clickhouse_source import Connection, build_read, read_frame, read_stream
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
  self.assertIn('< toDateTime64',sql);self.assertNotIn('LIMIT',sql);self.assertNotIn('ORDER BY',sql);self.assertTrue(meta['unlimited'])
  self.assertTrue(meta['start'].endswith('+08:00'));self.assertEqual(params['param_start'],'2026-10-20 00:00:00.000');self.assertEqual(params['param_end'],'2026-10-20 01:00:00.000')
 def test_bad_identifiers(self):
  for key in ('database','table'):
   with self.assertRaises(ValueError):Connection.parse({**CONFIG,key:'a; DROP TABLE x'})
 def test_bad_endpoints(self):
  for url in ('file:///tmp/data','http://u:p@example.com','https://example.com/?x=1','http://example.com:bad','http://example.com\r\nX:1'):
   with self.subTest(url=url),self.assertRaises(ValueError):Connection.parse({**CONFIG,'endpoint':url})
 def test_no_credentials_in_repr(self):
  self.assertNotIn(CONFIG['password'],repr(self.connection));self.assertNotIn(CONFIG['username'],repr(self.connection))
 def test_bad_limits_and_time_fields(self):
  for change in ({'start':OPTIONS['end']},{'time_column':'STATIONNAME'}):
   with self.subTest(change=change),self.assertRaises(ValueError):build_read(self.connection,COLUMNS,{**OPTIONS,**change})
 @patch('integrations.servo_cylinder_agent.clickhouse_source.http.client.HTTPSConnection',FakeHTTP)
 def test_http_headers_limits_and_close(self):
  self.assertEqual(self.connection.query('SELECT 1 FORMAT JSONEachRow'),[{'ok':1}])
  method,path,body,headers=FakeHTTP.last.request_data
  self.assertEqual(method,'POST');self.assertEqual(headers['X-ClickHouse-Key'],CONFIG['password']);self.assertNotIn(CONFIG['password'],path)
  settings=parse_qs(urlsplit(path).query)
  self.assertEqual(settings['readonly'],['2'])
  for key in ('max_rows_to_read','max_bytes_to_read','max_rows_to_read_leaf','max_bytes_to_read_leaf','max_result_rows','max_result_bytes','max_execution_time','max_execution_time_leaf'):self.assertEqual(settings[key],['0'])
  self.assertTrue(FakeHTTP.last.closed)
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
 def test_stream_has_no_former_row_limit(self):
  rows=[{'msg_timestamp':'2026-10-20 08:00:00','__agent_timestamp_ms':1792454400000,'ACTTORQUE':1}]*101
  with patch.object(Connection,'iter_rows',return_value=iter(rows)):
   chunks,meta=read_stream(self.connection,COLUMNS,OPTIONS,batch_rows=20)
   self.assertEqual(sum(len(chunk) for chunk in chunks),101);self.assertEqual(meta['rows'],101)
 def test_long_window_and_legacy_row_cap_are_not_limits(self):
  sql,_,meta=build_read(self.connection,COLUMNS,{**OPTIONS,'end':'2027-01-01T00:00','max_rows':100001})
  self.assertNotIn('LIMIT',sql);self.assertTrue(meta['unlimited'])
 def test_empty(self):
  with patch.object(Connection,'iter_rows',return_value=iter([])):
   with self.assertRaisesRegex(ValueError,'没有数据'):read_frame(self.connection,COLUMNS,OPTIONS)
 def test_timestamp_normalization(self):
  row={'msg_timestamp':'2026-10-20 08:00:00','__agent_timestamp_ms':1792454400000,'ACTTORQUE':1}
  with patch.object(Connection,'iter_rows',return_value=iter([row])):frame,meta=read_frame(self.connection,COLUMNS,OPTIONS)
  self.assertNotIn('msg_timestamp',frame);self.assertEqual(str(frame['MSG_TIMESTAMP'].dtype),'datetime64[ns, UTC]');self.assertEqual(meta['rows'],1)
  self.assertNotIn('password',json.dumps(meta))
if __name__=='__main__':unittest.main()
