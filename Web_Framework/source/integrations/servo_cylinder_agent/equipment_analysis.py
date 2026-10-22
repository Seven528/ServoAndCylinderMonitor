"""Per-equipment cycle extraction and zoom queries over retained local evidence."""
from __future__ import annotations
import json
import math
import sqlite3
from contextlib import contextmanager
from pathlib import Path
import numpy as np
from .wave_models import model_cycles

CYCLE_FIELDS=['torque_amplitude','velocity_instability','work_time','base_time','duration','torque_mean','velocity_mean','speed','acc','dec','acceleration_mean','deceleration_mean']
SERVO={'ACTTORQUE':'实际转矩','ACTVEL':'实际速度','POSITION_ERROR':'目标/实际位置差','ACTPOS':'实际位置','SPEED':'速度设定','ACC':'加速度设定','DEC':'减速度设定'}
CYLINDER={'MOVETOTBASTIME_MS':'回程时间 ms','MOVETOWORKTIME_MS':'工作行程时间 ms','MOVEMENTCOUNTER':'累计动作计数'}


def prepare_equipment(engine):
    try:
        import sklearn
        import scipy
    except ImportError:
        raise ValueError('周期模型需要 scikit-learn 和 scipy，请在运行网页的 Python 解释器中安装本集成的 requirements.txt。') from None
    db=engine.db;progress=engine.progress
    db.execute('CREATE TABLE wave_assets(asset TEXT PRIMARY KEY,asset_num INTEGER UNIQUE)')
    db.execute('INSERT INTO wave_assets SELECT asset,ROW_NUMBER() OVER(ORDER BY asset) FROM (SELECT DISTINCT asset FROM samples WHERE ts IS NOT NULL)')
    db.execute('CREATE TABLE wave_rows(family TEXT,asset INTEGER,sample_id INTEGER,cid INTEGER,acceleration REAL,PRIMARY KEY(family,sample_id))')
    db.execute('CREATE TABLE cycles(family TEXT,asset TEXT,cid INTEGER,start REAL,end REAL,n INTEGER,complete INTEGER,boundary TEXT,'+','.join(field+' REAL' for field in CYCLE_FIELDS)+',if_score REAL,if_anomaly INTEGER,torque_di REAL,velocity_di REAL,mean_di REAL,stage INTEGER,PRIMARY KEY(family,asset,cid))')
    db.execute('CREATE TABLE equipment_models(family TEXT,asset TEXT,info TEXT,PRIMARY KEY(family,asset))')
    db.execute('CREATE INDEX IF NOT EXISTS samples_asset_time ON samples(asset,ts,id)')
    for family,fields in [('servo',SERVO),('cylinder',CYLINDER)]:
        present=[field for field in fields if field in engine.available]
        if not present:continue
        condition=' OR '.join(field+' IS NOT NULL' for field in present)
        for (asset,) in db.execute('SELECT DISTINCT asset FROM samples WHERE ts IS NOT NULL AND ('+condition+')'):
            progress(f'正在识别 {family} 周期：{asset}')
            asset_num=db.execute('SELECT asset_num FROM wave_assets WHERE asset=?',(asset,)).fetchone()[0]
            db.execute('CREATE TEMP TABLE IF NOT EXISTS equipment_parameters(asset TEXT PRIMARY KEY,gap_limit REAL,execute_n INTEGER,still_n INTEGER,vmax REAL)')
            cached=db.execute('SELECT gap_limit,execute_n,still_n,vmax FROM equipment_parameters WHERE asset=?',(asset,)).fetchone()
            if cached is None:
                engine.ensure_intervals()
                n=db.execute('SELECT COUNT(*) FROM sample_intervals WHERE asset=? AND value>0',(asset,)).fetchone()[0]
                interval=db.execute('SELECT value FROM sample_intervals WHERE asset=? AND value>0 ORDER BY value LIMIT 1 OFFSET ?',(asset,n//2)).fetchone() if n else None
                gap_limit=max(30,10*(interval[0] if interval else 1))
                execute_n,still_n=db.execute('SELECT COUNT(DISTINCT execute),COUNT(DISTINCT standstill) FROM samples WHERE asset=?',(asset,)).fetchone()
                vmax=engine.quantile('ABS(ACTVEL)','asset=?',(asset,),q=.95) if 'ACTVEL' in engine.available else None
                cached=(gap_limit,execute_n,still_n,vmax)
                db.execute('INSERT INTO equipment_parameters VALUES(?,?,?,?,?)',(asset,*cached))
            gap_limit,execute_n,still_n,vmax=cached
            threshold=max(1e-8,(vmax or 0)*.02)
            boundary='EXEUTE/EXECUTE 上升沿' if execute_n==2 else 'STANDSTILL 下降沿' if still_n==2 else '|ACTVEL| 运动阈值上升沿' if vmax and vmax>0 else '未识别周期'
            if family=='cylinder':
                distinct=db.execute('SELECT COUNT(*) FROM (SELECT DISTINCT MOVEMENTCOUNTER FROM samples WHERE asset=? AND MOVEMENTCOUNTER IS NOT NULL LIMIT 2)',(asset,)).fetchone()[0]
                boundary='MOVEMENTCOUNTER 递增（周期代理）' if distinct==2 else '未识别周期'
            cursor=db.execute('SELECT id,ts,execute,standstill,ACTVEL,MOVEMENTCOUNTER FROM samples WHERE asset=? AND ts IS NOT NULL AND ('+condition+') ORDER BY ts,id',(asset,))
            cid=0;seen_start=False;previous=None;start=None;last=None;length=0;buffer=[]
            for rid,ts,execute,still,vel,counter in cursor:
                active=bool(execute) if execute_n==2 else still==0 if still_n==2 else abs(vel or 0)>threshold
                reset=previous is not None and ts-previous[0]>gap_limit
                counter_reset=family=='cylinder' and previous is not None and counter is not None and previous[3] is not None and counter<previous[3]
                rise=previous is not None and ((counter is not None and previous[3] is not None and counter>previous[3]) if family=='cylinder' else active and not previous[1])
                if start is not None and (rise or reset or counter_reset):
                    complete=seen_start and rise and not reset and not counter_reset
                    if family=='cylinder' and counter is not None and previous[3] is not None and counter-previous[3]!=1:complete=False
                    db.execute('INSERT INTO cycles(family,asset,cid,start,end,n,complete,boundary,duration) VALUES(?,?,?,?,?,?,?,?,?)',(family,asset,cid,start,ts if complete else last,length,int(complete),boundary,(ts if complete else last)-start))
                    cid+=1;length=0;start=None;seen_start=rise and not reset and not counter_reset
                if start is None:start=ts
                acceleration=(abs(vel)-abs(previous[2]))/(ts-previous[0]) if previous and vel is not None and previous[2] is not None and ts>previous[0] and not reset and not rise else None
                buffer.append((family,asset_num,rid,cid,acceleration));length+=1;last=ts
                if len(buffer)>=10000:
                    db.executemany('INSERT INTO wave_rows VALUES(?,?,?,?,?)',buffer);buffer=[];progress(f'周期读取：{asset} · 已识别 {cid:,} 个边界')
                previous=(ts,active,vel,counter)
            db.executemany('INSERT INTO wave_rows VALUES(?,?,?,?,?)',buffer)
            if start is not None:db.execute('INSERT INTO cycles(family,asset,cid,start,end,n,complete,boundary,duration) VALUES(?,?,?,?,?,?,?,?,?)',(family,asset,cid,start,last,length,0,boundary,last-start))
            db.commit()
    db.execute('CREATE INDEX wave_cycle ON wave_rows(family,asset,cid,sample_id)')
    for family,asset in db.execute('SELECT family,asset FROM cycles GROUP BY family,asset'):
        progress(f'正在计算周期波形特征：{family} · {asset}')
        from .cycle_features import compute_features
        vmax=db.execute('SELECT vmax FROM equipment_parameters WHERE asset=?',(asset,)).fetchone()[0]
        compute_features(db,family,asset,max(1e-8,(vmax or 0)*.02),progress)
        info=model_cycles(db,family,asset,progress)
        info['boundary']=db.execute('SELECT boundary FROM cycles WHERE family=? AND asset=? LIMIT 1',(family,asset)).fetchone()[0]
        db.execute('INSERT INTO equipment_models VALUES(?,?,?)',(family,asset,json.dumps(info,ensure_ascii=False,allow_nan=False)))
        db.commit()
    return {'version':1,'servo':catalog(db,'servo'),'cylinder':catalog(db,'cylinder'),'method':'按资产分别分周期；不完整边界周期不训练；IsolationForest 和 HMM 训练使用明确披露的有界样本，全部有效周期推断。'}


def catalog(db,family,query=''):
    total=db.execute('SELECT COUNT(*) FROM equipment_models WHERE family=?',(family,)).fetchone()[0]
    rows=db.execute("SELECT asset,info FROM equipment_models WHERE family=? AND instr(asset,?)>0 ORDER BY asset LIMIT 100",(family,query)).fetchall()
    assets=[]
    for asset,info in rows:
        start,end,n,complete=db.execute('SELECT MIN(start),MAX(end),SUM(n),SUM(complete) FROM cycles WHERE family=? AND asset=?',(family,asset)).fetchone()
        assets.append({'asset':asset,'start':start,'end':end,'records':n,'complete_cycles':complete,**json.loads(info)})
    return {'assets':assets,'total_assets':total,'matching_preview':len(assets)}


def evidence_path(run_id):
    from .analysis import PROJECT_ROOT
    if len(run_id)!=32 or any(c not in '0123456789abcdef' for c in run_id):raise ValueError('分析标识无效。')
    return PROJECT_ROOT/'data'/'output'/'web_agent_runs'/(run_id+'.wave.sqlite')


def persist(engine,result):
    path=evidence_path(result['run_id']);path.parent.mkdir(parents=True,exist_ok=True)
    engine.db.commit()
    # The working database is on the same volume as the result directory.
    # Closing and renaming preserves evidence without copying the entire DB.
    engine.db.close();engine.db=None
    Path(engine.database_path).replace(path)
    return path


@contextmanager
def open_evidence(run_id):
    path=evidence_path(run_id)
    if not path.is_file():raise ValueError('明细文件不存在，请重新运行分析。')
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
    db.execute('PRAGMA temp_store=FILE');db.execute('PRAGMA cache_size=-32768')
    try:yield db
    finally:db.close()


def query_view(run_id,options):
    family=options.get('family','servo');asset=options.get('asset','')
    if family not in ('servo','cylinder'):raise ValueError('设备类型无效。')
    with open_evidence(run_id) as db:
        info=db.execute('SELECT info FROM equipment_models WHERE family=? AND asset=?',(family,asset)).fetchone()
        if not info:raise ValueError('资产不存在。')
        full=db.execute('SELECT MIN(start),MAX(end) FROM cycles WHERE family=? AND asset=?',(family,asset)).fetchone()
        start=float(options.get('start',full[0]));end=float(options.get('end',full[1]))
        if not math.isfinite(start) or not math.isfinite(end) or end<start:raise ValueError('请选择有效时间范围。')
        start=max(start,full[0]);end=min(end,full[1])
        if end<start:raise ValueError('时间范围不在数据窗内。')
        bins=500;width=max(.000001,(end-start)/bins)
        metrics=SERVO if family=='servo' else CYLINDER
        if options.get('view')=='diagnostic':metrics={}
        elif options.get('view')=='lifecycle':metrics={key:value for key,value in metrics.items() if key in ('ACTTORQUE','ACTVEL','MOVETOWORKTIME_MS','MOVETOTBASTIME_MS')}
        from .chart_queries import read_charts
        charts=read_charts(db,family,asset,start,end,metrics,width)
        count=db.execute('SELECT COUNT(*) FROM cycles WHERE family=? AND asset=? AND end>=? AND start<=?',(family,asset,start,end)).fetchone()[0]
        bands=[]
        if count<=1000:
            bands=[dict(zip(['cid','start','end','complete','stage','anomaly'],row)) for row in db.execute('SELECT cid,start,end,complete,stage,if_anomaly FROM cycles WHERE family=? AND asset=? AND end>=? AND start<=? ORDER BY cid',(family,asset,start,end))]
        # Model plots are aggregated from complete cycles only. State 2 means
        # at least one model high-risk cycle in a coarse bin, not an entire bin.
        features=['if_score','torque_amplitude','velocity_instability','torque_di','velocity_di','mean_di','work_time','base_time']
        rows=db.execute('SELECT MIN(499,CAST((start-?)/? AS INTEGER)) b,AVG(start),'+','.join(('MAX' if f=='if_score' else 'AVG')+'('+f+')' for f in features)+',MAX(stage),SUM(if_anomaly),COUNT(*),SUM(stage=0),SUM(stage=1),SUM(stage=2),MIN(cid),MAX(cid) FROM cycles WHERE family=? AND asset=? AND complete=1 AND start>=? AND start<=? GROUP BY b ORDER BY b',(start,width,family,asset,start,end)).fetchall()
        models=[dict(zip(['bucket','time',*features,'stage','anomalies','cycles','stage0','stage1','stage2','first_cid','last_cid'],row)) for row in rows]
        scope=db.execute('SELECT COUNT(*),SUM(complete),SUM(CASE WHEN complete=1 THEN if_anomaly END),AVG(CASE WHEN complete=1 THEN mean_di END),SUM(CASE WHEN complete=1 THEN stage=2 END),COUNT(CASE WHEN complete=1 THEN stage END),COUNT(CASE WHEN complete=1 THEN mean_di END) FROM cycles WHERE family=? AND asset=? AND start>=? AND start<=?',(family,asset,start,end)).fetchone()
        return {'family':family,'asset':asset,'start':start,'end':end,'full_start':full[0],'full_end':full[1],'charts':charts,'bands':bands,'cycle_count':count,'dense_cycles':count>1000,'models':models,'model_info':json.loads(info[0]),'scope':dict(zip(['cycles','complete_cycles','if_anomalies','mean_degradation','high_risk_cycles','hmm_cycles','degradation_cycles'],scope)),'resolution_seconds':width,'statistics':'所选区间全部记录参与精确分位数统计；图点为时间桶，缩放后重新聚合。模型固定于本次完整分析，缩放不重新拟合。'}
