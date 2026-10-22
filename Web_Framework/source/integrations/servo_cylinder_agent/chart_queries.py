"""One ordered read for all chart signals; exact quantiles, bounded buffers."""
from __future__ import annotations
import math
import numpy as np

BUFFER_ROWS=50_000  # In-memory buffer only; denser buckets spill to local disk.


def read_charts(db,family,asset,start,end,metrics,width):
    if not metrics:return []
    columns=list(metrics);series=[[] for _ in columns]
    totals=[{'count':0,'min':None,'max':None,'sum':0.0} for _ in columns]
    names=[f'v{i}' for i in range(len(columns))]
    buffer=[];pending=[];spilled=False;current=None

    def spill_pending():
        if pending:
            db.executemany('INSERT INTO chart_spill VALUES('+','.join('?' for _ in names)+')',pending);pending.clear()

    def finish(bucket):
        nonlocal buffer,spilled
        if bucket is None:return
        if spilled:spill_pending()
        matrix=np.asarray(buffer,dtype=float) if not spilled else None
        for i,column in enumerate(columns):
            if spilled:
                name=names[i]
                count,minimum,maximum,mean=db.execute(f'SELECT COUNT({name}),MIN({name}),MAX({name}),AVG({name}) FROM chart_spill').fetchone()
                if not count:continue
                # The usual buffer stays in NumPy; this exact disk path handles
                # arbitrary-density timestamps without loading the whole bucket.
                db.execute(f'CREATE INDEX chart_spill_value ON chart_spill({name})')
                qs=[]
                for q in [.05,.5,.95]:
                    rank=(count-1)*q;offset=int(rank)
                    pair=db.execute(f'SELECT {name} FROM chart_spill WHERE {name} IS NOT NULL ORDER BY {name} LIMIT 2 OFFSET ?',(offset,)).fetchall()
                    qs.append(pair[0][0]+(pair[-1][0]-pair[0][0])*(rank-offset))
                db.execute('DROP INDEX chart_spill_value')
                variance=db.execute(f'SELECT AVG(({name}-?)*({name}-?)) FROM chart_spill',(mean,mean)).fetchone()[0]
                std=math.sqrt(max(0,variance))
            else:
                values=matrix[:,i];values=values[np.isfinite(values)]
                count=len(values)
                if not count:continue
                minimum=float(values.min());maximum=float(values.max());mean=float(values.mean());std=float(values.std())
                qs=np.quantile(values,[.05,.5,.95]).tolist()
            series[i].append({'time':start+(bucket+.5)*width,'count':count,'min':minimum,'max':maximum,'mean':mean,'std':std,'p05':qs[0],'median':qs[1],'p95':qs[2]})
            total=totals[i];total['count']+=count;total['sum']+=mean*count
            total['min']=minimum if total['min'] is None else min(total['min'],minimum)
            total['max']=maximum if total['max'] is None else max(total['max'],maximum)
        if spilled:db.execute('DROP TABLE chart_spill')
        buffer=[];spilled=False

    # Force the selective (asset,time) range first, then a primary-key membership
    # probe. The previous planner could scan all family rows for every zoom.
    cursor=db.execute('SELECT s.ts,'+','.join('s.'+c for c in columns)+''' FROM samples s INDEXED BY samples_asset_time
        CROSS JOIN wave_rows w ON w.family=? AND w.sample_id=s.id
        WHERE s.asset=? AND s.ts>=? AND s.ts<=? ORDER BY s.ts,s.id''',(family,asset,start,end))
    while True:
        batch=cursor.fetchmany(10_000)
        if not batch:break
        for row in batch:
            bucket=min(499,int((row[0]-start)/width))
            if bucket!=current:finish(current);current=bucket
            values=row[1:]
            if spilled:
                pending.append(values)
                if len(pending)>=5000:spill_pending()
            else:
                buffer.append(values)
                if len(buffer)>=BUFFER_ROWS:
                    db.execute('CREATE TEMP TABLE chart_spill('+','.join(name+' REAL' for name in names)+')')
                    db.executemany('INSERT INTO chart_spill VALUES('+','.join('?' for _ in names)+')',buffer)
                    buffer=[];spilled=True
    finish(current)
    result=[]
    for i,(column,label) in enumerate(metrics.items()):
        if not series[i]:continue
        total=totals[i]
        result.append({'key':column,'label':label,'points':series[i],'statistics':{'count':total['count'],'min':total['min'],'max':total['max'],'mean':total['sum']/total['count']}})
    return result
