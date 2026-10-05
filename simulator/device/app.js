import createEngine from '../fx991sim.js';

const $ = id => document.getElementById(id);

// These are the 49 physical packets in the original normal-ROM key matrix.
// Printed SHIFT and ALPHA legends never submit an invented alternate packet.
const keys = [
 {label:'SHIFT',token:233,columns:128,rows:1},
 {label:'ALPHA',token:232,columns:128,rows:2},
 {label:'↑',token:224,columns:128,rows:4},
 {label:'←',token:227,columns:64,rows:4},
 {label:'→',token:226,columns:128,rows:8},
 {label:'↓',token:225,columns:64,rows:8},
 {label:'MODE',token:228,columns:128,rows:16},
 {label:'CALC',token:252,columns:64,rows:1},
 {label:'∫',token:221,columns:64,rows:2},
 {label:'x⁻¹',token:212,columns:64,rows:16},
 {label:'logₐ',token:219,columns:64,rows:32},
 {label:'□/□',token:208,columns:32,rows:1},
 {label:'√',token:211,columns:32,rows:2},
 {label:'x²',token:213,columns:32,rows:4},
 {label:'x^□',token:210,columns:32,rows:8},
 {label:'log',token:104,columns:32,rows:16},
 {label:'ln',token:163,columns:32,rows:32},
 {label:'(-)',token:96,columns:16,rows:1},
 {label:'°′″',token:246,columns:16,rows:2},
 {label:'hyp',token:9,columns:16,rows:4},
 {label:'sin',token:160,columns:16,rows:8},
 {label:'cos',token:161,columns:16,rows:16},
 {label:'tan',token:162,columns:16,rows:32},
 {label:'RCL',token:234,columns:8,rows:1},
 {label:'ENG',token:248,columns:8,rows:2},
 {label:'(',token:40,columns:8,rows:4},
 {label:')',token:41,columns:8,rows:8},
 {label:'S⇔D',token:250,columns:8,rows:16},
 {label:'M+',token:238,columns:8,rows:32},
 {label:'7',token:55,columns:4,rows:1},
 {label:'8',token:56,columns:4,rows:2},
 {label:'9',token:57,columns:4,rows:4},
 {label:'DEL',token:254,columns:4,rows:8},
 {label:'AC',token:230,columns:4,rows:16},
 {label:'4',token:52,columns:2,rows:1},
 {label:'5',token:53,columns:2,rows:2},
 {label:'6',token:54,columns:2,rows:4},
 {label:'×',token:78,columns:2,rows:8},
 {label:'÷',token:79,columns:2,rows:16},
 {label:'1',token:49,columns:1,rows:1},
 {label:'2',token:50,columns:1,rows:2},
 {label:'3',token:51,columns:1,rows:4},
 {label:'+',token:43,columns:1,rows:8},
 {label:'−',token:45,columns:1,rows:16},
 {label:'0',token:48,columns:16,rows:64},
 {label:'.',token:46,columns:8,rows:64},
 {label:'×10ˣ',token:116,columns:4,rows:64},
 {label:'Ans',token:139,columns:2,rows:64},
 {label:'=',token:240,columns:1,rows:64},
];

