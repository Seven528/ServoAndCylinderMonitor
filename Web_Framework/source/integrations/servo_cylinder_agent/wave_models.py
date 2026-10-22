"""Cycle feature models. Bounded training, complete-population inference, disk Viterbi."""
from __future__ import annotations
import math
import numpy as np


class GaussianHMM:
    """Three diagonal Gaussian states; Baum-Welch EM and Viterbi decoding.

    Multiple contiguous training blocks have separate start distributions. No
    artificial transition is learned across omitted periods or acquisition gaps.
    """
    def fit(self, sequences, iterations=35, progress=None):
        x=np.concatenate(sequences)
        self.center=np.median(x,axis=0)
        self.scale=np.std(x,axis=0);self.scale[self.scale<1e-8]=1
        seq=[(a-self.center)/self.scale for a in sequences]
        z=np.concatenate(seq)
        order=np.argsort(z.mean(axis=1))
        self.means=np.stack([np.mean(part,axis=0) for part in np.array_split(z[order],3)])
        self.var=np.tile(np.maximum(z.var(axis=0),.05),(3,1))
        self.trans=np.full((3,3),.025);np.fill_diagonal(self.trans,.95)
        self.start=np.full(3,1/3)
        previous=-math.inf;self.converged=False;self.history=[]
        for iteration in range(iterations):
            if progress:progress(iteration+1,iterations)
            starts=np.full(3,.01);trans=np.full((3,3),.01)
            weights=np.zeros(3);sx=np.zeros_like(self.means);sx2=np.zeros_like(self.means);ll=0
            for values in seq:
                emission=self.emission_z(values);n=len(values)
                a=np.empty((n,3));a[0]=np.log(self.start)+emission[0]
                lt=np.log(self.trans)
                for t in range(1,n):a[t]=emission[t]+np.logaddexp.reduce(a[t-1,:,None]+lt,axis=0)
                likelihood=np.logaddexp.reduce(a[-1]);ll+=likelihood
                b=np.zeros((n,3))
                for t in range(n-2,-1,-1):b[t]=np.logaddexp.reduce(lt+emission[t+1]+b[t+1],axis=1)
                gamma=np.exp(a+b-likelihood);starts+=gamma[0]
                weights+=gamma.sum(axis=0);sx+=gamma.T@values;sx2+=gamma.T@(values**2)
                trans+=np.exp(a[:-1,:,None]+lt[None,:,:]+emission[1:,None,:]+b[1:,None,:]-likelihood).sum(axis=0)
            self.start=starts/starts.sum();self.trans=trans/trans.sum(axis=1,keepdims=True)
            self.means=sx/np.maximum(weights[:,None],1e-8)
            self.var=np.maximum(sx2/np.maximum(weights[:,None],1e-8)-self.means**2,.02)
            self.history.append(float(ll))
            if iteration>1 and abs(ll-previous)<.001*(1+abs(previous)):
                self.converged=True;break
            previous=ll
        # State labels are an explicit ordering of relative waveform severity,
        # not an independently validated quality or true equipment age label.
        self.stage_map=np.argsort(np.argsort(self.means.mean(axis=1)))
        return self

    def emission_z(self,z):
        return -.5*(np.log(2*np.pi*self.var).sum(axis=1)[None,:]+((z[:,None,:]-self.means)**2/self.var).sum(axis=2))

    def emissions(self,x):return self.emission_z((np.asarray(x)-self.center)/self.scale)


