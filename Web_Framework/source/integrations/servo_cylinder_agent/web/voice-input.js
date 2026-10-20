import {createVoice} from './voice-core.js';
export function setupVoice(onActivity=()=>{}) {
  const $=(id)=>document.getElementById(id), input=$('question'), button=$('voice-toggle'), dialog=$('voice-dialog');
  const Recognition=window.SpeechRecognition||window.webkitSpeechRecognition;
  const localSupported=typeof Recognition==='function' && 'processLocally' in Recognition.prototype;
  let prefix='',suffix='',busy=false,wasReadOnly=false,checking=0;
  const voice=createVoice({Recognition,onText(text){
    const room=Math.max(0,1000-prefix.length-suffix.length);
    input.value=prefix+text.slice(0,room)+suffix;
    input.dispatchEvent(new Event('input',{bubbles:true}));
  },onState(state){
    busy=['starting','listening','stopping'].includes(state.phase);
    input.readOnly=busy||wasReadOnly;
    button.setAttribute('aria-pressed',String(busy));
    button.setAttribute('aria-label',busy?'停止听写':'语音输入');
    $('voice-status').textContent=state.message;
    $('voice-status').hidden=!state.message;
    $('voice-status').classList.toggle('error',state.phase==='error');
    onActivity(busy);
  }});
  $('voice-local-option').disabled=!localSupported;
  $('voice-mode').value=localSupported?'local':'browser';
  async function reflect() {
    const id=++checking, local=$('voice-mode').value==='local';
    $('voice-remote-consent-row').hidden=local;
    $('voice-install').hidden=true;
    $('voice-start').disabled=typeof Recognition!=='function'||(!local&&!$('voice-remote-consent').checked);
    if(typeof Recognition!=='function'){
      $('voice-description').textContent='当前浏览器未开放语音识别。可在 Chrome/Edge 中打开本页，或点击输入框后使用系统听写（Windows：Win+H；Mac：系统听写快捷键）。';return;
    }
    $('voice-description').textContent=local?'本机识别中文，最长 60 秒。转写只填入输入框，不会自动发送。':'浏览器可能将音频发送给其语音服务；不会自动发送转写文字。';
    if(local && typeof Recognition.available==='function'){
      $('voice-start').disabled=true;
      try{
        const state=await Recognition.available({langs:['zh-CN'],processLocally:true});
        if(id!==checking||!dialog.open)return;
        $('voice-start').disabled=state!=='available';
        $('voice-install').hidden=!['downloadable','downloading'].includes(state)||typeof Recognition.install!=='function';
        if(state!=='available')$('voice-description').textContent='本机中文语音包尚未就绪。可以下载支持的语言包，或明确选择浏览器语音服务。';
      }catch{$('voice-description').textContent='无法确认离线语言包状态。请检查浏览器设置，或使用系统听写。';}
    }
  }
  button.addEventListener('click',()=>{
    if(voice.active){voice.stop();return;}
    dialog.showModal();void reflect();
  });
  $('voice-mode').addEventListener('change',()=>{$('voice-remote-consent').checked=false;void reflect();});
  $('voice-remote-consent').addEventListener('change',()=>void reflect());
  $('voice-close').addEventListener('click',()=>{checking++;dialog.close();input.focus();});
  $('voice-install').addEventListener('click',async()=>{
    $('voice-install').disabled=true;
    try{
      $('voice-description').textContent='正在下载浏览器中文语言包，尚未录音…';
      const ready=await Recognition.install({langs:['zh-CN']});
      if(!ready)$('voice-description').textContent='语言包未准备成功，请检查浏览器设置。';
      else await reflect();
    }catch{$('voice-description').textContent='无法安装语言包，请检查浏览器支持情况。';}
    finally{$('voice-install').disabled=false;}
  });
  $('voice-start').addEventListener('click',()=>{
    if($('voice-start').disabled)return;
    prefix=input.value.slice(0,input.selectionStart);suffix=input.value.slice(input.selectionEnd);wasReadOnly=input.readOnly;
    dialog.close();voice.start({local:$('voice-mode').value==='local',consent:$('voice-remote-consent').checked});
  });
  const observer=new MutationObserver(()=>{if($('chat-panel').dataset.presentation==='hidden')voice.cancel();});
  observer.observe($('chat-panel'),{attributes:true,attributeFilter:['data-presentation']});
  document.addEventListener('visibilitychange',()=>{if(document.hidden)voice.cancel();});
  document.addEventListener('keydown',(event)=>{if(event.key==='Escape'&&voice.active){event.preventDefault();event.stopImmediatePropagation();voice.cancel();}},{capture:true});
  window.addEventListener('pagehide',()=>{voice.cancel();observer.disconnect();});
  return {cancel:()=>voice.cancel(),get active(){return voice.active;}};
}
