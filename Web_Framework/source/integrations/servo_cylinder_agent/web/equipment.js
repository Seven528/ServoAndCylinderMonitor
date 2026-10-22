// Detailed time navigation queries retained local evidence, never a sampled prefix.
const esc=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=(v,d=2)=>v==null||!Number.isFinite(Number(v))?'—':Number(v).toLocaleString('zh-CN',{maximumFractionDigits:d});
const date=t=>new Date(t*1000).toLocaleString('zh-CN',{hour12:false});
const local=t=>{const d=new Date(t*1000);return new Date(d-d.getTimezoneOffset()*60000).toISOString().slice(0,23)};
const seriesNames={median:'中位数',mean:'均值',p95:'P95',p05:'P05',min:'最小值',max:'最大值',std:'标准差',if_score:'IsolationForest 异常分数',mean_di:'平均退化指数',torque_di:'转矩退化指数',velocity_di:'速度退化指数',stage:'HMM 阶段',torque_amplitude:'转矩幅度 P95−P05',velocity_instability:'速度不稳定度 CV',work_time:'工作行程 ms',base_time:'回程 ms'};
const colors=['#007bc0','#006c3a','#9e2896','#c06000','#355c7d','#525f6b','#827200'];
const familyNames={servo:'伺服',cylinder:'气缸'};
const controllers=[];
const viewCache=new Map();
function loadView(api,path,body){
 const key=path+'|'+JSON.stringify(body);
 if(viewCache.has(key)){const value=viewCache.get(key);viewCache.delete(key);viewCache.set(key,value);return value}
 const promise=api(path,{method:'POST',body:JSON.stringify(body)}).catch(error=>{viewCache.delete(key);throw error});
 viewCache.set(key,promise);while(viewCache.size>12)viewCache.delete(viewCache.keys().next().value);
 return promise;
}

