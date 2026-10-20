import json
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request,urlopen
from integrations.servo_cylinder_agent.server import AgentServer
from test_agent_models import FakeBridge,RESULT

class AgentHTTPTests(unittest.TestCase):
 def test_catalog_selected_model_and_consent(self):
  with patch('integrations.servo_cylinder_agent.agent_models.CodexBridge',FakeBridge):
   app=AgentServer(0);app.results['run-fixture']=RESULT
   threading.Thread(target=app.serve_forever,daemon=True).start()
   base=f'http://127.0.0.1:{app.server_address[1]}'
   def api(route,body=None):
    request=Request(base+route,data=json.dumps(body).encode() if body is not None else None,headers={'Origin':base,'X-Agent-Token':app.token,'Content-Type':'application/json'})
    with urlopen(request,timeout=5) as response:return json.load(response)
   def wait(job):
    for _ in range(200):
     result=api('/api/jobs/'+job['job_id'])
     if result['status'] in ('succeeded','failed'):
      self.assertEqual(result['status'],'succeeded',result.get('error'));return result['result']
     time.sleep(.01)
    self.fail('job timed out')
   try:
    self.assertEqual(len(api('/api/models')['models']),1)
    catalog=wait(api('/api/models/connect',{}));self.assertTrue(catalog['connected'])
    settings={'model':'test-model','effort':'low','speed':'default'}
    body={'run_id':'run-fixture','question':'解释当前异常','settings':settings}
    with self.assertRaises(HTTPError) as caught:api('/api/ask',body)
    self.assertEqual(caught.exception.code,400)
    self.assertEqual(app.answer_models.bridge.turns,0)
    answer=wait(api('/api/ask',{**body,'consent':True}))
    self.assertEqual(answer['settings'],settings);self.assertEqual(answer['engine'],'codex')
    self.assertNotIn('PRIVATE',app.answer_models.bridge.text)
    with self.assertRaises(HTTPError):api('/api/ask',{**body,'consent':True,'settings':{**settings,'model':'not-allowed'}})
   finally:
    app.shutdown();app.executor.shutdown(wait=True);app.server_close()
if __name__=='__main__':unittest.main()
