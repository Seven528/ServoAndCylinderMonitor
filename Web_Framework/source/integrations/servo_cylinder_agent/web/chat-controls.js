export function setupChatControls({api,pollJob,onChange=()=>{}}) {
  const $=(id)=>document.getElementById(id);
  let models=[{id:'local-statistical-v1',name:'本地统计问答',efforts:[],speeds:[],remote:false}],busy=false;
  function render() {
    const selected=models.find((item)=>item.id===$('answer-model').value)||models[0];
    $('model-current-label').textContent=selected.name;
    $('model-current-label').title=selected.name;
    $('model-options').hidden=!selected.remote;
    $('model-consent-row').hidden=!selected.remote;
    $('answer-model').disabled=busy;$('model-effort').disabled=busy;$('model-speed').disabled=busy;
    $('voice-toggle').disabled=busy;
  }
  function optionsForModel() {
    const model=models.find((item)=>item.id===$('answer-model').value)||models[0];
    $('model-effort').replaceChildren(...model.efforts.map((value)=>new Option(({low:'低',medium:'中',high:'高',xhigh:'更高',max:'最大',ultra:'Ultra',none:'无',minimal:'最少'})[value]||value,value)));
    if(model.default_effort)$('model-effort').value=model.default_effort;
    $('model-speed').replaceChildren(...model.speeds.map((item)=>new Option(item.name,item.id)));
    $('model-consent').checked=false;
    render();onChange();
  }
  function update(catalog) {
    const previous=$('answer-model').value;
    models=catalog.models;
    $('answer-model').replaceChildren(...models.map((item)=>new Option(item.name,item.id)));
    $('answer-model').value=models.some((item)=>item.id===previous)?previous:models[0].id;
    $('model-status').textContent=catalog.connected?`Codex 已连接 · ${models.length-1} 个模型；按账号实际可用性调用。`:catalog.message||'本地统计问答无需连接。连接 Codex 后可选择大模型。';
    optionsForModel();
  }
  $('answer-model').addEventListener('change',optionsForModel);
  $('connect-models').addEventListener('click',async()=>{
    $('connect-models').disabled=true;$('model-status').textContent='正在连接本机 Codex…';
    try{
      const job=await api('/api/models/connect',{method:'POST',body:'{}'});
      update(await pollJob(job.job_id,(message)=>{$('model-status').textContent=message;}));
    }catch(error){$('model-status').textContent=error.message;}
    finally{$('connect-models').disabled=false;}
  });
  document.addEventListener('click',(event)=>{if(!$('model-menu').contains(event.target))$('model-menu').open=false;});
  $('model-menu').addEventListener('keydown',(event)=>{if(event.key==='Escape'){
    event.preventDefault();event.stopPropagation();$('model-menu').open=false;$('model-menu').querySelector('summary').focus();
  }});
  $('question').addEventListener('keydown',(event)=>{
    if(event.key==='Enter'&&(event.ctrlKey||event.metaKey)&&!event.isComposing){event.preventDefault();if(!$('ask-submit').disabled)$('ask-form').requestSubmit();}
  });
  optionsForModel();
  return {
    initialize:async()=>update(await api('/api/models')),
    setBusy(value){busy=value;render();$('connect-models').disabled=value;},
    get busy(){return busy;},
    request(){
      const model=models.find((item)=>item.id===$('answer-model').value);
      if(!model)throw new Error('请选择有效模型。');
      if(model.remote&&!$('model-consent').checked)throw new Error('请先确认将本次问题和分析汇总发送至所选模型。');
      return {settings:{model:model.id,effort:model.remote?$('model-effort').value:null,speed:model.remote?$('model-speed').value:null},consent:model.remote&&$('model-consent').checked};
    },
  };
}