function svgPlot(title,points,keys,data,{risk=false,threshold=false,stage=false,anomaly=false}={}){
  const W=860,H=230,L=68,R=18,T=16,B=42,PW=W-L-R,PH=H-T-B;
  const values=points.flatMap(p=>keys.map(k=>p[k])).filter(v=>v!=null&&Number.isFinite(v));
  if(!values.length)return `<article class="wave-chart"><h4>${esc(title)}</h4><p class="muted">所选区间没有可计算数据。</p></article>`;
  let low=stage?0:Math.min(...values),high=stage?2:Math.max(...values);
  if(threshold){low=Math.min(low,0);high=Math.max(high,0)}
  let span=high-low||Math.max(1,Math.abs(low)*.1);if(!stage){low-=span*.08;high+=span*.08;span=high-low}
  const x=t=>L+(t-data.start)/Math.max(.000001,data.end-data.start)*PW;
  const y=v=>T+(high-v)/(high-low||1)*PH;
  const bands=data.bands.map(b=>{const a=Math.max(L,x(b.start)),end=Math.min(W-R,x(b.end));if(end<a)return '';return `<rect x="${a}" y="${T}" width="${Math.max(.5,end-a)}" height="${PH}" fill="${b.cid%2?'#d8edfa':'#fff'}"><title>周期 ${b.cid} · ${b.complete?'完整':'边界不完整'} · ${esc(date(b.start))} — ${esc(date(b.end))}</title></rect>`}).join('');
  const red=risk?data.bands.filter(b=>b.stage===2).map(b=>`<rect class="risk-band" x="${Math.max(L,x(b.start))}" y="${T}" width="${Math.max(.5,Math.min(W-R,x(b.end))-Math.max(L,x(b.start)))}" height="${PH}" fill="#ed0007" opacity=".16"><title>危险区域：HMM 阶段 2 · 周期 ${b.cid}（次品关联未验证）</title></rect>`).join(''):'';
  const grid=[0,.5,1].map(r=>`<line x1="${L}" x2="${W-R}" y1="${T+r*PH}" y2="${T+r*PH}" stroke="#dde4e8"/><text x="${L-8}" y="${T+r*PH+4}" text-anchor="end">${num(high-r*(high-low),3)}</text>`).join('');
  const paths=keys.map((k,index)=>{let path='',prior=null;for(const p of points){const v=p[k];if(v==null||!Number.isFinite(v)){prior=null;continue}const gap=prior!=null&&(p.first_cid!=null?p.first_cid>prior.last_cid+1:p.time-prior.time>data.resolution_seconds*2.1);path+=prior==null||gap?`M${x(p.time).toFixed(2)},${y(v).toFixed(2)} `:stage?`H${x(p.time).toFixed(2)} V${y(v).toFixed(2)} `:`L${x(p.time).toFixed(2)},${y(v).toFixed(2)} `;prior=p}return `<path d="${path}" fill="none" stroke="${colors[index%colors.length]}" stroke-width="${index?1.5:2}" ${index>1?'stroke-dasharray="4 3"':''}/>`}).join('');
  const marks=anomaly?points.filter(p=>p.anomalies>0&&p.if_score!=null).map(p=>`<circle cx="${x(p.time)}" cy="${y(p.if_score)}" r="3" fill="#ed0007"><title>此时间桶 ${p.anomalies} 个异常 / ${p.cycles} 个完整周期</title></circle>`).join(''):'';
  const zero=threshold?`<line x1="${L}" x2="${W-R}" y1="${y(0)}" y2="${y(0)}" stroke="#ed0007" stroke-dasharray="5 3"/>`:'';
  const labels=[0,.5,1].map(r=>`<text x="${L+r*PW}" y="${H-12}" text-anchor="${r===0?'start':r===1?'end':'middle'}">${esc(date(data.start+r*(data.end-data.start)))}</text>`).join('');
  return `<article class="wave-chart"><h4>${esc(title)}</h4><svg class="zoom-plot" viewBox="0 0 ${W} ${H}" tabindex="0" role="img" aria-label="${esc(title)}。拖动选择时间范围，双击恢复全部。" data-left="${L/W}" data-right="${(W-R)/W}"><rect x="${L}" y="${T}" width="${PW}" height="${PH}" fill="#f7f9fa"/>${bands}${red}${grid}${zero}${paths}${marks}${labels}<rect class="brush-selection" y="${T}" height="${PH}" fill="#007bc0" opacity=".18" hidden/></svg><div class="chart-legend">${keys.map((k,i)=>`<span><i class="legend-dot" style="background:${colors[i%colors.length]}"></i>${esc(seriesNames[k]||k)}</span>`).join('')}${threshold?'<span class="danger-text">红点：桶内有异常周期；红虚线：分数 0 阈值</span>':''}${risk?'<span class="danger-text">红色半透明：阶段 2 危险区域（模型筛查）</span>':''}</div><output class="wave-tooltip">悬停查看数值；拖动框选时间，双击恢复全部。</output></article>`;
}

function metrics(view,mode){
 const s=view.scope,ifm=view.model_info.isolation_forest;
 const items=mode==='overview'?[["区间记录",view.charts[0]?.statistics.count],["相交周期",view.cycle_count],["完整周期",s.complete_cycles]]:mode==='diagnostic'?[["完整周期",s.complete_cycles],["IF 异常周期",s.if_anomalies],["mean degradation",s.mean_degradation==null?'不可计算':num(s.mean_degradation)+' / 100']]:[["HMM 已划分周期",s.hmm_cycles],["阶段 2 周期",s.high_risk_cycles],["高危占比",s.hmm_cycles?num(s.high_risk_cycles/s.hmm_cycles*100)+'%':'不可计算']];
 return `<div class="equipment-kpis">${items.map(([label,value])=>`<div><small>${esc(label)}</small><strong>${typeof value==='number'?num(value,0):esc(value)}</strong></div>`).join('')}</div>`;
}