// Printed legends transcribed from the extracted Ver4 emulator face resource.
const legends = {
 228:{shift:'SETUP'},
 252:{shift:'SOLVE',alpha:'='},
 221:{shift:'d/dx',alpha:':'},
 212:{shift:'x!'},
 219:{shift:'Σ',alpha:'Π'},
 208:{shift:'a b/c',alpha:'÷R'},
 211:{shift:'∛',alpha:'x̅'},
 213:{shift:'x³',base:'DEC'},
 210:{shift:'ⁿ√',base:'HEX'},
 104:{shift:'10ˣ',base:'BIN'},
 163:{shift:'eˣ',base:'OCT'},
 96:{shift:'∠',alpha:'A'},
 246:{shift:'FACT',alpha:'B'},
 9:{shift:'Abs',alpha:'C'},
 160:{shift:'sin⁻¹',alpha:'D'},
 161:{shift:'cos⁻¹',alpha:'E'},
 162:{shift:'tan⁻¹',alpha:'F'},
 234:{shift:'STO'},
 248:{shift:'←',alpha:'i'},
 40:{shift:'%'},
 41:{shift:',',alpha:'X'},
 250:{shift:'a b/c⇔d/c',alpha:'Y'},
 238:{shift:'M−',alpha:'M'},
 55:{shift:'CONST'},
 56:{shift:'CONV'},
 57:{shift:'CLR'},
 254:{shift:'INS'},
 230:{shift:'OFF'},
 52:{shift:'MATRIX'},
 53:{shift:'VECTOR'},
 54:{shift:'VERIFY'},
 78:{shift:'nPr',alpha:'GCD'},
 79:{shift:'nCr',alpha:'LCM'},
 49:{shift:'STAT/DIST'},
 50:{shift:'CMPLX'},
 51:{shift:'BASE'},
 43:{shift:'Pol',alpha:'Int'},
 45:{shift:'Rec',alpha:'Intg'},
 48:{shift:'Rnd'},
 46:{shift:'Ran#',alpha:'RanInt'},
 116:{shift:'π',alpha:'e'},
 139:{shift:'DRG▶',alpha:'PreAns'},
};

const controls = ['create','reset','step','release','timer','callback'];
const keyByToken = new Map(keys.map(key => [key.token,key]));
// Original calculator geometry, measured against the 405 × 816 reference.
const keyPositions = new Map([
 [233,[41,294,48,37]], [232,[95,303,48,37]], [228,[265,303,48,37]],
 [224,[188,299,30,28]], [227,[156,323,30,34]],
 [226,[221,323,30,34]], [225,[188,353,30,28]],
 [252,[38,366,51,29]], [221,[92,366,51,29]],
 [212,[263,366,51,29]], [219,[316,366,49,29]],
]);
for (const [tokens,top] of [
 [[208,211,213,210,104,163],412],
 [[96,246,9,160,161,162],459],
 [[234,248,40,41,250,238],506],
]) {
 tokens.forEach((token,index) => keyPositions.set(token,[[43,97,152,206,261,315][index],top,49,29]));
}
for (const [tokens,top] of [
 [[55,56,57,254,230],551],
 [[52,53,54,78,79],608],
 [[49,50,51,43,45],664],
 [[48,46,116,139,240],722],
]) {
 tokens.forEach((token,index) => keyPositions.set(token,[43+65*index,top,60,40]));
}
const keyButtons = [];
const buttonByToken = new Map();
const pressedButtons = new Set();
const keyboardPresses = new Map();
let engine = null, handle = 0, state = null, held = null, busy = false;
let actionTail = Promise.resolve(), pendingActions = 0;
const trace = [];

function unsigned(value,max=0xffffffff) {
 if (!Number.isSafeInteger(value) || value < 0 || value > max) {
  throw new Error('Enter a whole unsigned value from 0 to '+max+'.');
 }
 return value;
}

function observe() {
 const pointer = engine._fx_device_browser_snapshot(handle);
 if (!pointer) throw new Error('C device observation failed.');
 try { state = JSON.parse(engine.UTF8ToString(pointer)); }
 finally { engine._fx_device_browser_snapshot_free(pointer); }
 const c = $('lcd').getContext('2d');
 c.fillStyle = '#c0cbb3';
 c.fillRect(0,0,96,32);
 const bytes = state.framebuffer.match(/../g).map(h => parseInt(h,16));
 c.fillStyle = '#21362c';
 for (let y=0;y<32;y++) {
  for (let x=0;x<96;x++) {
   if (bytes[y*12+(x>>3)] & (0x80>>(x&7))) c.fillRect(x,y,1,1);
  }
 }
 $('status').textContent = state.status;
 $('packet').textContent = 'Raw packet '+state.key_columns.toString(16).padStart(2,'0')+
  ' / '+state.key_rows.toString(16).padStart(2,'0')+
  (state.key_columns || state.key_rows ? ' · held' : ' · released');
 const r = state.request;
 $('detail').textContent = r.kind ?
  'Pending request '+r.kind+' · operation '+r.operation+' · page '+r.page+' · status '+r.status :
  'Controller '+state.phase+' · event '+state.event+' · steps '+state.steps;
 $('observation').textContent = JSON.stringify(state,null,2);
 $('timer').disabled = busy || !state.timer_pending;
 for (const b of keyButtons) {
  b.classList.toggle('held',!!(state.key_columns || state.key_rows) &&
   b.dataset.packet === state.key_columns+','+state.key_rows);
 }
}

