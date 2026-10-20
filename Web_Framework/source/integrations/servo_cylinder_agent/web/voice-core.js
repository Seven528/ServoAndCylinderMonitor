// No recording starts until a user gesture; cloud-capable mode requires explicit consent.
export function createVoice({Recognition,onText,onState,schedule=setTimeout,cancelTimer=clearTimeout}) {
  let current=null, generation=0, timer=null, drain=null, active=false;
  const clearTimers=()=>{cancelTimer(timer);cancelTimer(drain);timer=drain=null;};
  function finish(message='',error=false) {
    const old=current;current=null;active=false;clearTimers();
    if(old) old.onstart=old.onresult=old.onerror=old.onend=null;
    onState({phase:error?'error':'idle',message});
    return old;
  }
  function stop() {
    if(!current || drain!==null)return;
    onState({phase:'stopping',message:'正在结束听写…'});
    try{current.stop();}catch{finish();return;}
    if(active)drain=schedule(()=>finish()?.abort(),3000);
  }
  return {
    get active(){return active;},
    start({local=true,consent=false}={}) {
      if(active)return false;
      if(typeof Recognition!=='function'){onState({phase:'error',message:'此浏览器不支持语音识别，可在输入框使用系统听写。'});return false;}
      if(!local && consent!==true){onState({phase:'error',message:'请先确认使用可能联网的浏览器语音服务。'});return false;}
      const version=++generation;
      try{
        const speech=new Recognition();
        if(local && !('processLocally' in speech))throw new Error('no local speech support');
        if('processLocally' in speech)speech.processLocally=local;
        if(local && speech.processLocally!==true)throw new Error('local processing unavailable');
        speech.lang='zh-CN';speech.continuous=true;speech.interimResults=true;speech.maxAlternatives=1;
        current=speech;active=true;
        const live=()=>current===speech && generation===version;
        speech.onstart=()=>{if(live())onState({phase:'listening',message:'正在听写，再点麦克风停止。'});};
        speech.onresult=(event)=>{
          if(!live())return;
          let final='',interim='';
          for(let i=0;i<event.results.length;i++){
            const row=event.results[i];
            if(row.isFinal)final+=row[0]?.transcript||'';else interim+=row[0]?.transcript||'';
          }
          onText(final.slice(0,1000));
          onState({phase:'listening',message:interim?'听写中：'+interim.slice(0,60):'正在听写，再点麦克风停止。'});
          if(final.length>=1000)stop();
        };
        speech.onerror=(event)=>{
          if(!live())return;
          const messages={'not-allowed':'未获得麦克风权限，请在浏览器中允许后重试。','service-not-allowed':'浏览器没有开放语音服务，请使用系统听写。','audio-capture':'麦克风不可用。','no-speech':'未识别到语音，请重试。','network':'浏览器语音服务连接失败。','language-not-supported':'中文语言包不可用，请检查听写设置。'};
          finish(messages[event.error]||'听写失败，请重试。',true)?.abort();
        };
        speech.onend=()=>{if(live())finish();};
        onState({phase:'starting',message:'正在请求麦克风权限…'});
        timer=schedule(stop,60000);speech.start();return true;
      }catch{finish('当前模式无法启动听写，请检查浏览器或中文语言包。',true)?.abort();return false;}
    },
    stop,
    cancel(){generation++;finish()?.abort();},
  };
}
