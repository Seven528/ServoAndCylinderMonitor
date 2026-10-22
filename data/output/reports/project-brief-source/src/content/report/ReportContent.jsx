import React, {useState} from 'react';
import {DataComponent, DataTable, EvidenceChart, ReportSection, RichNarrative, useDataApp} from '../../data-app-public.jsx';
import {ReportDisclosure} from '../shared/ReportDisclosure.jsx';
import {copy} from './copy.js';
import logo from '../assets/bosch-logo.svg';
import supergraphic from '../assets/bosch-supergraphic.svg';
import lifecycleImage from '../assets/equipment-hmm-lifecycle.jpg';
import performanceImage from '../assets/performance-optimized.jpg';

const sections=[['purpose','业务问题'],['capabilities','已实现能力'],['architecture','Agent 架构'],['models','模型与指标'],['engineering','大数据与工程'],['performance','性能证据'],['next','下一阶段']];
const modules=[
 ['main_web.py / server.py','启动、HTTP API、单工作线程任务、会话、进度与取消'],
 ['local_source.py / clickhouse_source.py','CSV/XLSX 与 ClickHouse 流式读取、字段与时间处理'],
 ['analysis.py / disk_analysis.py','流程编排、规范化、磁盘精确统计与数据质量'],
 ['equipment_analysis.py / cycle_features.py','伺服/气缸分区、周期提取与批量特征计算'],
 ['wave_models.py','IsolationForest、退化指数、Gaussian HMM 与磁盘 Viterbi'],
 ['chart_queries.py / web/equipment.js','单次有序读取、精确时间桶、图表交互与区间缓存'],
 ['agent_models.py / codex_runtime.py','证据摘要、本地/可选模型问答及 stdio 隔离适配'],
 ['src/web_logging.py → src/logger.py','共享日志实例、错误脱敏及原有 Logger 复用']
];

function Narrative({id,text,className=''}){return <RichNarrative id={id} value={text} className={className} label="编辑报告文字"/>}
function BoundSection({id,queryId,title,text,children}){return <section id={id} className="brief-section"><ReportSection id={'report-'+id} queryId={queryId} title={title} showHeading={false}><Narrative id={id+':copy'} text={text}/>{children}</ReportSection></section>}

function Architecture({rows}){
 const [selected,setSelected]=useState(2);
 const detail=rows[selected];
 return <div className="architecture-graphic" data-reviewed-rows>
  
  <div className="architecture-scroll"><svg viewBox="0 0 1000 425" role="img" aria-label="实际架构：源数据经任务编排与本机分析引擎产生证据，证据进入工作台；可选外部模型只接收确认后的摘要。">
   <defs><marker id="flow-arrow" markerWidth="9" markerHeight="9" refX="8" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8" fill="#007bc0"/></marker></defs>
   <rect x="4" y="4" width="992" height="417" rx="12" fill="#f5f8fa"/>
   <rect x="30" y="164" width="180" height="162" rx="8" fill="white" stroke="#c2d5df"/><text x="50" y="196" className="node-title">数据源</text><text x="50" y="230">ClickHouse HTTP</text><text x="50" y="258">本地 CSV / XLSX</text><text x="50" y="291" className="node-note">所选时间与站点范围</text>
   <rect x="265" y="30" width="230" height="104" rx="8" fill="#e4f2fc" stroke="#007bc0"/><text x="285" y="63" className="node-title">任务编排</text><text x="285" y="92">Python API / 任务队列</text><text x="285" y="116" className="node-note">进度、取消、会话与日志</text>
   <rect x="265" y="164" width="230" height="197" rx="8" fill="white" stroke="#007bc0"/><text x="285" y="197" className="node-title">本机分析引擎</text><text x="285" y="230">批次规范化 → 磁盘统计</text><text x="285" y="258">周期 → 特征 → 模型</text><text x="285" y="290">Pandas / NumPy</text><text x="285" y="318">SQLite / scikit-learn</text><text x="285" y="344" className="node-note">全量统计，有界训练，全量有效推断</text>
   <rect x="550" y="164" width="175" height="197" rx="8" fill="white" stroke="#c2d5df"/><text x="570" y="197" className="node-title">已计算证据</text><text x="570" y="232">汇总结果 JSON</text><text x="570" y="261">周期特征与分数</text><text x="570" y="290">波形 SQLite</text><text x="570" y="325" className="node-note">明细保留本机</text>
   <rect x="780" y="30" width="193" height="104" rx="8" fill="#e5f4eb" stroke="#79a78c" strokeDasharray="5 3"/><text x="800" y="63" className="node-title">可选模型问答</text><text x="800" y="92">Codex stdio 适配</text><text x="800" y="116" className="node-note">仅问题 + 脱敏摘要</text>
   <rect x="780" y="194" width="193" height="167" rx="8" fill="white" stroke="#c2d5df"/><text x="800" y="227" className="node-title">Bosch 工作台</text><text x="800" y="259">统计 / 异常 / 状态</text><text x="800" y="287">本地问答 / 区间缩放</text><text x="800" y="325" className="node-note">工程人员查看与复核</text>
   <g stroke="#007bc0" strokeWidth="2" fill="none" markerEnd="url(#flow-arrow)"><path d="M210 260 H258"/><path d="M380 134 V157"/><path d="M495 260 H543"/><path d="M725 282 H773"/></g>
   <path d="M638 164 V82 H772" fill="none" stroke="#4a8f66" strokeWidth="2" strokeDasharray="6 4" markerEnd="url(#flow-arrow)"/>
   <text x="540" y="54" className="edge-note">用户明确确认后发送摘要</text>
   <path d="M876 134 V187" fill="none" stroke="#4a8f66" strokeWidth="2" strokeDasharray="6 4" markerEnd="url(#flow-arrow)"/>
   <text x="886" y="167" className="edge-note">解释</text>
   <text x="30" y="397" className="node-note">实线：当前分析与证据流　｜　虚线：可选模型解释路径　｜　图中无自动维护/控制执行路径</text>
  </svg></div>
  <div className="layer-buttons" aria-label="查看技术层职责">{rows.map((row,i)=><button type="button" key={row.layer} aria-pressed={selected===i} onClick={()=>setSelected(i)}>{row.layer}</button>)}</div>
  <div className="layer-detail" role="status"><strong>{detail.layer}层 · {detail.technology}</strong><span>{detail.role}</span></div>
 </div>
}

