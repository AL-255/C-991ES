import fs from 'node:fs';
import {pathToFileURL} from 'node:url';
const {default:createModule}=await import(pathToFileURL(process.argv[4]).href);
const input=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const module=await createModule();
function snapshot(handle) {
 const pointer=module._fx_device_browser_snapshot(handle);
 if(!pointer)throw new Error('Snapshot unavailable');
 try{return JSON.parse(module.UTF8ToString(pointer));}
 finally{module._fx_device_browser_snapshot_free(pointer);}
}
function require(value,message){if(!value)throw new Error(message);}
const records=[];
for(const sequence of input.sequences) {
 const handle=module._fx_device_browser_create(sequence.variant);
 require(handle,'Create failed');
 const rows=[];
 try{
  for(const op of sequence.operations) {
   let result=null;
   if(op.operation!=='create')result=module['_fx_device_browser_'+op.operation](handle,...op.args);
   rows.push({operation:op.operation,args:op.args,result,snapshot:snapshot(handle)});
  }
 }finally{module._fx_device_browser_destroy(handle);}
 records.push({id:sequence.id,operations:rows});
}
let guards=0;
for(const variant of [256,65536,0xffffffff]){
 require(module._fx_device_browser_create(variant)===0,'Wide variant truncated');guards++;
}
const handle=module._fx_device_browser_create(255);
require(handle,'Boundary variant failed');
try{
 const before=JSON.stringify(snapshot(handle));
 for(const width of [256,65536,0xffffffff]){
  require(module._fx_device_browser_submit_pair(handle,width,1)===-1,'Wide columns accepted');
  require(module._fx_device_browser_submit_pair(handle,1,width)===-1,'Wide rows accepted');
  require(JSON.stringify(snapshot(handle))===before,'Rejected pair mutated');guards+=2;
 }
 for(const flag of [2,255,256,65536,0xffffffff]){
  require(module._fx_device_browser_step(handle,flag)===-1,'Wide timer accepted');
  require(JSON.stringify(snapshot(handle))===before,'Rejected flag mutated');guards++;
 }
 require(module._fx_device_browser_ack_timer(handle)===-1,'Nonpending ack accepted');
 require(JSON.stringify(snapshot(handle))===before,'Nonpending ack mutated');guards++;
 const pointers=[];
 for(let n=0;n<16;n++)pointers.push(module._fx_device_browser_snapshot(handle));
 require(pointers.every(Boolean)&&new Set(pointers).size===pointers.length,'Snapshots not independently owned');
 require(pointers.every(p=>module.UTF8ToString(p)===before),'Allocated snapshots differ');
 module._fx_device_browser_reset(handle);
 require(pointers.every(p=>module.UTF8ToString(p)===before),'Snapshot changed after controller reset');
 for(const p of pointers)module._fx_device_browser_snapshot_free(p);
 guards+=3;
}finally{module._fx_device_browser_destroy(handle);}
require(module._fx_device_browser_snapshot(0)===0,'NULL snapshot');
module._fx_device_browser_destroy(0);module._fx_device_browser_snapshot_free(0);
for(const method of ['reset','release','ack_timer']){require(module['_fx_device_browser_'+method](0)===-1,'NULL '+method);guards++;}
require(module._fx_device_browser_step(0,0)===-1&&module._fx_device_browser_submit_pair(0,1,1)===-1&&module._fx_device_browser_take_callback(0)===0,'NULL transport');guards+=3;
fs.writeFileSync(process.argv[3],JSON.stringify({schema:1,status:'pass',sequences:records,guards,scope:'Actual WebAssembly exports; input contains only operation names/arguments. No native expected state is supplied to module.'},null,2)+'\n');
