import createEngine from '../fx991sim.js';
const $=id=>document.getElementById(id);
const keys=[{"label": "SHIFT", "token": 233, "columns": 128, "rows": 1}, {"label": "MODE", "token": 228, "columns": 128, "rows": 16}, {"label": "←", "token": 227, "columns": 64, "rows": 4}, {"label": "↑", "token": 224, "columns": 128, "rows": 4}, {"label": "↓", "token": 226, "columns": 128, "rows": 8}, {"label": "7", "token": 55, "columns": 4, "rows": 1}, {"label": "8", "token": 56, "columns": 4, "rows": 2}, {"label": "9", "token": 57, "columns": 4, "rows": 4}, {"label": "DEL", "token": 254, "columns": 4, "rows": 8}, {"label": "AC", "token": 230, "columns": 4, "rows": 16}, {"label": "4", "token": 52, "columns": 2, "rows": 1}, {"label": "5", "token": 53, "columns": 2, "rows": 2}, {"label": "6", "token": 54, "columns": 2, "rows": 4}, {"label": "×", "token": 78, "columns": 2, "rows": 8}, {"label": "÷", "token": 79, "columns": 2, "rows": 16}, {"label": "1", "token": 49, "columns": 1, "rows": 1}, {"label": "2", "token": 50, "columns": 1, "rows": 2}, {"label": "3", "token": 51, "columns": 1, "rows": 4}, {"label": "+", "token": 43, "columns": 1, "rows": 8}, {"label": "−", "token": 45, "columns": 1, "rows": 16}, {"label": "0", "token": 48, "columns": 16, "rows": 64}, {"label": ".", "token": 46, "columns": 8, "rows": 64}, {"label": "Ans", "token": 139, "columns": 2, "rows": 64}, {"label": "→", "token": 225, "columns": 64, "rows": 8}, {"label": "=", "token": 240, "columns": 1, "rows": 64}];
const controls=['create','reset','step','release','timer','callback'];
let engine=null,handle=0,state=null,held=null,busy=false;
const trace=[];
function unsigned(value,max=0xffffffff){
 if(!Number.isSafeInteger(value)||value<0||value>max)throw new Error('Enter a whole unsigned value from 0 to '+max+'.');
 return value;
}
function observe(){
 const pointer=engine._fx_device_browser_snapshot(handle);
 if(!pointer)throw new Error('C device observation failed.');
 try{state=JSON.parse(engine.UTF8ToString(pointer));}
 finally{engine._fx_device_browser_snapshot_free(pointer);}
 const c=$('lcd').getContext('2d');c.fillStyle='#c0cbb3';c.fillRect(0,0,96,32);
 const bytes=state.framebuffer.match(/../g).map(h=>parseInt(h,16));c.fillStyle='#21362c';
 for(let y=0;y<32;y++)for(let x=0;x<96;x++)if(bytes[y*12+(x>>3)]&(0x80>>(x&7)))c.fillRect(x,y,1,1);
 $('status').textContent=state.status;
 $('packet').textContent='Raw packet '+state.key_columns.toString(16).padStart(2,'0')+' / '+state.key_rows.toString(16).padStart(2,'0')+(state.key_columns||state.key_rows?' · held':' · released');
 const r=state.request;
 $('detail').textContent=r.kind?'Pending request '+r.kind+' · operation '+r.operation+' · page '+r.page+' · status '+r.status:'Controller '+state.phase+' · event '+state.event+' · steps '+state.steps;
 $('observation').textContent=JSON.stringify(state,null,2);$('timer').disabled=busy||!state.timer_pending;
 for(const b of $('keypad').children)b.classList.toggle('held',!!(state.key_columns||state.key_rows)&&b.dataset.packet===state.key_columns+','+state.key_rows);
}
function setBusy(value){
 busy=value;
 controls.forEach(id=>$(id).disabled=value);
 for(const b of $('keypad').children)b.disabled=value;
 $('variant').disabled=value;$('autotimer').disabled=value;$('autopress').disabled=value;
 if(!value)$('timer').disabled=!state?.timer_pending;
}
async function action(fn){
 if(busy)return;
 setBusy(true);$('error').textContent='';
 try{await fn();observe();}
 catch(error){$('error').textContent=error.message;}
 finally{setBusy(false);}
}
function record(operation,args,result){
 observe();
 const actual={operation,args,result,snapshot:structuredClone(state)};
 document.dispatchEvent(new CustomEvent('fxsim:device-operation',{detail:actual}));
 trace.push(actual);if(trace.length>128)trace.shift();
 $('scheduler-log').textContent=JSON.stringify(trace,null,2);
}
function invoke(method,...args){
 const result=engine['_fx_device_browser_'+method](handle,...args);
 record(method,args,result);return result;
}
const frame=()=>new Promise(resolve=>requestAnimationFrame(resolve));
async function settle(stage){
 let timers=0;
 for(let count=0;count<40;count++){
  observe();
  if(state.request.kind||['request','invalid','reset','export'].includes(state.status))return state.status;
  if(state.timer_pending){
   if(stage==='held'||!$('autotimer').checked)return 'timer';
   if(timers===8)return 'timer-limit';
   await frame();
   if(!state.timer_pending)throw new Error('Pending timer changed before acknowledgment.');
   invoke('ack_timer');timers++;
  }else{await frame();invoke('step',0);}
  if(stage==='held'&&state.event===5)return 'cycle-return';
  if(['wait','request','invalid','reset','export'].includes(state.status))return state.status;
  if(stage==='held'&&state.timer_pending)return 'timer';
 }
 return 'step-limit';
}
async function boot(){
 invoke('reset');
 const first=await settle('held');invoke('release');
 const second=await settle('released');invoke('take_callback');
 $('scheduler-status').textContent='Reset: '+first+' → '+second+'.';
}
async function press(key){
 let first='not-started',second='not-started';
 if(invoke('submit_pair',unsigned(key.columns,255),unsigned(key.rows,255))!==0)throw new Error('C rejected the raw packet.');
 try{first=await settle('held');}
 finally{invoke('release');}
 second=await settle('released');invoke('take_callback');
 $('scheduler-status').textContent=key.label+': '+first+' → '+second+'.';
 if(first.endsWith('limit')||second.endsWith('limit'))throw new Error('Bounded phase limit reached. Use the explicit controls or reset.');
}