function setBusy(value) {
 busy = value;
 controls.forEach(id => $(id).disabled = value);
 // Physical taps can be queued while a previous bounded C gesture finishes.
 for (const b of keyButtons) b.disabled = !engine || !handle;
 $('variant').disabled = value;
 $('autotimer').disabled = value;
 $('autopress').disabled = value;
 if (!value) $('timer').disabled = !state?.timer_pending;
}

function action(fn) {
 if (!engine || !handle) return Promise.resolve();
 pendingActions++;
 setBusy(true);
 const next = actionTail.then(async () => {
  $('error').textContent = '';
  try {
   if (!handle) return;
   await fn();
   if (handle) observe();
  } catch (error) {
   $('error').textContent = error.message;
  } finally {
   pendingActions--;
   if (!pendingActions) setBusy(false);
  }
 });
 actionTail = next.catch(() => {});
 return next;
}

function record(operation,args,result) {
 observe();
 const actual = {operation,args,result,snapshot:structuredClone(state)};
 document.dispatchEvent(new CustomEvent('fxsim:device-operation',{detail:actual}));
 trace.push(actual);
 if (trace.length > 128) trace.shift();
 $('scheduler-log').textContent = JSON.stringify(trace,null,2);
}

function invoke(method,...args) {
 const result = engine['_fx_device_browser_'+method](handle,...args);
 record(method,args,result);
 return result;
}

const frame = () => new Promise(resolve => requestAnimationFrame(resolve));
async function settle(stage) {
 let timers = 0;
 for (let count=0;count<40;count++) {
  observe();
  if (state.request.kind || ['request','invalid','reset','export'].includes(state.status)) return state.status;
  if (state.timer_pending) {
   if (stage === 'held' || !$('autotimer').checked) return 'timer';
   if (timers === 8) return 'timer-limit';
   await frame();
   if (!state.timer_pending) throw new Error('Pending timer changed before acknowledgment.');
   invoke('ack_timer');
   timers++;
  } else {
   await frame();
   invoke('step',0);
  }
  if (stage === 'held' && state.event === 5) return 'cycle-return';
  if (['wait','request','invalid','reset','export'].includes(state.status)) return state.status;
  if (stage === 'held' && state.timer_pending) return 'timer';
 }
 return 'step-limit';
}

async function boot() {
 held = null;
 invoke('reset');
 const first = await settle('held');
 invoke('release');
 const second = await settle('released');
 invoke('take_callback');
 $('scheduler-status').textContent = 'Reset: '+first+' → '+second+'.';
}

async function press(key) {
 let first = 'not-started', second = 'not-started';
 if (invoke('submit_pair',unsigned(key.columns,255),unsigned(key.rows,255)) !== 0) {
  throw new Error('C rejected the raw packet.');
 }
 held = key;
 try { first = await settle('held'); }
 finally {
  invoke('release');
  held = null;
 }
 second = await settle('released');
 invoke('take_callback');
 $('scheduler-status').textContent = key.label+': '+first+' → '+second+'.';
 if (first.endsWith('limit') || second.endsWith('limit')) {
  throw new Error('Bounded phase limit reached. Use the explicit controls or reset.');
 }
}

