import json
import unittest
from unittest.mock import patch
from integrations.servo_cylinder_agent.agent_models import AnswerModels,summary_for_model
from integrations.servo_cylinder_agent.codex_runtime import _configured_mcp_names

RESULT={
 'dataset':'PRIVATE-file.csv',
 'descriptive':{'top_level':{'rows':10,'asset_groups':1,'window_hours':.5},'assets':[{'asset_key':'PRIVATE-axis'}]},
 'diagnostic':{'flag_counts':[{'flag':'TORQUE','records':2,'share':.2}],'notes':['筛查，不是故障'],'events':[{'raw':'PRIVATE-payload'}]},
 'lifecycle':{'assets':[{'asset_key':'PRIVATE-axis','state':'watch','signal_score':80}],'notes':['状态需要校准']},
 'predictive':{'status':'not_ready','message':'没有寿命预测','reasons':['缺少事件'],'candidate_models':[]},
 'dictionary':[{'value':'PRIVATE-parameter'}]}
class FakeBridge:
 def __init__(self):
  self.models=[{'id':'test-model','name':'Test model','efforts':['low','high'],'speeds':[{'id':'default','name':'标准'}]}];self.released=[];self.closed=False;self.turns=0
 def validate(self,settings):
  if settings!={'model':'test-model','effort':'low','speed':'default'}:raise ValueError('unsupported settings')
  return dict(settings)
 def start_thread(self,settings,instructions,tools):self.tools=tools;return 'owned',dict(settings)
 def run_turn(self,session,text,settings,handler,emit):
  self.turns+=1;self.text=text;return {'status':'completed','text':'这是模型回答','settings':settings}
 def release(self,thread):self.released.append(thread)
 def close(self):self.closed=True
class ModelTests(unittest.TestCase):
 def test_summary_excludes_identifiers_rows_and_dictionary(self):
  summary=summary_for_model(RESULT)
  self.assertNotIn('PRIVATE',summary);self.assertIn('TORQUE',summary)
 def test_local_catalog_before_connect(self):
  service=AnswerModels();self.assertFalse(service.catalog()['connected']);self.assertEqual(len(service.catalog()['models']),1)
 def test_selected_model_used_only_after_consent(self):
  with patch('integrations.servo_cylinder_agent.agent_models.CodexBridge',FakeBridge):
   service=AnswerModels();service.connect();bridge=service.bridge
   settings={'model':'test-model','effort':'low','speed':'default'}
   with self.assertRaises(ValueError):service.answer(RESULT,'问题',settings,False)
   self.assertEqual(bridge.turns,0)
   answer=service.answer(RESULT,'请解释统计',settings,True)
   self.assertEqual(answer['settings'],settings);self.assertEqual(bridge.turns,1);self.assertEqual(bridge.tools,[])
   self.assertNotIn('PRIVATE',bridge.text);self.assertEqual(bridge.released,['owned'])
   with self.assertRaises(ValueError):service.validate({**settings,'model':'other-model'})
   service.close();self.assertTrue(bridge.closed)
 def test_model_failure_never_returns_local_fallback(self):
  service=AnswerModels();service.bridge=FakeBridge()
  from integrations.servo_cylinder_agent.codex_runtime import BridgeError
  with patch.object(service.bridge,'run_turn',side_effect=BridgeError('provider error')):
   with self.assertRaisesRegex(ValueError,'不会自动切换模型'):service.answer(RESULT,'question',{'model':'test-model','effort':'low','speed':'default'},True)
  self.assertEqual(service.bridge.released,['owned'])
 def test_python39_mcp_config_isolation(self):
  with patch('integrations.servo_cylinder_agent.codex_runtime.tomllib',None):
   self.assertEqual(_configured_mcp_names('[mcp_servers.alpha]\ncommand="x"\n[mcp_servers."beta-server".env]\nK="v"'),['alpha','beta-server'])
   with self.assertRaises(Exception):_configured_mcp_names('mcp_servers = {evil = {enabled = true}}')
if __name__=='__main__':unittest.main()
