"""Separate process semantics: servo motion groups and cylinder event evidence."""
from .product_cycles import motion_rows, settings


def build(db,family,asset,asset_num,threshold,gap_limit,progress):
    if family=='cylinder':
        db.execute('CREATE TABLE IF NOT EXISTS cylinder_events(asset TEXT,sample_id INTEGER,ts REAL,delta REAL,work_ms REAL,base_ms REAL,quality TEXT)')
        rows=[];mapping=[];prev=None;first=None;last=None;n=0;interrupted=False
        for rid,ts,counter,work,base in db.execute('SELECT id,ts,MOVEMENTCOUNTER,MOVETOWORKTIME_MS,MOVETOTBASTIME_MS FROM samples WHERE asset=? AND ts IS NOT NULL ORDER BY ts,id',(asset,)):
            if first is None:first=ts
            if prev is not None and ts-prev[0]>gap_limit:interrupted=True
            if prev is not None and counter is not None and prev[1] is not None and counter!=prev[1]:
                delta=counter-prev[1]
                quality='单次递增事件（完成语义待PLC确认）' if delta==1 and not interrupted and ts-prev[0]<=gap_limit else '跳变/复位/断档，不代表单次完整动作'
                rows.append((asset,rid,ts,delta,work,base,quality));interrupted=False
            mapping.append((family,asset_num,rid,0,None));n+=1;last=ts;prev=(ts,counter)
            if len(mapping)>=10000:
                db.executemany('INSERT INTO wave_rows VALUES(?,?,?,?,?)',mapping);mapping=[]
                db.executemany('INSERT INTO cylinder_events VALUES(?,?,?,?,?,?,?)',rows);rows=[];progress(f'气缸事件读取：{asset} · {n:,} 条')
        db.executemany('INSERT INTO wave_rows VALUES(?,?,?,?,?)',mapping)
        db.executemany('INSERT INTO cylinder_events VALUES(?,?,?,?,?,?,?)',rows)
        db.execute('CREATE INDEX IF NOT EXISTS cylinder_event_time ON cylinder_events(asset,ts,sample_id)')
        boundary='气缸独立动作事件；缺少工作位/基本位到位信号，无法重建含工作位停留的有效周期'
        if first is not None:db.execute('INSERT INTO cycles(family,asset,cid,start,end,n,complete,boundary,duration) VALUES(?,?,?,?,?,?,?,?,?)',(family,asset,0,first,last,n,0,boundary,None))
        return {'kind':'events_only','source':'MOVEMENTCOUNTER','idle_seconds':None,'velocity_threshold':None,'definition':boundary,'nominal_work_dwell_seconds':1,'note':'1秒仅为专家参考，不填入实测结果；去/回行程时间不等于工作位停留时间。'}

    source,idle,method=settings(db,asset,threshold,gap_limit,progress)
    # Terminal rest is deliberately more conservative than a command pause.
    if source=='MOVEMENTCOUNTER':source='unavailable'
    terminal=max(60.,idle)
    lo,hi=db.execute('SELECT MIN(ACTPOS),MAX(ACTPOS) FROM samples WHERE asset=?',(asset,)).fetchone()
    tolerance=max(1e-6,(hi-lo)*.01) if lo is not None and hi is not None else None
    boundary=f'伺服候选有效周期：运行/保持/等待/返回；返回后静止≥{terminal:.3f}秒确认结束，尾部停留排除；600秒仅作参考'
    cid=0;start=None;seen=False;prev=None;quiet=None;home=None;away=False;lastpos=None;buffer=[];count=0
    def flush():
        if buffer:db.executemany('INSERT INTO wave_rows VALUES(?,?,?,?,?)',buffer);buffer.clear()
    def close(end,complete,trim=False):
        nonlocal cid,start,seen,home,away,quiet
        flush()
        if trim:
            db.execute('UPDATE wave_rows SET cid=-1 WHERE family=? AND asset=? AND cid=? AND sample_id IN (SELECT id FROM samples WHERE asset=? AND ts>=?)',(family,asset_num,cid,asset,end))
        n=db.execute('SELECT COUNT(*) FROM wave_rows WHERE family=? AND asset=? AND cid=?',(family,asset_num,cid)).fetchone()[0]
        db.execute('INSERT INTO cycles(family,asset,cid,start,end,n,complete,boundary,duration) VALUES(?,?,?,?,?,?,?,?,?)',(family,asset,cid,start,end,n,int(complete),boundary,max(0,end-start)))
        cid+=1;start=None;seen=False;home=None;away=False;quiet=None
    # Join positions in the same ordered pass; no per-row database lookup.
    positions=iter(db.execute('SELECT ACTPOS FROM samples WHERE asset=? AND ts IS NOT NULL ORDER BY ts,id',(asset,)))
    for rid,ts,vel,active in motion_rows(db,asset,threshold,source):
        pos=next(positions)[0];reset=prev is not None and ts-prev[0]>gap_limit
        if start is not None and (reset or active is None):close(prev[0],False)
        if reset:quiet=None
        if start is None and active:
            start=ts;seen=prev is not None and not reset and prev[2] is False;home=prev[3] if seen else pos
        if start is not None:
            if home is not None and pos is not None and abs(pos-home)>(tolerance or 1e-6):away=True
            if active:quiet=None
            elif active is False and quiet is None:quiet=ts
        acceleration=(abs(vel)-abs(prev[1]))/(ts-prev[0]) if prev and vel is not None and prev[1] is not None and ts>prev[0] and not reset else None
        buffer.append((family,asset_num,rid,cid if start is not None else -1,acceleration));count+=1
        returned=away and home is not None and pos is not None and abs(pos-home)<=(tolerance or 1e-6)
        if start is not None and quiet is not None and ts-quiet>=terminal:
            # A position-confirmed return is preferred. Without it, only a long
            # rest (600 s) closes a candidate group; this is not a PLC completion.
            if returned or ts-quiet>=600:close(quiet,seen,True)
        if len(buffer)>=10000:flush();progress(f'伺服有效周期读取：{asset} · {count:,} 条')
        prev=(ts,vel,active,pos);lastpos=pos
    if start is not None:close(prev[0],False)
    flush()
    return {'kind':'candidate','source':source,'idle_seconds':terminal,'velocity_threshold':threshold,'reference_seconds':600,'position_tolerance':tolerance,'threshold_method':method,'definition':boundary,'note':'周期内等待保留；候选返回位置为起点位置，容差为观察位置范围1%；静止确认后回溯到静止起点结束，不强行截断为600秒。缺失/断档及窗口尾部未确认结束者不完整。'}