function create(){
 if(!$('variant').value.trim())throw new Error('Enter a variant from 0 to 255.');
 const variant=unsigned(Number($('variant').value),255),next=engine._fx_device_browser_create(variant);
 if(!next)throw new Error('Device allocation failed.');
 if(handle)engine._fx_device_browser_destroy(handle);handle=next;held=null;trace.length=0;record('create',[variant],null);
}
for(const key of keys){
 const b=document.createElement('button');b.textContent=key.label;
 b.className=key.label==='AC'?'ac':key.token>=128?'function':'';
 b.dataset.packet=key.columns+','+key.rows;b.title='Raw columns '+key.columns+' / rows '+key.rows;
 b.onclick=()=>action(()=>$('autopress').checked?press(key):invoke('submit_pair',unsigned(key.columns,255),unsigned(key.rows,255)));
 b.disabled=true;$('keypad').append(b);
}
$('create').onclick=()=>action(async()=>{create();if($('autopress').checked)await boot();});
$('reset').onclick=()=>action(()=>$('autopress').checked?boot():invoke('reset'));
$('step').onclick=()=>action(()=>invoke('step',0));
$('release').onclick=()=>action(()=>{invoke('release');held=null;});
$('timer').onclick=()=>action(()=>invoke('ack_timer'));
$('callback').onclick=()=>action(()=>{$('error').textContent='Drained callback '+invoke('take_callback')+'.';});
setBusy(true);
try{
 engine=await createEngine();
 if(typeof engine._fx_device_browser_create!=='function')throw new Error('This build does not export the device bridge yet.');
 create();if($('autopress').checked)await boot();observe();setBusy(false);
}catch(error){$('status').textContent='Engine unavailable';$('error').textContent=error.message;}
$('autopress').addEventListener('change',()=>{$('key-legend').textContent=$('autopress').checked?'Each click is one bounded press and release.':'Manual mode: a key stays held until Release.';});
window.addEventListener('pagehide',event=>{if(!event.persisted&&engine&&handle){engine._fx_device_browser_destroy(handle);handle=0;}});
window.addEventListener('pageshow',event=>{if(event.persisted&&engine&&handle)observe();});