function activate(key) {
 return action(() => {
  if ($('autopress').checked) return press(key);
  const result = invoke('submit_pair',unsigned(key.columns,255),unsigned(key.rows,255));
  if (result !== 0) throw new Error('C rejected the raw packet.');
  held = key;
 });
}

function create() {
 if (!$('variant').value.trim()) throw new Error('Enter a variant from 0 to 255.');
 const variant = unsigned(Number($('variant').value),255);
 const next = engine._fx_device_browser_create(variant);
 if (!next) throw new Error('Device allocation failed.');
 if (handle) engine._fx_device_browser_destroy(handle);
 handle = next;
 held = null;
 trace.length = 0;
 record('create',[variant],null);
}

function markPressed(button,value) {
 if (value) pressedButtons.add(button);
 else pressedButtons.delete(button);
 button.classList.toggle('pressed',value);
}

function keyCell(token,extraClass='') {
 const key = keyByToken.get(token);
 const cell = document.createElement('div');
 cell.className = 'key-cell key-token-'+token+(extraClass ? ' '+extraClass : '');
 const printed = document.createElement('div');
 printed.className = 'key-legends';
 printed.setAttribute('aria-hidden','true');
 if ([233,232,228].includes(token)) {
  const primary = document.createElement('span');
  primary.className = token === 233 ? 'shift-legend' : token === 232 ? 'alpha-legend' : 'primary-legend';
  primary.textContent = key.label;
  printed.append(primary);
 }
 for (const [kind,label] of Object.entries(legends[token] || {})) {
  const span = document.createElement('span');
  span.className = kind+'-legend';
  span.textContent = label;
  printed.append(span);
 }
 const b = document.createElement('button');
 b.type = 'button';
 b.textContent = key.label;
 b.className = 'calc-key '+(key.label === 'AC' ? 'ac' : key.label === 'DEL' ? 'delete' :
  key.label === 'SHIFT' ? 'shift' : key.label === 'ALPHA' ? 'alpha' :
  token >= 224 && token <= 227 ? 'replay-key' : token >= 128 ? 'function' : 'number');
 b.dataset.packet = key.columns+','+key.rows;
 b.dataset.token = String(token);
 b.title = 'Raw columns '+key.columns+' / rows '+key.rows;
 const [left,top,width,height] = keyPositions.get(token);
 for (const element of [cell,b]) {
  element.style.setProperty('--key-left',(left/405*100)+'%');
  element.style.setProperty('--key-top',(top/816*100)+'%');
  element.style.setProperty('--key-width',(width/405*100)+'%');
  element.style.setProperty('--key-height',(height/816*100)+'%');
 }
 b.onclick = () => activate(key);
 b.addEventListener('pointerdown',event => {
  if (event.button !== 0 || b.disabled) return;
  markPressed(b,true);
 });
 b.addEventListener('pointerup',() => markPressed(b,false));
 b.addEventListener('pointercancel',() => markPressed(b,false));
 b.addEventListener('pointerleave',() => markPressed(b,false));
 b.disabled = true;
 keyButtons.push(b);
 buttonByToken.set(token,b);
 cell.append(printed,b);
 return cell;
}

function appendRow(tokens,className) {
 const row = document.createElement('div');
 row.className = 'key-row '+className;
 tokens.forEach(token => row.append(keyCell(token)));
 $('keypad').append(row);
 return row;
}

const controlRow = document.createElement('div');
controlRow.className = 'key-row control-row';
controlRow.append(keyCell(233),keyCell(232));
const replay = document.createElement('div');
replay.className = 'replay-control';
const replayLabel = document.createElement('span');
replayLabel.className = 'replay-label';
replayLabel.textContent = 'REPLAY';
replayLabel.setAttribute('aria-hidden','true');
replay.append(replayLabel);
for (const [token,direction] of [[224,'up'],[227,'left'],[226,'right'],[225,'down']]) {
 replay.append(keyCell(token,'replay-'+direction));
}
controlRow.append(replay,keyCell(228));
$('keypad').append(controlRow);
appendRow([252,221,212,219],'scientific-top-row');
appendRow([208,211,213,210,104,163],'scientific-row');
appendRow([96,246,9,160,161,162],'scientific-row');
appendRow([234,248,40,41,250,238],'scientific-row');
appendRow([55,56,57,254,230],'numeric-row');
appendRow([52,53,54,78,79],'numeric-row');
appendRow([49,50,51,43,45],'numeric-row');
appendRow([48,46,116,139,240],'numeric-row');

