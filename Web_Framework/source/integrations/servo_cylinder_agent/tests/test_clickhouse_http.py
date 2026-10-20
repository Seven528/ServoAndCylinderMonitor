"""Local HTTP integration: browser API -> warehouse mock -> shared analysis pipeline."""
import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

from integrations.servo_cylinder_agent.server import AgentServer

class Warehouse(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  sql=self.rfile.read(int(self.headers['Content-Length'])).decode()
  if sql.startswith('SELECT 1 '):rows=[{'ok':1}]
  elif sql.startswith('DESCRIBE '):rows=[{'name':'MSG_TIMESTAMP','type':'DateTime64(3)'},{'name':'STATIONNAME','type':'String'},{'name':'ACTTORQUE','type':'Float64'}]
  else:
   start=int(parse_qs(urlsplit(self.path).query)['param_start'][0])
   rows=[{'MSG_TIMESTAMP':'2026-10-20 08:00:00','__agent_timestamp_ms':start+i*1000,'STATIONNAME':'ST401','ACTTORQUE':float(i%5),'ACTVEL':2.0} for i in range(50)]
  data=('\n'.join(json.dumps(row) for row in rows)+'\n').encode()
  self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)

class HTTPIntegration(unittest.TestCase):
 def test_connection_schema_query_analysis_and_csv_regression(self):
  with tempfile.TemporaryDirectory() as folder, patch('integrations.servo_cylinder_agent.server.OUTPUT_ROOT',Path(folder)):
   warehouse=ThreadingHTTPServer(('127.0.0.1',0),Warehouse);app=AgentServer(0)
   for server in (warehouse,app):threading.Thread(target=server.serve_forever,daemon=True).start()
   base=f'http://127.0.0.1:{app.server_address[1]}'
   def api(path,body=None):
    headers={'X-Agent-Token':app.token,'Origin':base,'Content-Type':'application/json'}
    request=Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
    with urlopen(request,timeout=10) as response:return json.load(response)
   def wait(job):
    for _ in range(400):
     status=api('/api/jobs/'+job['job_id'])
     if status['status'] in ('succeeded','failed'):
      self.assertEqual(status['status'],'succeeded',status.get('error'));return status['result']
     time.sleep(.02)
    self.fail('job timed out')
   try:
    checked=wait(api('/api/clickhouse/connect',{'endpoint':f'http://127.0.0.1:{warehouse.server_address[1]}','database':'mock','table':'runtime','username':'dummy','password':'fixture-secret'}))
    self.assertEqual(len(checked['columns']),3)
    self.assertNotIn('fixture-secret',json.dumps(checked))
    result=wait(api('/api/clickhouse/analyze',{'connection_id':checked['connection_id'],'options':{'time_column':'MSG_TIMESTAMP','start':'2026-10-20T08:00','end':'2026-10-20T09:00','max_rows':100}}))
    self.assertEqual(result['descriptive']['top_level']['rows'],50)
    self.assertEqual(result['source']['kind'],'clickhouse')
    self.assertTrue(result['descriptive']['top_level']['first_timestamp'].startswith('2026-10-20T08:00'))
    self.assertNotIn('fixture-secret',json.dumps(result))
    for key in ('descriptive','diagnostic','lifecycle','predictive'):self.assertIn(key,result)
    dataset=api('/api/datasets')['datasets'][0]['id']
    csv=wait(api('/api/analyze',{'dataset':dataset}))
    self.assertEqual(csv['descriptive']['top_level']['rows'],10000)
    self.assertEqual(csv['source']['kind'],'csv')
   finally:
    app.shutdown();app.executor.shutdown(wait=True);app.server_close();warehouse.shutdown();warehouse.server_close()
if __name__=='__main__':unittest.main()