export function ReportContent(){
 const {snapshot,appTitle,canEdit,mode,setAppTitle,reviewedRows,visible}=useDataApp();
 const capabilities=reviewedRows('capabilities'),architecture=reviewedRows('architecture'),bench=reviewedRows('benchmark'),phases=reviewedRows('stage_timings'),sample=reviewedRows('sample');
 const capabilityColumns=[{field:'area',label:'分析层级'},{field:'servo',label:'伺服',renderCell:value=><span className="capability-cell">{value}</span>},{field:'cylinder',label:'气缸',renderCell:value=><span className="capability-cell">{value}</span>},{field:'implementation',label:'交付状态',renderCell:value=><span className="capability-cell">{value}</span>},{field:'boundary',label:'解释边界',renderCell:value=><span className="capability-cell">{value}</span>}];
 return <article className="report-content project-brief" aria-label="伺服与气缸分析 Agent 项目汇报">
  <header className="report-hero project-hero"><img className="project-supergraphic" src={supergraphic} alt=""/><div className="project-brand"><img src={logo} alt="BOSCH"/><span>设备运行分析 · 项目汇报</span></div>
   <h1 data-data-app-title contentEditable={canEdit&&mode==='edit'} suppressContentEditableWarning onBlur={canEdit&&mode==='edit'?e=>setAppTitle(e.currentTarget.textContent.trim()||appTitle):undefined}>{appTitle}</h1>
   <Narrative id="project:subtitle" text="覆盖数据接入、周期分析、异常筛查、状态识别与证据问答。"/>
  </header>
  {visible('report-summary')&&<ReportSection id="report-summary" queryId="capabilities" queryIds={['capabilities','sample','benchmark']} sourceRowsByQuery={{capabilities,sample,benchmark:bench}} title="项目概览" showHeading={false}><Narrative id="summary:copy" text={copy.executive}/></ReportSection>}
  <nav className="brief-contents" aria-label="报告目录">{sections.map(([id,label])=><a href={'#'+id} key={id}>{label}</a>)}</nav>
  <BoundSection id="purpose" queryId="capabilities" title="业务问题" text={copy.value}/>
  <BoundSection id="capabilities" queryId="capabilities" title="当前版本能力" text={copy.capability_intro}>
   <DataComponent id="capabilities-matrix" kind="table" queryId="capabilities" title="四层分析的实现与边界" sourceRows={capabilities} displayRows={capabilities}><DataTable rows={capabilities} columns={capabilityColumns} searchable={false} caption="伺服与气缸分析能力矩阵"/></DataComponent>
  </BoundSection>
  <BoundSection id="architecture" queryId="architecture" title="Agent 架构与数据流" text={copy.architecture_intro}>
   <DataComponent id="agent-architecture-diagram" kind="custom" queryId="architecture" title="当前代码对应的架构与数据流" sourceRows={architecture} displayRows={architecture}><Architecture rows={architecture}/></DataComponent>
   <Narrative id="workflow:copy" text={copy.workflow}/>
  </BoundSection>
  <BoundSection id="models" queryId="capabilities" title="模型与指标" text={copy.methods_intro}>
   <div className="model-briefs"><Narrative id="mad:copy" text={copy.mad}/><Narrative id="isolation:copy" text={copy.iforest}/><Narrative id="degradation:copy" text={copy.degradation}/><Narrative id="hmm:copy" text={copy.hmm}/><Narrative id="rul:copy" text={copy.rul}/></div>
  </BoundSection>
  <BoundSection id="engineering" queryId="architecture" title="大数据与工程实现" text={copy.engineering}/>
  <BoundSection id="performance" queryId="benchmark" title="性能优化观测" text={copy.performance}>
   <EvidenceChart id="performance-before-after" queryId="benchmark" title="同一样例 cProfile 总耗时（秒）" rows={bench} sourceRows={bench} spec={{type:'bar',x:'version',y:'seconds',yLabel:'秒',stackable:false}} height={300}/>
   <ReportSection id="stage-analysis" queryId="stage_timings" title="网页阶段耗时" showHeading={false}><Narrative id="stage:copy" text={copy.stage_note}/>
    <EvidenceChart id="stage-duration-chart" queryId="stage_timings" title="网页实际运行各阶段耗时（秒；总计 2.3 秒）" rows={phases} sourceRows={phases} spec={{type:'bar',x:'phase',y:'seconds',yLabel:'秒',stackable:false}} height={330}/>
   </ReportSection>
  </BoundSection>
  <BoundSection id="sample" queryId="sample" title="样例结果与边界" text={copy.sample_note}>
   <DataComponent id="sample-model-results" kind="table" queryId="sample" title="参考站点样例模型输出" sourceRows={sample} displayRows={sample}><DataTable rows={sample} searchable={false} caption="参考样例周期模型结果" columns={[{field:'设备',label:'设备'},{field:'完整周期',label:'完整周期'},{field:'IF异常周期',label:'IF 异常周期'},{field:'HMM已解码周期',label:'HMM 解码周期'},{field:'退化可计算周期',label:'退化有效周期'},{field:'mean_degradation',label:'平均退化指数'}]}/></DataComponent>
   <ReportDisclosure id="product-screens" label="展开查看当前工作台与 HMM 页面截图"><div className="screenshots"><figure><img src={performanceImage} alt="工作台样例分析完成页面，显示 10,000 条记录及 2.3 秒处理耗时"/><figcaption>当前工作台实际样例运行；仅代表该次 10k 行处理。</figcaption></figure><figure><img src={lifecycleImage} alt="伺服 HMM 阶段与半透明红色高危背景截图"/><figcaption>HMM 页面展示方式。截图红区为模型筛查区域，不是已验证的次品概率。</figcaption></figure></div></ReportDisclosure>
  </BoundSection>
  <BoundSection id="deployment" queryId="architecture" title="部署、数据边界与维护" text={copy.privacy}/>
  <section id="next" className="brief-section next-section"><Narrative id="roadmap:copy" text={copy.roadmap}/></section>
  <BoundSection id="evidence" queryId="architecture" title="证据与代码索引" text={copy.sources}>
   <ReportDisclosure id="implementation-files" label="展开技术模块与实现版本索引"><div className="module-index">{modules.map(([name,role])=><div key={name}><code>{name}</code><span>{role}</span></div>)}</div><div className="fingerprints" data-reviewed-rows>{snapshot.implementationEvidence?.map(row=><div key={row.file}><code>{row.file}</code><span>SHA-256 · {row.sha256.slice(0,16)}…</span></div>)}</div></ReportDisclosure>
  </BoundSection>

 </article>
}