def model_cycles(db,family,asset,progress):
    """Fit per asset; score every eligible cycle and persist HMM back pointers."""
    from sklearn.ensemble import IsolationForest
    fields=['torque_amplitude','velocity_instability','torque_mean','velocity_mean','speed','acc','dec','acceleration_mean','deceleration_mean','duration'] if family=='servo' else ['work_time','base_time','duration']
    where='family=? AND asset=? AND complete=1'
    args=(family,asset)
    count=db.execute('SELECT COUNT(*) FROM cycles WHERE '+where,args).fetchone()[0]
    info={'asset':asset,'cycles':count,'isolation_forest':{'status':'insufficient_data'},'hmm':{'status':'insufficient_data'},'degradation':{'status':'unavailable'}}
    if count<30:return info
    step=max(1,math.ceil(count/10000))
    select=','.join(fields)
    # Evenly spaced bounded training, all cycles are subsequently scored.
    rows=db.execute(f'SELECT {select} FROM (SELECT *,ROW_NUMBER() OVER(ORDER BY cid) rn FROM cycles WHERE {where}) WHERE (rn-1)%?=0',(*args,step)).fetchall()
    train=np.array([[np.nan if v is None else v for v in row] for row in rows],dtype=float)
    usable=np.isfinite(train).sum(axis=0)>=max(10,len(train)*.5)
    medians=np.zeros(len(fields));medians[usable]=np.nanmedian(train[:,usable],axis=0)
    train=np.where(np.isfinite(train),train,medians)
    usable&=train.std(axis=0)>1e-9
    selected=[field for field,valid in zip(fields,usable) if valid]
    if len(selected)>=2:
        model=IsolationForest(n_estimators=100,max_samples=min(256,len(train)),contamination='auto',random_state=42,n_jobs=1).fit(train[:,usable])
        cursor=db.execute(f'SELECT cid,{select} FROM cycles WHERE {where} ORDER BY cid',args)
        scored=0;outliers=0
        while True:
            batch=cursor.fetchmany(5000)
            if not batch:break
            data=np.array([[np.nan if v is None else v for v in row[1:]] for row in batch],dtype=float)
            eligible=np.isfinite(data[:,usable]).sum(axis=1)>=2
            x=np.where(np.isfinite(data),data,medians)[:,usable]
            scores=-model.decision_function(x)
            updates=[(float(score),int(score>0),family,asset,row[0]) for row,score,valid in zip(batch,scores,eligible) if valid]
            db.executemany('UPDATE cycles SET if_score=?,if_anomaly=? WHERE family=? AND asset=? AND cid=?',updates)
            scored+=len(updates);outliers+=sum(row[1] for row in updates)
            progress(f'IsolationForest 正在评分：{asset} · {scored:,} 个完整周期')
        info['isolation_forest']={'status':'ready','model':'IsolationForest','features':selected,'training_cycles':len(train),'scored_cycles':scored,'anomalies':outliers,'contamination':'auto','random_state':42,'threshold':0,'imputation':'训练集字段中位数；至少两个有效特征才评分','sampling':f'按时间每 {step} 个完整周期抽取一个训练，所有可评分周期均推断'}
    # Degradation uses the early 20% of complete cycles under the same speed,
    # acceleration and deceleration setpoints. It is a reference, not healthy truth.
    ref_count=max(10,math.ceil(count*.2))
    db.execute('DROP TABLE IF EXISTS early_reference')
    db.execute('CREATE TEMP TABLE early_reference AS SELECT * FROM cycles WHERE '+where+' ORDER BY cid LIMIT ?',(*args,ref_count))
    if family=='servo':
        db.execute('DROP TABLE IF EXISTS di_reference')
        db.execute('CREATE TEMP TABLE di_reference(speed REAL,acc REAL,dec REAL,amp REAL,vi REAL)')
        db.execute('CREATE INDEX IF NOT EXISTS early_reference_commands ON early_reference(speed,acc,dec)')
        for speed,acc,dec,n in db.execute('SELECT speed,acc,dec,COUNT(*) FROM early_reference GROUP BY speed,acc,dec HAVING COUNT(*)>=5'):
            key=(speed,acc,dec);med=[]
            for field in ['torque_amplitude','velocity_instability']:
                clause='speed IS ? AND acc IS ? AND dec IS ? AND '+field+' IS NOT NULL'
                count_ref=db.execute('SELECT COUNT(*) FROM early_reference WHERE '+clause,key).fetchone()[0]
                pair=db.execute(f'SELECT {field} FROM early_reference WHERE {clause} ORDER BY {field} LIMIT 2 OFFSET ?',(*key,max(0,(count_ref-1)//2))).fetchall() if count_ref else []
                med.append((pair[0][0]+pair[-1][0])/2 if count_ref%2==0 and pair else pair[0][0] if pair else None)
            db.execute('INSERT INTO di_reference VALUES(?,?,?,?,?)',(*key,*med))
        db.execute('CREATE INDEX di_commands ON di_reference(speed,acc,dec)')
        group_count=db.execute('SELECT COUNT(*) FROM di_reference').fetchone()[0]
        updates=[]
        query='SELECT c.cid,c.torque_amplitude,c.velocity_instability,r.amp,r.vi FROM cycles c LEFT JOIN di_reference r ON c.speed IS r.speed AND c.acc IS r.acc AND c.dec IS r.dec WHERE c.family=? AND c.asset=? AND c.complete=1 ORDER BY c.cid'
        for cid,amp,vi,amp_ref,vi_ref in db.execute(query,args):
            parts=[]
            for value,ref in zip([amp,vi],[amp_ref,vi_ref]):
                parts.append(100*(-math.expm1(-max(0,value/ref-1))) if value is not None and ref is not None and ref>1e-8 else None)
            if all(v is not None for v in parts):updates.append((*parts,float(np.mean(parts)),family,asset,cid))
            if len(updates)>=5000:
                db.executemany('UPDATE cycles SET torque_di=?,velocity_di=?,mean_di=? WHERE family=? AND asset=? AND cid=?',updates);updates=[]
                progress(f'退化指标计算：{asset}')
        db.executemany('UPDATE cycles SET torque_di=?,velocity_di=?,mean_di=? WHERE family=? AND asset=? AND cid=?',updates)
        n,mean=db.execute('SELECT COUNT(mean_di),AVG(mean_di) FROM cycles WHERE '+where,args).fetchone()
        info['degradation']={'status':'ready' if n else 'unavailable','eligible_cycles':n,'mean_degradation':mean,'reference_cycles':ref_count,'reference_groups':group_count,'formula':'D(x)=100×[1−exp(−max(0,x/x_ref−1))]；mean degradation=(D_torque+D_velocity)/2','baseline':'每台资产最早 20%（至少 10 个）完整周期；相同 SPEED/ACC/DEC 设定至少 5 个参考周期的中位数。参考窗未经良品标签验证。','torque_amplitude':'运动期间 |ACTTORQUE| 的 P95−P05，表示波形幅度；不含停机保持转矩。','velocity_instability':'非加速/减速的有效运动段，按指令速度和运动方向分组，组内速度方差加权后开方 / 平均绝对速度；减少换向和指令变化的影响。','missing':'基准为零、缺少稳定运动段或新工况无参考时不计算，不以零代替；汇总为可计算周期的等权平均。'}
    # HMM learns contiguous blocks, never false adjacency between sampled cycles.
    hmm_fields=['torque_amplitude','velocity_instability'] if family=='servo' else ['work_time','base_time','duration']
    expr=','.join(hmm_fields);valid=' AND '.join(field+' IS NOT NULL' for field in hmm_fields)
    valid_where=where+' AND '+valid
    valid_n=db.execute('SELECT COUNT(*) FROM cycles WHERE '+valid_where,args).fetchone()[0]
    feature_note=''
    if valid_n<30 and family=='servo':
        hmm_fields=['torque_amplitude'];expr='torque_amplitude';valid='torque_amplitude IS NOT NULL';valid_where=where+' AND '+valid
        valid_n=db.execute('SELECT COUNT(*) FROM cycles WHERE '+valid_where,args).fetchone()[0]
        feature_note='稳定速度片段不足 30 个周期，本资产 HMM 仅使用转矩幅度；退化指数仍要求转矩与速度两个分量。'
    if valid_n<30:return info
    # Ten separate contiguous blocks cover the entire observation period.
    blocks=[];blocklen=min(500,max(3,valid_n//10))
    for offset in sorted(set(np.linspace(0,max(0,valid_n-blocklen),min(10,max(1,valid_n//blocklen))).astype(int))):
        block=db.execute(f'SELECT cid,{expr} FROM cycles WHERE {valid_where} ORDER BY cid LIMIT ? OFFSET ?',(*args,int(blocklen),int(offset))).fetchall()
        segment=[];prior=None
        for row in block:
            if prior is not None and row[0]!=prior+1:
                if segment:blocks.append(np.array(segment));segment=[]
            segment.append(row[1:]);prior=row[0]
        if segment:blocks.append(np.array(segment))
    allx=np.concatenate(blocks)
    if len(np.unique(allx,axis=0))<3 or np.max(allx.std(axis=0))<1e-8:return info
    progress(f'正在拟合 Gaussian HMM：{asset}')
    hmm=GaussianHMM().fit(blocks,progress=lambda step,total:progress(f'HMM 参数拟合：{asset} · 迭代 {step}/{total}'))
    db.execute('DROP TABLE IF EXISTS hmm_path')
    db.execute('CREATE TEMP TABLE hmm_path(seq INTEGER PRIMARY KEY,cid INTEGER,p0 INTEGER,p1 INTEGER,p2 INTEGER,best INTEGER,segment INTEGER)')
    delta=None;prior=None;seqno=0;segment=0
    log_trans=np.log(hmm.trans);log_start=np.log(hmm.start)
    cursor=db.execute(f'SELECT cid,{expr} FROM cycles WHERE {valid_where} ORDER BY cid',args)
    while True:
        batch=cursor.fetchmany(5000)
        if not batch:break
        emission=hmm.emissions([row[1:] for row in batch]);updates=[]
        for row,e in zip(batch,emission):
            cid=row[0]
            if delta is None or cid!=prior+1:
                delta=log_start+e;pointers=[-1]*3;segment+=1
            else:
                choices=delta[:,None]+log_trans;pointers=choices.argmax(axis=0);delta=choices.max(axis=0)+e
            delta-=delta.max();seqno+=1
            updates.append((seqno,cid,*map(int,pointers),int(delta.argmax()),segment));prior=cid
        db.executemany('INSERT INTO hmm_path VALUES(?,?,?,?,?,?,?)',updates)
        progress(f'HMM 已解码 {seqno:,} 个周期')
    next_state=None;prior_segment=None;updates=[]
    for seq,cid,p0,p1,p2,best,seg in db.execute('SELECT * FROM hmm_path ORDER BY seq DESC'):
        current=best if prior_segment!=seg else next_state
        updates.append((int(hmm.stage_map[current]),family,asset,cid));next_state=[p0,p1,p2][current];prior_segment=seg
        if len(updates)>=5000:
            db.executemany('UPDATE cycles SET stage=? WHERE family=? AND asset=? AND cid=?',updates);updates=[]
    db.executemany('UPDATE cycles SET stage=? WHERE family=? AND asset=? AND cid=?',updates)
    info['hmm']={'status':'ready','model':'Gaussian HMM · diagonal covariance · Baum–Welch EM + Viterbi','features':hmm_fields,'feature_note':feature_note,'training_cycles':len(allx),'decoded_cycles':seqno,'transition_matrix':hmm.trans.tolist(),'start_probabilities':hmm.start.tolist(),'feature_center':hmm.center.tolist(),'feature_scale':hmm.scale.tolist(),'diagonal_variance':hmm.var.tolist(),'iterations':len(hmm.history),'converged':hmm.converged,'states':[{'stage':int(hmm.stage_map[k]),'relative_center':hmm.means[k].tolist()} for k in range(3)],'sampling':'全时间窗最多 10 个连续块、每块最多 500 个周期训练；全部有效周期磁盘 Viterbi 解码；缺失周期与采样断档重置序列。','interpretation':'按模型状态的平均标准化幅度/不稳定度由低到高命名为阶段 0/1/2；属于相对波形状态，未经设备寿命或良品/次品标签验证，不代表次品概率。'}
    return info
