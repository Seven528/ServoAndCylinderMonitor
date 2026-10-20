import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const code=readFileSync(new URL('../web/voice-core.js',import.meta.url),'utf8');
const {createVoice}=await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
let starts=0,aborts=0,stops=0,last,states=[],texts=[],timers=[];
class Recognition{
 constructor(){this.processLocally=false;last=this;}
 start(){starts++;this.onstart?.();}
 stop(){stops++;this.onend?.();}
 abort(){aborts++;}
}
const make=(Type=Recognition)=>createVoice({Recognition:Type,onText:(text)=>texts.push(text),onState:(state)=>states.push(state),schedule:(fn,ms)=>{timers.push({fn,ms});return timers.length;},cancelTimer:()=>{}});
let voice=make();
assert.equal(voice.start({local:false,consent:false}),false);assert.equal(starts,0,'No remote capture before consent');
assert.equal(voice.start({local:true}),true);assert.equal(last.processLocally,true);assert.equal(starts,1);
assert.equal(voice.start({local:true}),false,'Never start overlapping microphone sessions');
let final=[{transcript:'分析气缸状态'}];final.isFinal=true;
last.onresult({results:[final]});assert.equal(texts.at(-1),'分析气缸状态');
const late=last.onresult;voice.cancel();assert.equal(voice.active,false);
late({results:[final]});assert.equal(texts.length,1,'Ignore late recognition results after cancel');
voice=make();voice.start({local:false,consent:true});assert.equal(last.processLocally,false);
voice.stop();assert.equal(voice.active,false);assert.equal(stops,1);
class NoLocal{start(){starts++;}abort(){aborts++;}}
voice=make(NoLocal);const before=starts;assert.equal(voice.start({local:true}),false);assert.equal(starts,before,'No implicit cloud fallback');
voice=make(undefined); // Default parameter restores the test recognizer.
voice.start({local:true});assert.ok(timers.some((timer)=>timer.ms===60000),'Capture is bounded at 60 seconds');voice.cancel();
console.log('Voice consent, local enforcement, stop/cancel and stale-result checks: passed');
