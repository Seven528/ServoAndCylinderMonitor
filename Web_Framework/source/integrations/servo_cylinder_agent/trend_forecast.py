"""Small, holdout-selected trend forecasts independent of failure labels/cycles."""
import math
import numpy as np


def forecast(db,progress):
    result=[]
    metrics={'ACTTORQUE':'实际扭矩均值（原单位）','ACTVEL':'实际速度均值（原单位）','MOVETOWORKTIME_MS':'气缸工作时间均值 ms','MOVETOTBASTIME_MS':'气缸回程时间均值 ms'}
    # Same asset preview scope as the UI; all observations contribute within each asset.
    for (asset,) in db.execute('SELECT DISTINCT asset FROM samples ORDER BY asset LIMIT 100'):
        start,end=db.execute('SELECT MIN(ts),MAX(ts) FROM samples WHERE asset=?',(asset,)).fetchone()
        if start is None or end<=start:continue
        width=(end-start)/96
        for key,label in metrics.items():
            progress(f'计算趋势预测：{asset} · {label}')
            rows=db.execute(f'''SELECT MIN(95,CAST((ts-?)/? AS INTEGER)) b,AVG({key}),COUNT({key}) FROM samples INDEXED BY samples_asset_time
                WHERE asset=? AND ts IS NOT NULL AND {key} IS NOT NULL GROUP BY b ORDER BY b''',(start,width,asset)).fetchall()
            # Use only the final contiguous block; never extrapolate across missing buckets.
            block=[];previous=None
            for b,value,n in rows:
                if previous is not None and b!=previous+1:block=[]
                if n<3:block=[];previous=b;continue
                block.append((b,value,n));previous=b
            if len(block)<12:
                result.append({'asset':asset,'signal':key,'label':label,'status':'insufficient_data','reason':'末段不足12个连续有效时间桶（每桶至少3条记录）'});continue
            if end-(start+(block[-1][0]+1)*width)>width:
                result.append({'asset':asset,'signal':key,'label':label,'status':'insufficient_data','reason':'该信号末段过旧，停止预测'});continue
            x=np.array([r[0] for r in block],float);y=np.array([r[1] for r in block],float)
            hold=max(3,len(x)//5);train_x=x[:-hold];train_y=y[:-hold]
            fit=np.polyfit(train_x,train_y,1);linear=np.polyval(fit,x[-hold:]);baseline=np.full(hold,train_y[-1])
            linear_mae=float(np.mean(abs(linear-y[-hold:])));base_mae=float(np.mean(abs(baseline-y[-hold:])))
            use_linear=linear_mae<base_mae
            residual=y[-hold:]-(linear if use_linear else baseline)
            scale=float(np.sqrt(np.mean(residual**2)))
            fitted=np.polyfit(x,y,1) if use_linear else (0.,y[-1])
            steps=max(1,min(24,int(len(x)*.2)));future=[]
            for step in range(1,steps+1):
                value=float(np.polyval(fitted,x[-1]+step));radius=1.96*scale*math.sqrt(1+step/hold)
                future.append({'time':start+(x[-1]+step+.5)*width,'value':value,'low':value-radius,'high':value+radius})
            result.append({'asset':asset,'signal':key,'label':label,'status':'ready','model':'线性趋势' if use_linear else '保持最近值（趋势未优于基线）','bucket_seconds':width,'history_buckets':len(x),'holdout_buckets':hold,'linear_mae':linear_mae,'baseline_mae':base_mae,'selected_mae':min(linear_mae,base_mae),'slope_per_hour':float(fitted[0]*3600/width),'history':[{'time':start+(b+.5)*width,'value':v} for b,v,n in block],'future':future})
    return {'method':'最近连续时间桶均值；末20%时间留出回测，在最小二乘线性趋势与保持最近值之间按MAE选择。全段重新拟合后外推不超过历史20%且最多24桶。阴影为回测RMSE启发式误差带（非校准置信区间），工况变化时失效；不是RUL或故障概率。','assets_preview_limit':100,'series':result}
