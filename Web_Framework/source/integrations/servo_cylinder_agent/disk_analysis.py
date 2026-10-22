"""Full-population statistics on a disk-backed SQLite spool, not a sampled prefix."""
from __future__ import annotations
import hashlib
import json
import math
import sqlite3
import tempfile
import time
from functools import lru_cache
from collections import Counter
from pathlib import Path
import numpy as np
import pandas as pd
from src.analysis_agent import LTIME_COLUMNS,ASSET_COLUMNS,parse_ltime_ms

SIGNALS=[('ACTTORQUE','SERVO_TORQUE_OUTLIER','伺服实际转矩'),
         ('POSITION_ERROR','SERVO_POSITION_ERROR_OUTLIER','伺服目标/实际位置差'),
         ('ACTTIME_MS','SERVO_ACTTIME_OUTLIER','伺服动作时间'),
         ('MOVETOTBASTIME_MS','CYLINDER_TO_BASE_TIME_OUTLIER','气缸回程时间'),
         ('MOVETOWORKTIME_MS','CYLINDER_TO_WORK_TIME_OUTLIER','气缸工作行程时间')]
METRICS=['ACTTORQUE','ACTVEL','POSITION_ERROR','ACTTIME_MS','MOVETOTBASTIME_MS','MOVETOWORKTIME_MS','MOVEMENTCOUNTER','ACTPOS','SPEED','ACC','DEC']
STATE_FLAGS=['CLASS1DIAG_ASSERTED','CLASS2DIAG_ASSERTED','CLASS3DIAG_ASSERTED','DRIVE_ENABLED_NOT_READY_FOR_MOVEMENT','AXIS_NOT_REFERENCED']


def _finite(value):
    try:
        result=float(value)
        return result if math.isfinite(result) else None
    except (TypeError,ValueError):return None


def _time(value):
    return pd.Timestamp(value,unit='s',tz='UTC').tz_convert('Asia/Shanghai').isoformat() if value is not None else None


@lru_cache(maxsize=8192)
def _duration(value):
    try:return parse_ltime_ms(value)
    except (ValueError,SyntaxError,TypeError):return np.nan


def _true(series):return series.astype(str).str.lower().isin(['true','1','1.0','yes'])


