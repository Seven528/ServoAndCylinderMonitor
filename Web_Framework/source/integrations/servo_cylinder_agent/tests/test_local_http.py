import io
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import pandas as pd
from integrations.servo_cylinder_agent.server import AgentServer

class LocalHTTPTests(unittest.TestCase):
 def test_upload_path_sheet_and_authorization(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder)
   frame=pd.DataFrame({'MSG_TIMESTAMP':['2026-10-20T00:00:00Z']*30,'ACTTORQUE':range(30),'STATIONNAME':['ST401']*30})
   csv=root/'external.csv';frame.to_csv(csv,index=False)
   output=root/'results'
   with patch('integrations.servo_cylinder_agent.server.OUTPUT_ROOT',output):
    app=AgentServer(0);threading.Thread(target=app.serve_forever,daemon=True).start()
    base=f'http://127.0.0.1:{app.server_address[1]}'
    def api(route,body=None,raw=None,authorized=True):
     headers={'Origin':base,'Content-Type':'application/octet-stream' if raw is not None else 'application/json'}
     if authorized:headers['X-Agent-Token']=app.token
     data=raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
     with urlopen(Request(base+route,data=data,headers=headers),timeout=10) as response:return json.load(response)
    def analyze(body):
     job=api('/api/analyze',body)
     for _ in range(300):
      result=api('/api/jobs/'+job['job_id'])
      if result['status'] in ('failed','succeeded'):
       self.assertEqual(result['status'],'succeeded',result.get('error'));return result['result']
      time.sleep(.02)
     self.fail('analysis timed out')
    try:
     selected=api('/api/local/register',{'path':str(csv)})
     result=analyze({'local_file_id':selected['file_id']})
     self.assertEqual(result['descriptive']['top_level']['rows'],30)
     self.assertTrue(csv.exists(),'Original files must be preserved')
     selected=api('/api/local/upload?filename=uploaded.csv',raw=csv.read_bytes())
     self.assertEqual(analyze({'local_file_id':selected['file_id']})['source']['kind'],'csv')
     buffer=io.BytesIO()
     with pd.ExcelWriter(buffer,engine='openpyxl') as writer:
      frame.to_excel(writer,sheet_name='First',index=False)
      frame.head(10).to_excel(writer,sheet_name='Second',index=False)
     selected=api('/api/local/upload?filename=uploaded.xlsx',raw=buffer.getvalue())
     self.assertEqual(selected['sheets'],['First','Second'])
     result=analyze({'local_file_id':selected['file_id'],'sheet':'Second'})
     self.assertEqual(result['descriptive']['top_level']['rows'],10)
     self.assertEqual(result['source']['sheet'],'Second')
     with self.assertRaises(HTTPError) as caught:api('/api/local/upload?filename=a.csv',raw=b'a\n1\n',authorized=False)
     self.assertEqual(caught.exception.code,403)
     with self.assertRaises(HTTPError) as caught:api('/api/local/upload?filename=a.txt',raw=b'data')
     self.assertEqual(caught.exception.code,400)
    finally:
     app.shutdown();app.executor.shutdown(wait=True);app.server_close()

if __name__=='__main__':unittest.main()
