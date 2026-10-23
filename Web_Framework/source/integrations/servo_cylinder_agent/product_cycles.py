"""Candidate product starts from separated motion groups, never command counts.

The supplied schema has no authoritative product-start marker. Long quiescence
separates candidate groups; it does not prove a one-to-one product mapping.
"""
import math


def motion_rows(db, asset, threshold, source):
    prior_counter=None
    for rid,ts,execute,still,vel,counter in db.execute('SELECT id,ts,execute,standstill,ACTVEL,MOVEMENTCOUNTER FROM samples WHERE asset=? AND ts IS NOT NULL ORDER BY ts,id',(asset,)):
        if source=='ACTVEL':active=None if vel is None else abs(vel)>threshold
        elif source=='STANDSTILL':active=None if still is None else still==0
        else:active=counter is not None and prior_counter is not None and counter>prior_counter
        yield rid,ts,vel,active
        prior_counter=counter


def settings(db,asset,threshold,gap_limit,progress):
    db.execute('CREATE TEMP TABLE IF NOT EXISTS product_settings(asset TEXT PRIMARY KEY,source TEXT,idle REAL,method TEXT)')
    cached=db.execute('SELECT source,idle,method FROM product_settings WHERE asset=?',(asset,)).fetchone()
    if cached:return cached
    velocity,still,counters=db.execute('SELECT MAX(ABS(ACTVEL)),COUNT(DISTINCT standstill),COUNT(DISTINCT MOVEMENTCOUNTER) FROM samples WHERE asset=?',(asset,)).fetchone()
    source='ACTVEL' if velocity and velocity>threshold else 'STANDSTILL' if still==2 else 'MOVEMENTCOUNTER' if counters>1 else 'unavailable'
    db.execute('DROP TABLE IF EXISTS product_idle');db.execute('CREATE TEMP TABLE product_idle(duration REAL)')
    quiet=None;previous=None;pending=[]
    for i,(_,ts,vel,active) in enumerate(motion_rows(db,asset,threshold,source)):
        if previous is not None and ts-previous>gap_limit:quiet=None
        if active is None:quiet=None
        elif active:
            if quiet is not None and ts>quiet:pending.append((ts-quiet,))
            quiet=None
        elif quiet is None:quiet=ts
        previous=ts
        if len(pending)>=1000:db.executemany('INSERT INTO product_idle VALUES(?)',pending);pending=[]
        if i%10000==0:progress(f'识别产品动作组间隔：{asset} · {i:,} 条')
    db.executemany('INSERT INTO product_idle VALUES(?)',pending)
    best=4.;split=None;previous=None
    for (duration,) in db.execute('SELECT duration FROM product_idle WHERE duration>=0.5 ORDER BY duration'):
        if previous and duration/previous>best:best=duration/previous;split=math.sqrt(previous*duration)
        previous=duration
    idle=split if split is not None else 10.
    method='静止时长最大倍率间隙（倍率≥4）几何中点' if split is not None else '静止时长未明显分群，使用假设阈值 10 秒'
    db.execute('INSERT INTO product_settings VALUES(?,?,?,?)',(asset,source,idle,method))
    return source,idle,method
