import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from integrations.servo_cylinder_agent.local_source import inspect_file, load_frame, validate_file
from integrations.servo_cylinder_agent.clickhouse_source import ClickHouseError
from src.logger import Logger
from src.web_logging import get_logger, log_failure

class LocalSourceTests(unittest.TestCase):
 def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
 def tearDown(self):self.temp.cleanup()
 def test_csv_and_excel_sheet_selection(self):
  table=pd.DataFrame({'MSG_TIMESTAMP':['2026-10-20T00:00:00Z'],'ACTTORQUE':[5.0]})
  csv=self.root/'运行.csv';table.to_csv(csv,index=False)
  frame,source=load_frame(csv);self.assertEqual(len(frame),1);self.assertEqual(source['kind'],'csv')
  book=self.root/'运行.xlsx'
  with pd.ExcelWriter(book,engine='openpyxl') as writer:
   table.to_excel(writer,sheet_name='站点A',index=False)
   pd.concat([table,table]).to_excel(writer,sheet_name='站点B',index=False)
  self.assertEqual(inspect_file(book)['sheets'],['站点A','站点B'])
  frame,source=load_frame(book,'站点B');self.assertEqual(len(frame),2);self.assertEqual(source['sheet'],'站点B')
  with self.assertRaises(ValueError):load_frame(book,'不存在')
 def test_gb18030_csv(self):
  path=self.root/'gb.csv';pd.DataFrame({'STATIONNAME':['工位一']}).to_csv(path,index=False,encoding='gb18030')
  frame,_=load_frame(path);self.assertEqual(frame.iloc[0,0],'工位一')
 def test_reject_relative_missing_or_unsupported_files(self):
  for path in ('relative.csv',self.root/'missing.csv',self.root/'data.json'):
   with self.assertRaises(ValueError):validate_file(path)
 def test_no_silent_row_truncation(self):
  path=self.root/'large.csv';pd.DataFrame({'ACTTORQUE':range(4)}).to_csv(path,index=False)
  with patch('integrations.servo_cylinder_agent.local_source.MAX_LOCAL_ROWS',3):
   with self.assertRaisesRegex(ValueError,'不会截断'):load_frame(path)
 def test_error_classification_no_remote_sql_or_password(self):
  text=b'Code: 158. DB::Exception: sensitive-test-secret SELECT xxx (TOO_MANY_ROWS)'
  message=str(ClickHouseError(500,text))
  self.assertIn('Code 158',message);self.assertIn('扫描行数',message);self.assertNotIn('sensitive-test-secret',message)
  self.assertIn('内存',str(ClickHouseError(500,b'Code: 241')))
 def test_existing_logger_and_redacted_traceback(self):
  self.assertIsInstance(get_logger(),Logger)
  fake=Logger(self.root)
  try:raise RuntimeError('password=secret-token secret-token')
  except RuntimeError as error:
   with patch('src.web_logging.get_logger',return_value=fake):log_failure('web.test',error,'TEST',secrets=['secret-token'])
  log=Path(fake.log_file).read_text()
  self.assertIn('TEST',log);self.assertIn('Traceback',log);self.assertNotIn('password=secret-token',log)
  # The traceback includes source code, so use a generated secret absent from source.
  secret='generated'+'-credential-9381'
  try:raise ValueError(secret)
  except ValueError as error:
   with patch('src.web_logging.get_logger',return_value=fake):log_failure('web.test',error,'TEST2',secrets=[secret])
  self.assertNotIn(secret,Path(fake.log_file).read_text())

if __name__=='__main__':unittest.main()