class EquipmentView {
 constructor(host,mode,family,result,api){this.host=host;this.mode=mode;this.family=family;this.result=result;this.api=api;this.catalog=result.equipment[family];this.assets=this.catalog.assets;this.keys=['median','mean','p95'];this.version=0;this.drawShell()}
 drawShell(){
  const name=familyNames[this.family];
  this.host.innerHTML=`<section class="equipment-section"><header class="equipment-heading"><h3>${name}<small>${this.mode==='overview'?'波形与周期':this.mode==='diagnostic'?'异常与退化':'生命周期状态'}</small></h3><span>按资产独立计算</span></header><div class="equipment-body">${!this.assets.length?'<p class="callout">当前数据没有可用的'+name+'字段或有效时间戳。</p>':`<div class="asset-picker"><label>资产<select aria-label="${name}资产"></select></label><form class="asset-search"><label>查找资产<input type="search" placeholder="输入资产名称或站点" aria-label="查找${name}资产"/></label><button type="submit">查找</button></form></div><p class="muted asset-scope"></p><div class="time-toolbar"><button data-action="all">全部时间</button><button data-action="in">放大 ＋</button><button data-action="out">缩小 −</button><button data-action="prev" aria-label="向前平移时间">←</button><button data-action="next" aria-label="向后平移时间">→</button><label>开始<input class="time-start" type="datetime-local" step=".001"/></label><label>结束<input class="time-end" type="datetime-local" step=".001"/></label><button data-action="apply">应用区间</button></div><div class="stat-options" ${this.mode!=='overview'?'hidden':''}><span>显示统计：</span>${['median','mean','p05','p95','min','max','std'].map(k=>`<label><input type="checkbox" value="${k}" ${this.keys.includes(k)?'checked':''}/> ${seriesNames[k]}</label>`).join('')}</div><p class="equipment-status" role="status"></p><div class="equipment-content"></div>`}</div></section>`;
  if(!this.assets.length)return;
  this.select=this.host.querySelector('select');this.content=this.host.querySelector('.equipment-content');this.status=this.host.querySelector('.equipment-status');this.fillAssets();
  this.select.onchange=()=>this.reset();
  this.host.querySelector('.asset-search').onsubmit=async e=>{e.preventDefault();try{const q=this.host.querySelector('input[type=search]').value;const response=await this.api(`/api/equipment/${this.result.run_id}`,{method:'POST',body:JSON.stringify({action:'assets',family:this.family,query:q})});this.assets=response.assets;this.fillAssets();if(this.assets.length)this.reset();else{this.content.innerHTML='';this.status.textContent='没有匹配资产，请修改关键词。'}}catch(e){this.status.textContent=e.message}};
  this.host.querySelectorAll('[data-action]').forEach(b=>b.onclick=()=>this.action(b.dataset.action));
  this.host.querySelectorAll('.stat-options input').forEach(i=>i.onchange=()=>{this.keys=[...this.host.querySelectorAll('.stat-options input:checked')].map(x=>x.value);if(!this.keys.length){i.checked=true;this.keys=[i.value]}this.draw()});
  if(this.mode==='overview'||!this.host.closest('.panel').hidden)this.reset();
 }
 fillAssets(){this.select.innerHTML=this.assets.map(a=>`<option value="${esc(a.asset)}">${esc(a.asset)}</option>`).join('');this.host.querySelector('.asset-scope').textContent=`共 ${num(this.catalog.total_assets,0)} 个资产，当前列表 ${this.assets.length} 个；可查找其余资产。`}
 reset(){const a=this.assets.find(a=>a.asset===this.select.value);if(!a)return;this.full=[a.start,a.end];this.range=[...this.full];this.load()}
 action(action){if(!this.range)return;let [a,b]=this.range,w=b-a||1,c=(a+b)/2;
 if(action==='all')this.range=[...this.full];
 else if(action==='in')this.range=[c-w/4,c+w/4];
 else if(action==='out')this.range=[c-w,c+w];
 else if(action==='prev'||action==='next'){const shift=w*.6*(action==='prev'?-1:1);this.range=[a+shift,b+shift]}
 else if(action==='apply'){const a=new Date(this.host.querySelector('.time-start').value).valueOf()/1000,b=new Date(this.host.querySelector('.time-end').value).valueOf()/1000;if(!Number.isFinite(a)||!Number.isFinite(b)||b<a){this.status.textContent='请选择有效的开始和结束时间。';return}this.range=[a,b]}
 this.range=[Math.max(this.full[0],this.range[0]),Math.min(this.full[1],this.range[1])];if(this.range[1]<this.range[0]){this.range=[...this.full]}this.load();
 }
 async load(){const version=++this.version;this.status.textContent='正在按所选时间范围读取完整数据…';this.content.setAttribute('aria-busy','true');
 const began=performance.now();const timer=setInterval(()=>{if(version===this.version)this.status.textContent=`正在读取所选区间全部数据… 已等待 ${Math.floor((performance.now()-began)/1000)} 秒`},1000);
 try{const view=await loadView(this.api,`/api/equipment/${this.result.run_id}`,{family:this.family,view:this.mode,asset:this.select.value,start:this.range[0],end:this.range[1]});if(version!==this.version)return;this.view=view;this.range=[view.start,view.end];this.host.querySelector('.time-start').value=local(view.start);this.host.querySelector('.time-end').value=local(view.end);this.draw();this.status.textContent=`${date(view.start)} — ${date(view.end)} · 蓝/白交替表示相邻周期${view.dense_cycles?'；周期密集，放大后显示周期背景':''}。${view.model_info.boundary}。`}
 catch(e){if(version===this.version){this.status.textContent=e.message;this.content.innerHTML='<p class="callout">当前区间读取失败，请重新选择。</p>'}}finally{clearInterval(timer);if(version===this.version)this.content.removeAttribute('aria-busy')}
 }
 draw(){const v=this.view;if(!v)return;const mode=this.mode,info=v.model_info;
 let html=metrics(v,mode);
 if(mode==='overview'){
  html+=`<p class="method-copy">${esc(v.statistics)} P05/P95 描述分布两端；标准差表示桶内离散程度，不是置信区间。首尾不完整周期仍展示波形，不进入周期模型。</p>`;
  html+=v.charts.map(c=>svgPlot(c.label,c.points,this.keys,v)).join('');
  html+=`<details class="details"><summary>所选时间范围描述统计</summary><div class="table-wrap"><table><thead><tr><th>信号</th><th>有效记录</th><th>均值</th><th>最小值</th><th>最大值</th></tr></thead><tbody>${v.charts.map(c=>`<tr><td>${esc(c.label)}</td>${['count','mean','min','max'].map(k=>`<td>${num(c.statistics[k],k==='count'?0:3)}</td>`).join('')}</tr>`).join('')}</tbody></table></div></details>`;
 } else if(mode==='diagnostic'){
  const m=info.isolation_forest;
  if(m.status==='ready'){
   html+=`<p class="method-copy"><b>模型：IsolationForest</b> · ${esc(m.features.join('、'))}。${esc(m.sampling)}；${esc(m.imputation)}。100 棵树，max_samples≤256，contamination=auto，random_state=42；异常分数 = −decision_function，>0 为异常。多变量异常不代表其中每个字段都异常，也不能直接归因为某一个字段。</p>`;
   html+='<p class="method-copy">曲线显示每个时间桶内的最大异常分数。</p>';
   html+=svgPlot('多变量异常检测',v.models,['if_score'],v,{threshold:true,anomaly:true});
  }else html+='<p class="callout">IsolationForest 暂不可用：至少需要 30 个完整周期、两个有变化的有效特征。</p>';
  html+='<details class="details"><summary>原有筛查模型与边界</summary><p>逐行统计模型：按资产/工况拟合中位数与 MAD，稳健 Z 分数阈值 3.5；MAD 为零时使用标准差。动作时间使用中位数 + max(5.2×MAD, 10%×|中位数|)。驱动诊断位使用布尔规则。上方 IF 是额外的周期级多变量模型，异常周期数与原有异常快照数不可相加。</p></details>';
  if(this.family==='servo'){
   const d=info.degradation;
   html+=`<h4>Degradation index · 退化指标</h4><p class="method-copy">当前区间 ${num(v.scope.degradation_cycles,0)} / ${num(v.scope.complete_cycles,0)} 个完整周期可计算，汇总按可计算周期等权平均。</p><p class="method-copy"><b>转矩幅度：</b>运动段 |ACTTORQUE| 的 P95−P05。<b>速度不稳定度：</b>稳定运动段按速度设定与方向分组后的加权组内标准差 / 平均绝对速度，排除加速、减速与换向影响。不是对整个往返波形直接计算 CV。</p><p class="method-copy">${esc(d.formula||'D(x)=100×[1−exp(−max(0,x/x_ref−1))]；mean degradation=(D_torque+D_velocity)/2')}。${esc(d.baseline||'使用同一资产前 20% 完整周期中相同 SPEED/ACC/DEC 设定的参考中位数；每种参考工况至少 5 个周期。')} ${esc(d.missing||'缺少稳定运动段、参考为零或无同工况参考时不可计算。')} 分数是相对参考的增幅映射，不是磨损百分比；负载/产品变化也可能影响该指标。</p>`;
   html+=svgPlot('Mean degradation · 0–100',v.models,['mean_di','torque_di','velocity_di'],v);
   html+=svgPlot('Torque amplitude · 转矩幅度',v.models,['torque_amplitude'],v);
   html+=svgPlot('Velocity instability · 无量纲',v.models,['velocity_instability'],v);
  }else{
   html+='<p class="method-copy">气缸没有独立转矩/速度波形，不能套用伺服 mean degradation 公式；使用工作/回程时间、周期时长进行异常与 HMM 分析。</p>';
   html+=svgPlot('气缸周期动作时间',v.models,['work_time','base_time'],v);
  }
 }else{
  const hmm=info.hmm;
  html+='<div class="stage-legend"><span class="stage-0">阶段 0（健康）</span><span class="stage-1">阶段 1（退化）</span><span class="stage-2">阶段 2（高危）</span></div><p class="risk-explanation"><b>危险区域＝模型阶段 2。</b>红色区域提示优先复核；目前没有逐周期良品/次品标签，不能声称进入区域就极易产生次品，也不能把相对波形状态等同于已验证的真实生命周期。</p>';
  if(hmm.status==='ready'){
   html+=`<p class="method-copy"><b>Gaussian HMM</b> · 输入：${esc(hmm.features.join('、'))}。${esc(hmm.feature_note||'')} 状态按特征水平由低到高排序；允许恢复，不强制单向退化。</p>`;
   html+=svgPlot('HMM 生命周期阶段 · 0 / 1 / 2',v.models,['stage'],v,{risk:true,stage:true});
   html+=`<p class="method-copy">同一时间桶包含多个周期时，阶段线显示该桶最高阶段；红色背景按实际阶段 2 周期绘制。${v.dense_cycles?'当前周期过密，需放大后查看逐周期红色区域。':''} 跨缺失周期和采样断档不连线推断生命周期。</p>`;
   html+=`<details class="details"><summary>HMM 模型方法与训练覆盖</summary><p class="method-copy"><b>${esc(hmm.model)}</b> · 输入：${esc(hmm.features.join('、'))}。${esc(hmm.sampling)} ${esc(hmm.interpretation)} ${esc(hmm.feature_note||'')} EM ${hmm.iterations} 次，${hmm.converged?'已满足数值收敛条件':'达到迭代上限，尚未确认收敛'}。模型允许状态恢复，不强制随时间单向恶化。</p></details>`;
   const signals=this.family==='servo'?['ACTTORQUE','ACTVEL']:['MOVETOWORKTIME_MS','MOVETOTBASTIME_MS'];
   html+=v.charts.filter(c=>signals.includes(c.key)).map(c=>svgPlot(c.label+' · 危险区域叠加',c.points,['median','p95'],v,{risk:true})).join('');
  }else html+='<p class="callout">HMM 暂不可用：至少需要 30 个特征完整的周期，以及足够的波形变化。缺失稳定速度片段时，伺服状态不会用虚构数值补齐。</p>';
 }
 this.content.innerHTML=html;this.bindPlots();
 }
 bindPlots(){
  const plots=[...this.content.querySelectorAll('.zoom-plot')];
  plots.forEach(svg=>{let down=null;const fraction=e=>{const rect=svg.getBoundingClientRect();const f=(e.clientX-rect.left)/rect.width;return Math.max(0,Math.min(1,(f-Number(svg.dataset.left))/(Number(svg.dataset.right)-Number(svg.dataset.left))))};
   svg.onpointerdown=e=>{if(e.button!==0)return;down=fraction(e);svg.setPointerCapture(e.pointerId)};
   svg.onpointermove=e=>{const f=fraction(e),tooltip=svg.closest('article').querySelector('output');
    if(down!=null){const rect=svg.querySelector('.brush-selection');rect.removeAttribute('hidden');rect.setAttribute('x',68+Math.min(down,f)*774);rect.setAttribute('width',Math.abs(f-down)*774);return}
    const target=this.range[0]+f*(this.range[1]-this.range[0]);const chart=this.view.charts.find(c=>svg.getAttribute('aria-label').startsWith(c.label));const points=chart?.points||this.view.models;let nearest=null;for(const p of points)if(!nearest||Math.abs(p.time-target)<Math.abs(nearest.time-target))nearest=p;if(nearest){const keys=chart?this.keys:Object.keys(seriesNames).filter(k=>nearest[k]!=null);tooltip.textContent=`${date(nearest.time)} · ${keys.filter(k=>nearest[k]!=null).map(k=>`${seriesNames[k]||k} ${num(nearest[k],4)}`).join(' · ')}${nearest.count!=null?' · n='+nearest.count:''}`}
   };
   svg.onpointerup=e=>{if(down==null)return;const end=fraction(e),a=down;down=null;svg.querySelector('.brush-selection').setAttribute('hidden','');if(Math.abs(end-a)>.01){const [s,t]=this.range;this.range=[s+Math.min(a,end)*(t-s),s+Math.max(a,end)*(t-s)];this.load()}};
   svg.onpointercancel=()=>{down=null;svg.querySelector('.brush-selection').setAttribute('hidden','')};
   svg.ondblclick=()=>this.action('all');
   svg.onkeydown=e=>{if(['+','=','-','ArrowLeft','ArrowRight','Home'].includes(e.key)){e.preventDefault();this.action(({'+':'in','=':'in','-':'out','ArrowLeft':'prev','ArrowRight':'next','Home':'all'})[e.key])}};
  });
 }
}

export function renderEquipmentViews(result,api){
 viewCache.clear();controllers.splice(0).forEach(c=>c.version++);
 for(const [mode,id] of [['overview','overview-devices'],['diagnostic','diagnostic-devices'],['lifecycle','lifecycle-devices']]){
  const host=document.getElementById(id);host.replaceChildren();
  if(!result.equipment){host.innerHTML='<p class="callout">请重新运行完整分析以生成周期、退化指标与 HMM 状态。</p>';continue}
  for(const family of ['servo','cylinder']){const section=document.createElement('div');host.append(section);controllers.push(new EquipmentView(section,mode,family,result,api))}
 }
}

export function activateEquipmentTab(){for(const view of controllers)if(!view.view&&!view.host.closest('.panel').hidden&&view.assets.length)view.reset()}