$('create').onclick = () => action(async () => { create(); if ($('autopress').checked) await boot(); });
$('reset').onclick = () => action(() => $('autopress').checked ? boot() : invoke('reset'));
$('step').onclick = () => action(() => invoke('step',0));
$('release').onclick = () => action(() => { invoke('release'); held = null; });
$('timer').onclick = () => action(() => invoke('ack_timer'));
$('callback').onclick = () => action(() => { $('error').textContent = 'Drained callback '+invoke('take_callback')+'.'; });

const keyboardTokens = new Map([
 ['.',46],['+',43],['-',45],['*',78],['/',79],['(',40],[')',41],['=',240],['Enter',240],
 ['ArrowUp',224],['ArrowLeft',227],['ArrowRight',226],['ArrowDown',225],
 ['Backspace',254],['Delete',254],['Escape',230],['F1',233],['F2',232],['F3',228],['F4',252],
 ...Array.from({length:10},(_,digit) => [String(digit),48+digit]),
]);

function editingControl(target) {
 return target instanceof Element && !!target.closest(
  'input,textarea,select,[contenteditable]:not([contenteditable="false"]),#advanced-controls'
 );
}

document.addEventListener('keydown',event => {
 if (event.altKey || event.ctrlKey || event.metaKey || editingControl(event.target)) return;
 const token = keyboardTokens.get(event.key);
 if (token === undefined && event.key !== 'Home') return;
 event.preventDefault();
 if (event.repeat || !engine || !handle) return;
 if (event.key === 'Home') {
  markPressed($('reset'),true);
  keyboardPresses.set(event.code || event.key,$('reset'));
  action(() => $('autopress').checked ? boot() : invoke('reset'));
 } else {
  const b = buttonByToken.get(token);
  markPressed(b,true);
  keyboardPresses.set(event.code || event.key,b);
  activate(keyByToken.get(token));
 }
});
document.addEventListener('keyup',event => {
 const code = event.code || event.key;
 const b = keyboardPresses.get(code);
 if (b) { markPressed(b,false); keyboardPresses.delete(code); }
});

function clearPresses() {
 for (const b of pressedButtons) b.classList.remove('pressed');
 pressedButtons.clear();
 keyboardPresses.clear();
 // Manual debugging can hold a packet. Losing focus always releases it.
 if (held && !$('autopress').checked) {
  action(() => { invoke('release'); held = null; });
 }
}
window.addEventListener('blur',clearPresses);
document.addEventListener('visibilitychange',() => { if (document.hidden) clearPresses(); });

setBusy(true);
try {
 engine = await createEngine();
 if (typeof engine._fx_device_browser_create !== 'function') {
  throw new Error('This build does not export the device bridge yet.');
 }
 create();
 if ($('autopress').checked) await boot();
 observe();
 setBusy(false);
} catch (error) {
 $('status').textContent = 'Engine unavailable';
 $('error').textContent = error.message;
}
$('autopress').addEventListener('change',() => {
 $('key-legend').textContent = $('autopress').checked ?
  'Each click is one bounded press and release.' : 'Manual mode: a key stays held until Release.';
});
window.addEventListener('pagehide',event => {
 if (!event.persisted && engine && handle) {
  engine._fx_device_browser_destroy(handle);
  handle = 0;
 }
});
window.addEventListener('pageshow',event => { if (event.persisted && engine && handle) observe(); });
