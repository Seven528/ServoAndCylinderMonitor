import tempfile
import threading
import unittest
from pathlib import Path
import pandas as pd
from integrations.servo_cylinder_agent.analysis import analyze_dataset,analyze_stream
from integrations.servo_cylinder_agent.local_source import frame_stream

class FullPopulationTests(unittest.TestCase):
 def test_more_than_100000_records_and_cross_batch_baseline(self):
  n=120001
  frame=pd.DataFrame({'MSG_TIMESTAMP':pd.date_range('2026-01-01',periods=n,freq='100ms').astype(str),
                      'STATIONNAME':['A']*n,'ACTVEL':[1]*n,'ACTTORQUE':[0]*(n-1)+[100]})
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'large.csv';frame.to_csv(path,index=False)
   result=analyze_dataset(path)
  self.assertEqual(result['descriptive']['top_level']['rows'],n)
  self.assertEqual(result['processing']['rows_processed'],n)
  self.assertFalse(result['processing']['source_truncated'])
  self.assertEqual(result['diagnostic']['event_record_count'],1,'The final batch must use the whole-population baseline')
  asset=result['descriptive']['assets'][0]
  self.assertEqual(asset['acttorque_median'],0);self.assertEqual(asset['acttorque_p95'],0);self.assertEqual(asset['acttorque_max'],100)
  self.assertEqual(result['processing']['quantiles'],'exact')
 def test_cross_batch_duplicates_and_per_asset_health(self):
  a=pd.DataFrame({'MSG_TIMESTAMP':pd.date_range('2026-01-01',periods=101,freq='s').astype(str),'STATIONNAME':['A']*101,'ACTTORQUE':[0]*100+[100],'ACTVEL':[1]*101})
  b=pd.DataFrame({'MSG_TIMESTAMP':pd.date_range('2026-01-01',periods=100,freq='s').astype(str),'STATIONNAME':['B']*100,'ACTTORQUE':[1000]*100,'ACTVEL':[1]*100})
  result=analyze_stream(iter([a,b,a.head(1)]),'fixture')
  self.assertEqual(result['descriptive']['quality']['duplicate_rows'],1)
  scores={item['asset_key']:item['signal_score'] for item in result['lifecycle']['assets']}
  self.assertGreater(scores['B'],scores['A'])
  self.assertAlmostEqual(result['descriptive']['quality']['timestamp_interval_median_seconds'],1)
 def test_time_chart_covers_entire_window(self):
  frame=pd.DataFrame({'MSG_TIMESTAMP':pd.date_range('2026-01-01',periods=500,freq='h').astype(str),'ACTTORQUE':range(500)})
  result=analyze_stream(iter([frame]),'full-window')
  chart=result['descriptive']['charts'][0]
  self.assertTrue(chart['points'][0]['time'].startswith('2026-01-01'))
  self.assertEqual(chart['points'][-1]['max'],499)
  self.assertLessEqual(len(chart['points']),361)
 def test_cancel_never_returns_a_partial_success(self):
  event=threading.Event();event.set()
  with self.assertRaisesRegex(ValueError,'取消'):analyze_stream(iter([pd.DataFrame({'ACTTORQUE':[1]})]),'cancel',cancel=event)
if __name__=='__main__':unittest.main()
