"""Exact cycle features in grouped passes rather than per-cycle source scans."""


def compute_features(db,family,asset,threshold,progress):
    args=(family,asset)
    asset_num=db.execute('SELECT asset_num FROM wave_assets WHERE asset=?',(asset,)).fetchone()[0]
    read_args=(family,asset_num)
    source='FROM wave_rows w JOIN samples s ON s.id=w.sample_id WHERE w.family=? AND w.asset=?'
    # Per-cycle means and derivative summaries share one pass over the source.
    progress(f'批量计算周期均值与加减速特征：{family} · {asset}')
    db.execute('DROP TABLE IF EXISTS feature_basic')
    db.execute('''CREATE TEMP TABLE feature_basic AS SELECT w.cid,
        AVG(ABS(s.ACTTORQUE)) torque_mean,AVG(ABS(s.ACTVEL)) velocity_mean,
        AVG(s.SPEED) speed,AVG(s.ACC) acc,AVG(s.DEC) dec,
        AVG(CASE WHEN w.acceleration>0 THEN w.acceleration END) acceleration_mean,
        AVG(CASE WHEN w.acceleration<0 THEN -w.acceleration END) deceleration_mean,
        AVG(s.MOVETOWORKTIME_MS) work_time,AVG(s.MOVETOTBASTIME_MS) base_time '''+source+' GROUP BY w.cid',read_args)
    db.execute('CREATE UNIQUE INDEX feature_basic_cid ON feature_basic(cid)')
    fields=['torque_mean','velocity_mean','speed','acc','dec','acceleration_mean','deceleration_mean'] if family=='servo' else ['work_time','base_time']
    db.execute('UPDATE cycles SET ('+','.join(fields)+')=(SELECT '+','.join(fields)+''' FROM feature_basic f WHERE f.cid=cycles.cid)
        WHERE family=? AND asset=?''',args)
    if family!='servo':return
    progress(f'批量计算转矩幅度精确分位数：{asset}')
    db.execute('DROP TABLE IF EXISTS feature_amplitude')
    query='''CREATE TEMP TABLE feature_amplitude AS WITH v AS (
        SELECT w.cid,ABS(s.ACTTORQUE) v '''+source+''' AND ABS(s.ACTVEL)>? AND s.ACTTORQUE IS NOT NULL),
        r AS (SELECT cid,v,ROW_NUMBER() OVER(PARTITION BY cid ORDER BY v) rn,
                   COUNT(*) OVER(PARTITION BY cid) n FROM v)
        SELECT cid,'''
    expressions=[]
    for q in [.05,.95]:
        pos=f'((n-1)*{q})'
        low=f'MAX(CASE WHEN rn=CAST({pos} AS INTEGER)+1 THEN v END)'
        high=f'MAX(CASE WHEN rn=CAST({pos} AS INTEGER)+2 THEN v END)'
        expressions.append(f'({low}+(COALESCE({high},{low})-{low})*({pos}-CAST({pos} AS INTEGER)))')
    db.execute(query+expressions[1]+'-'+expressions[0]+' amplitude FROM r GROUP BY cid',(*read_args,threshold))
    db.execute('CREATE UNIQUE INDEX feature_amplitude_cid ON feature_amplitude(cid)')
    db.execute('UPDATE cycles SET torque_amplitude=(SELECT amplitude FROM feature_amplitude f WHERE f.cid=cycles.cid) WHERE family=? AND asset=?',args)
    progress(f'批量计算稳定运动段速度不稳定度：{asset}')
    db.execute('DROP TABLE IF EXISTS feature_velocity')
    db.execute('''CREATE TEMP TABLE feature_velocity AS WITH g AS (
        SELECT w.cid,COUNT(s.ACTVEL) n,AVG(ABS(s.ACTVEL)) m,AVG(s.ACTVEL*s.ACTVEL) sq '''+source+'''
        AND ABS(s.ACTVEL)>? AND s.accelerating=0 AND s.decelerating=0
        GROUP BY w.cid,s.SPEED,CASE WHEN s.ACTVEL>=0 THEN 1 ELSE -1 END HAVING COUNT(s.ACTVEL)>=3)
        SELECT cid,SUM(n) n,SUM(n*m)/SUM(n) mean_speed,SUM(n*MAX(0,sq-m*m))/SUM(n) variance
        FROM g GROUP BY cid''',(*read_args,threshold))
    # sqrt is not guaranteed in every bundled SQLite; only one scalar per cycle
    # crosses into Python, never the original rows or a per-cycle SELECT.
    import math
    updates=((math.sqrt(max(0,var))/mean if mean>1e-8 else None,family,asset,cid)
             for cid,n,mean,var in db.execute('SELECT cid,n,mean_speed,variance FROM feature_velocity'))
    db.executemany('UPDATE cycles SET velocity_instability=? WHERE family=? AND asset=? AND cid=?',updates)