class DiskAnalysis:
    def __init__(self,progress=None,cancel=None):
        from .analysis import PROJECT_ROOT
        work_root=PROJECT_ROOT/'data'/'output'/'web_agent_runs'
        work_root.mkdir(parents=True,exist_ok=True)
        self.temporary=tempfile.TemporaryDirectory(prefix='.processing-',dir=str(work_root))
        self.database_path=Path(self.temporary.name)/'statistics.sqlite'
        self.db=sqlite3.connect(str(self.database_path))
        self._notify=progress or (lambda _:None)
        self._message='正在准备分析';self._heartbeat=time.monotonic();self.cancel=cancel
        self._intervals_ready=False
        self.db.execute('PRAGMA temp_store=FILE')
        self.db.execute('PRAGMA cache_size=-65536')
        self.db.execute('PRAGMA journal_mode=OFF')
        self.db.execute('PRAGMA synchronous=OFF')
        self.db.set_progress_handler(self._sql_progress,10000)
        self.db.execute('CREATE TABLE samples(id INTEGER PRIMARY KEY,asset TEXT,context TEXT,context_speed TEXT,ts REAL,moving INTEGER,row_hash TEXT,asset_id TEXT,event INTEGER,diagno TEXT,flags TEXT,screened INTEGER,execute INTEGER,accelerating INTEGER,decelerating INTEGER,standstill INTEGER,'+','.join(f'{col} REAL' for col in METRICS)+')')
        self.columns=None;self.available=set();self.missing=Counter();self.rows=0;self.pred_columns={}

    def progress(self,message):
        if self.cancel is not None and self.cancel.is_set():raise ValueError('分析已取消，未返回部分结果。')
        self._message=message;self._heartbeat=time.monotonic();self._notify(message)

    def _sql_progress(self):
        if self.cancel is not None and self.cancel.is_set():return 1
        if time.monotonic()-self._heartbeat>=2:
            self._heartbeat=time.monotonic();self._notify(self._message)
        return 0

    def close(self):
        if self.db is not None:self.db.close()
        self.temporary.cleanup()

    def ensure_intervals(self):
        if self._intervals_ready:return
        self.progress('正在一次性计算并缓存全量采样间隔')
        self.db.execute('CREATE INDEX IF NOT EXISTS samples_asset_time ON samples(asset,ts,id)')
        self.db.execute('CREATE TEMP TABLE sample_intervals AS SELECT asset,ts-LAG(ts) OVER(PARTITION BY asset ORDER BY ts,id) value FROM samples WHERE ts IS NOT NULL')
        self.db.execute('CREATE INDEX interval_value ON sample_intervals(value)')
        self.db.execute('CREATE INDEX interval_asset_value ON sample_intervals(asset,value)')
        self._intervals_ready=True

    def add(self,raw):
        from .analysis import PREDICTOR_COLUMNS
        raw=raw.copy().reset_index(drop=True)
        raw.columns=[str(col).strip().upper() for col in raw.columns]
        if raw.columns.duplicated().any():raise ValueError('字段名大小写归一化后重复。')
        if self.columns is None:
            self.columns=list(raw.columns)
            self.pred_columns={key:next((col for col in choices if col in raw),None) for key,choices in PREDICTOR_COLUMNS.items()}
        elif list(raw.columns)!=self.columns:raise ValueError('读取过程中字段结构发生变化，已停止，未返回部分结果。')
        if raw.empty:return
        self.missing.update({key:int(value) for key,value in raw.isna().sum().items() if value})
        hashes=[hashlib.sha256(json.dumps(row,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest() for row in raw.to_dict('records')]
        frame=raw.copy()
        for col in LTIME_COLUMNS:
            if col in frame:
                frame[col+'_MS']=frame[col].map(lambda value:_duration(tuple(value) if isinstance(value,(list,bytearray)) else value))
        for col in ['ACTPOS','ACTVEL','ACTTORQUE','SPEED','ACC','DEC','TARGETPOS','MOVEMENTCOUNTER']:
            if col in frame:frame[col]=pd.to_numeric(frame[col],errors='coerce')
        if {'TARGETPOS','ACTPOS'}.issubset(frame):frame['POSITION_ERROR']=frame['TARGETPOS']-frame['ACTPOS']
        self.available.update(col for col in METRICS if col in frame)
        if 'MSG_TIMESTAMP' in frame:
            stamps=pd.to_datetime(frame['MSG_TIMESTAMP'],errors='coerce',utc=True)
            timestamps=pd.Series(stamps.array.asi8/1e9,index=frame.index).where(stamps.notna(),np.nan).tolist()
        else:timestamps=[None]*len(frame)
        keys=[col for col in ASSET_COLUMNS if col in frame]
        assets=frame[keys].fillna('NA').astype(str).agg(' / '.join,axis=1).tolist() if keys else ['unknown_asset']*len(frame)
        asset_column=self.pred_columns['asset']
        ids=raw[asset_column].where(raw[asset_column].notna(),None).tolist() if asset_column else [None]*len(frame)
        if asset_column:
            assets=[f'{key} / {asset_column}={value}' if value is not None else key for key,value in zip(assets,ids)]
        event_column=self.pred_columns['event']
        events=raw[event_column].astype(str).str.lower().isin(['true','1','1.0','yes','failed','replaced']).astype(int).tolist() if event_column else [0]*len(frame)
        execute='EXEUTE' if 'EXEUTE' in frame else 'EXECUTE' if 'EXECUTE' in frame else None
        moving=_true(frame[execute]) if execute else pd.Series(True,index=frame.index)
        if 'ACTVEL' in frame:moving|=frame['ACTVEL'].fillna(0).abs().gt(0)
        phase=pd.DataFrame(index=frame.index)
        for col in ['EXEUTE','EXECUTE','ACCELERATING','DECELERATING']:
            if col in frame:phase[col]=frame[col].astype(str).str.lower()
        if 'ACTVEL' in frame:phase['DIRECTION']=np.sign(frame['ACTVEL'].fillna(0)).astype(int)
        contexts=[json.dumps(row,default=str) for row in phase.itertuples(index=False,name=None)] if len(phase.columns) else ['[]']*len(frame)
        speeds=frame['SPEED'].map(lambda x:str(x) if pd.notna(x) else None).tolist() if 'SPEED' in frame else [None]*len(frame)
        flags=[[] for _ in range(len(frame))]
        for col in ['CLASS1DIAG','CLASS2DIAG','CLASS3DIAG']:
            if col in frame:
                for index in np.flatnonzero(_true(frame[col])):flags[index].append(col+'_ASSERTED')
        if {'DRIVEENABLED','DRIVEREADYFORMOVEMENT'}.issubset(frame):
            for index in np.flatnonzero(_true(frame['DRIVEENABLED']) & ~_true(frame['DRIVEREADYFORMOVEMENT'])):flags[index].append('DRIVE_ENABLED_NOT_READY_FOR_MOVEMENT')
        if 'AXISINREFERENCE' in frame:
            for index in np.flatnonzero(~_true(frame['AXISINREFERENCE'])):flags[index].append('AXIS_NOT_REFERENCED')
        metrics=[tuple(_finite(value) for value in row) for row in frame.reindex(columns=METRICS).itertuples(index=False,name=None)]
        moving_values=moving.astype(int).tolist()
        diag=raw['DIAGNO'].astype(str).tolist() if 'DIAGNO' in raw else [None]*len(frame)
        states=[]
        for col in ['EXEUTE' if 'EXEUTE' in raw else 'EXECUTE','ACCELERATING','DECELERATING','STANDSTILL']:
            states.append([int(str(v).lower() in ['true','1','1.0','yes']) if pd.notna(v) else None for v in raw[col]] if col in raw else [None]*len(raw))
        records=[(assets[i],contexts[i],speeds[i],_finite(timestamps[i]),moving_values[i],hashes[i],str(ids[i]) if ids[i] is not None else None,int(events[i]),diag[i],';'.join(flags[i]),int(any(not flag.startswith('CLASS') for flag in flags[i])),*(values[i] for values in states),*metrics[i]) for i in range(len(frame))]
        self.db.executemany('INSERT INTO samples(asset,context,context_speed,ts,moving,row_hash,asset_id,event,diagno,flags,screened,execute,accelerating,decelerating,standstill,'+','.join(METRICS)+') VALUES('+','.join('?' for _ in records[0])+')',records)
        self.db.commit();self.rows+=len(frame)
        self.progress(f'已读取 {self.rows:,} 条，全部写入磁盘统计，不截断数据')

    def quantile(self,expression,where='1',params=(),q=.5,n=None):
        if n is None:n=self.db.execute(f'SELECT COUNT({expression}) FROM samples WHERE {where}',params).fetchone()[0]
        if not n:return None
        rank=(n-1)*q;offset=int(rank)
        values=self.db.execute(f'SELECT {expression} AS value FROM samples WHERE {where} AND {expression} IS NOT NULL ORDER BY value LIMIT 2 OFFSET ?',(*params,offset)).fetchall()
        first=values[0][0];last=values[-1][0]
        return first+(last-first)*(rank-offset)

    def prepare(self):
        self.progress(f'已读取全部 {self.rows:,} 条，正在建立全量统计索引')
        speeds=self.db.execute('SELECT COUNT(*) FROM (SELECT DISTINCT context_speed FROM samples WHERE context_speed IS NOT NULL LIMIT 13)').fetchone()[0]
        if 'SPEED' in self.columns and speeds<=12:self.db.execute("UPDATE samples SET context=context||' / speed='||COALESCE(context_speed,'nan')")
        self.db.execute('CREATE INDEX sample_asset_phase ON samples(asset,context,moving)')
        self.db.execute('CREATE INDEX sample_time ON samples(ts)')
        self.db.execute('CREATE INDEX sample_hash ON samples(row_hash)')
        self.db.execute('CREATE TABLE baselines(asset TEXT,context TEXT,signal TEXT,median REAL,mad REAL,scale REAL,n INTEGER,PRIMARY KEY(asset,context,signal))')
        groups=self.db.execute('SELECT asset,COUNT(*) FROM samples GROUP BY asset')
        for number,(asset,_) in enumerate(groups):
            self._baseline(asset,'*','asset=? AND moving=1',(asset,))
            phases=self.db.execute('SELECT context,COUNT(*) FROM samples WHERE asset=? AND moving=1 GROUP BY context HAVING COUNT(*)>=30',(asset,))
            for context,_ in phases:self._baseline(asset,context,'asset=? AND context=? AND moving=1',(asset,context))
            if number%50==0:self.progress(f'正在按设备和工况计算全量基准：已完成 {number+1:,} 个资产组')
        self.db.commit()
        for signal,flag,_ in SIGNALS:
            if signal not in self.available:continue
            self.progress(f'正在用全量基准筛查 {signal}')
            query=f'''SELECT s.id,s.{signal},COALESCE(l.median,g.median),COALESCE(l.mad,g.mad),COALESCE(l.scale,g.scale),COALESCE(l.n,g.n)
                      FROM samples s LEFT JOIN baselines g ON g.asset=s.asset AND g.context='*' AND g.signal=?
                      LEFT JOIN baselines l ON l.asset=s.asset AND l.context=s.context AND l.signal=? AND l.n>=30
                      WHERE s.moving=1 AND s.{signal} IS NOT NULL'''
            cursor=self.db.execute(query,(signal,signal))
            while True:
                batch=cursor.fetchmany(10000)
                if not batch:break
                updates=[]
                for rid,value,median,mad,scale,n in batch:
                    if median is None:continue
                    hit=value>median+max(5.2*mad,abs(median)*.1) if 'TIME' in signal else bool(n>=30 and scale and abs(value-median)/scale>3.5)
                    if hit:updates.append((flag,flag,rid))
                self.db.executemany("UPDATE samples SET flags=CASE WHEN flags='' THEN ? ELSE flags||';'||? END,screened=1 WHERE id=?",updates)
            self.db.commit()

    def _baseline(self,asset,context,where,params):
        for signal,_,_ in SIGNALS:
            if signal not in self.available:continue
            self.progress(f'正在计算{"资产" if context=="*" else "工况"}全量基准：{asset} · {signal}')
            n=self.db.execute(f'SELECT COUNT({signal}) FROM samples WHERE {where}',params).fetchone()[0]
            if not n:continue
            median=self.quantile(signal,where,params,n=n)
            mad=self.quantile(f'ABS({signal}-({median!r}))',where,params,n=n)
            scale=1.4826*mad
            if scale<=0:
                center=repr(median)
                a,b=self.db.execute(f'SELECT AVG(({signal}-({center}))*({signal}-({center}))),AVG({signal}-({center})) FROM samples WHERE {where}',params).fetchone()
                scale=math.sqrt(max(0,a-b*b))
            self.db.execute('INSERT INTO baselines VALUES(?,?,?,?,?,?,?)',(asset,context,signal,median,mad,scale,n))

    def result(self,dataset,dictionary_path,source,source_bytes,include_charts=True):
        from .analysis import _records,predictive_summary
        self.progress('正在生成覆盖全部记录的统计结果')
        first,last=self.db.execute('SELECT MIN(ts),MAX(ts) FROM samples').fetchone()
        hours=(last-first)/3600 if first is not None else 0
        assets_count=self.db.execute('SELECT COUNT(DISTINCT asset) FROM samples').fetchone()[0]
        duplicate=self.db.execute('SELECT COALESCE(SUM(n-1),0) FROM (SELECT COUNT(*) n FROM samples GROUP BY row_hash HAVING COUNT(*)>1)').fetchone()[0]
        timestamp_missing=self.db.execute('SELECT COUNT(*) FROM samples WHERE ts IS NULL').fetchone()[0]
        interval=self._interval(.5) if first is not None else None
        quality={'rows':self.rows,'columns':len(self.columns),'asset_count':assets_count,'duplicate_rows':duplicate,
                 'timestamp_missing':timestamp_missing,'timestamp_interval_median_seconds':interval,
                 'timestamp_interval_p95_seconds':self._interval(.95) if first is not None else None,
                 'time_window_hours':hours,'missing_by_column':dict(self.missing),'processing':'disk-backed-full-population'}
        asset_rows=[];health=[]
        for asset,count in self.db.execute('SELECT asset,COUNT(*) FROM samples GROUP BY asset ORDER BY asset LIMIT 100'):
            row={'asset_key':asset,'records':count}
            for column in METRICS:
                if column not in self.available:continue
                n,maximum=self.db.execute(f'SELECT COUNT({column}),MAX({column}) FROM samples WHERE asset=?',(asset,)).fetchone()
                row[column.lower()+'_median']=self.quantile(column,'asset=?',(asset,),n=n)
                row[column.lower()+'_p95']=self.quantile(column,'asset=?',(asset,),q=.95,n=n)
                row[column.lower()+'_max']=maximum
            flagged,screened=self.db.execute("SELECT SUM(flags<>''),SUM(screened) FROM samples WHERE asset=?",(asset,)).fetchone()
            diag=sum(self.db.execute('SELECT COUNT(*) FROM samples WHERE asset=? AND instr(flags,?)>0',(asset,flag)).fetchone()[0] for flag in STATE_FLAGS[:3])
            row.update(diagnostic_assertions=diag,screened_records=flagged,screened_record_rate=flagged/count,lifecycle_state='needs_review' if diag else 'watch' if flagged/count>=.01 else 'no_major_signal_in_window')
            asset_rows.append(row)
            rate=screened/count;score=100*(1-rate)
            state='critical' if score<50 else 'degradation' if score<70 else 'watch' if score<90 else 'normal'
            health.append({'asset_key':asset,'signal_score':round(score,1),'state':state,'screened_record_rate':round(rate,5),
                           'movement_counter_max':row.get('movementcounter_max'),'observation_hours':hours,'evidence':['全量异常快照占比']})
        counts=[]
        for flag in STATE_FLAGS+[item[1] for item in SIGNALS]:
            count=self.db.execute('SELECT COUNT(*) FROM samples WHERE instr(flags,?)>0',(flag,)).fetchone()[0]
            if count:counts.append({'flag':flag,'records':count,'share':round(count/self.rows,5)})
        counts.sort(key=lambda item:item['records'],reverse=True)
        event_count=self.db.execute("SELECT COUNT(*) FROM samples WHERE flags<>''").fetchone()[0]
        event_columns=['asset','ts','flags',*METRICS,'diagno']
        events=[]
        for values in self.db.execute('SELECT '+','.join(event_columns)+" FROM samples WHERE flags<>'' ORDER BY ts DESC LIMIT 100"):
            event=dict(zip(event_columns,values));event['asset_key']=event.pop('asset');event['msg_timestamp']=_time(event.pop('ts'));event['anomaly_flags']=event.pop('flags')
            events.append({key.lower():value for key,value in event.items() if value is not None})
        explicit_assets=self.db.execute('SELECT COUNT(DISTINCT asset_id) FROM samples').fetchone()[0]
        event_rows=self.db.execute('SELECT COALESCE(SUM(event),0) FROM samples').fetchone()[0]
        dictionary=[]
        if dictionary_path and Path(dictionary_path).exists():dictionary=_records(pd.read_excel(dictionary_path),200)
        return {'run_id':__import__('uuid').uuid4().hex,'dataset':dataset,'source':{**source,'rows':self.rows,'unlimited':True},'source_bytes':source_bytes,'dictionary':dictionary,
            'engine':'disk-statistical-v2','processing':{'mode':'disk-backed-full-population','rows_processed':self.rows,'source_truncated':False,'quantiles':'exact','assets_displayed':len(asset_rows),'assets_total':assets_count},
            'descriptive':{'assets':asset_rows,'top_level':{'rows':self.rows,'duplicate_rows':duplicate,'asset_groups':assets_count,'first_timestamp':_time(first),'last_timestamp':_time(last),'window_hours':hours,'sample_interval_seconds':interval},'quality':quality,'charts':self._charts(first,last) if include_charts else [],'charts_on_demand':not include_charts},
            'diagnostic':{'event_record_count':event_count,'flag_counts':counts,'events':events,'diagnostic_status_bits':{flag.split('_ASSERTED')[0].lower():next((item['records'] for item in counts if item['flag']==flag),0) for flag in STATE_FLAGS[:3]},
                'notes':['全部记录参与统计；中位数、P95、MAD 在磁盘上精确计算，未对原始数据抽样。','大数据基准按资产、执行阶段、运动方向和低基数速度分组；小工况回退到同一资产全窗基准。','连续快照计数不等于独立故障次数；诊断位含义仍需机型手册确认。','界面仅展示最新 100 条异常明细及前 100 个资产，汇总计数覆盖全部数据。']},
            'lifecycle':{'assets':health,'method':'健康分 = 100 × (1 − 同资产全量数据中含统计/状态异常的快照比例)，不包含未解释的 CLASS 诊断位。','notes':['筛查分不是可靠性概率、真实生命周期阶段或剩余寿命。','基准覆盖全部选定数据，不在每个读取批次内重新拟合。']},
            'predictive':predictive_summary(self.pred_columns,explicit_assets if self.pred_columns['asset'] else assets_count,event_rows,hours)}

    def _interval(self,q):
        self.ensure_intervals()
        n=self.db.execute('SELECT COUNT(*) FROM sample_intervals WHERE value IS NOT NULL').fetchone()[0]
        if not n:return None
        rank=(n-1)*q;offset=int(rank)
        values=self.db.execute('SELECT value FROM sample_intervals WHERE value IS NOT NULL ORDER BY value LIMIT 2 OFFSET ?',(offset,)).fetchall()
        return values[0][0]+(values[-1][0]-values[0][0])*(rank-offset)

    def _charts(self,first,last):
        if first is None:return []
        bucket=max(60,int(math.ceil((last-first)/360/60))*60)
        charts=[]
        labels={'ACTTORQUE':'伺服实际转矩','ACTVEL':'伺服实际速度','POSITION_ERROR':'伺服目标/实际位置差','MOVETOTBASTIME_MS':'气缸回程时间','MOVETOWORKTIME_MS':'气缸工作行程时间'}
        for column,label in labels.items():
            if column not in self.available:continue
            groups=self.db.execute(f'SELECT CAST(ts/{bucket} AS INTEGER)*{bucket},COUNT({column}),MAX({column}) FROM samples WHERE ts IS NOT NULL AND {column} IS NOT NULL GROUP BY 1 ORDER BY 1')
            points=[]
            for start,n,maximum in groups:
                median=self.quantile(column,'ts>=? AND ts<?',(start,start+bucket),n=n)
                points.append({'time':_time(start),'median':median,'max':maximum})
            charts.append({'key':column.lower(),'label':label,'points':points,'bucket_seconds':bucket,'coverage':'full-window'})
        return charts
