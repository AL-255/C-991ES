#!/usr/bin/env python3
"""Actual browser bounded scheduler proof; saved fresh host-C reference."""
import argparse, base64, datetime as dt, functools, hashlib, http.server, json, os, shutil, threading,zlib
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[2]
def require(v,m):
 if not v:raise ValueError(m)
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
class Quiet(http.server.SimpleHTTPRequestHandler):
 def log_message(self,*args):pass
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--native-trace',type=Path,required=True);p.add_argument('--build-report',type=Path,required=True);p.add_argument('--dist',type=Path,default=ROOT/'simulator/dist');p.add_argument('--output',type=Path);a=p.parse_args();out=(a.output or ROOT/'analysis/build/device-browser'/('scheduler-browser-'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ'))).resolve()
 require(not (out/'report.json').exists(),'Existing proof refused');out.mkdir(parents=True,exist_ok=True)
 prototype=ROOT/'simulator/device';reference=a.native_trace.resolve()
 native=json.loads(reference.read_text());require(native['status']=='pass','Native trace reference')
 build_path=a.build_report.resolve();build=json.loads(build_path.read_text())
 for name,wanted in native['source_pins_after'].items():require(digest(ROOT/name)==wanted,'Fresh native source drift '+name)
 require(digest(Path(native['library']))==native['library_sha256'],'Fresh native library drift')
 for name,wanted in build['input_pins'].items():require(digest(ROOT/name)==wanted,'Current built input drift '+name)
 inputs=list({Path(__file__),reference,build_path,*[ROOT/n for n in native['source_pins_after']],*[ROOT/n for n in build['input_pins']],*[prototype/n for n in ('index.html','app.js','styles.css')]})
 pins={str(p.relative_to(ROOT)):digest(p) for p in inputs}
 web=out/'served';web.mkdir(exist_ok=True)
 for name in ('fx991sim.js','fx991sim.wasm'):
  actual=a.dist.resolve()/name;require(digest(actual)==build['artifacts'][name]['sha256'],'Frozen module differs');shutil.copyfile(actual,web/name)
 (web/'scheduler').mkdir()
 for name in ('index.html','app.js','styles.css'):
  selected=a.dist.resolve()/'device'/name
  require(digest(selected)==build['artifacts']['device/'+name]['sha256'] and digest(selected)==digest(prototype/name),'Built device asset differs '+name)
  shutil.copyfile(selected,web/'scheduler'/name)
 served={str(p.relative_to(web)):digest(p) for p in web.rglob('*') if p.is_file()}
 short=ROOT/('.dv-sc-'+hashlib.sha256(str(out).encode()).hexdigest()[:6]);short.mkdir(exist_ok=True);os.environ['TMPDIR']=str(short)
 server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=str(web)));threading.Thread(target=server.serve_forever,daemon=True).start()
 origin='http://127.0.0.1:'+str(server.server_port);errors=[];requests=[];responses={};observations=[];states=0;pixels=0;trace_states=0
 try:
  with sync_playwright() as play:
   browser=play.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox']);context=browser.new_context(viewport={'width':1200,'height':900},device_scale_factor=1);context.add_init_script("window.__actual_device_operations=[];document.addEventListener('fxsim:device-operation',event=>window.__actual_device_operations.push(structuredClone(event.detail)));");page=context.new_page()
   page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:requests.append(r.url))
   def response(r):
    if r.status==200:
     key=r.url.removeprefix(origin+'/')
     if key=='scheduler/':key='scheduler/index.html'
     responses[key]=hashlib.sha256(r.body()).hexdigest()
   page.on('response',response);page.goto(origin+'/scheduler/');page.wait_for_function("!document.getElementById('reset').disabled")
   def read():return json.loads(page.locator('#observation').text_content())
   def equal(want,label):
    nonlocal states,pixels
    actual=read();require(actual==want,'Actual gesture final snapshot differs '+label)
    rgba=bytes(page.locator('#lcd').evaluate('(c)=>Array.from(c.getContext("2d").getImageData(0,0,96,32).data)'));fb=bytes.fromhex(actual['framebuffer'])
    for y in range(32):
     for x in range(96):
      i=4*(y*96+x);want_rgba=bytes([33,54,44,255] if fb[12*y+(x>>3)]&(128>>(x&7)) else [192,203,179,255]);require(rgba[i:i+4]==want_rgba,'Actual LCD pixel');pixels+=1
    observations.append({'label':label,'snapshot':actual,'actual_rgba_zlib_base64':base64.b64encode(zlib.compress(rgba)).decode()});states+=1
   for index,row in enumerate(native['rows']):
    if index:
     page.evaluate('window.__actual_device_operations=[]');page.locator('#create').click();page.wait_for_function("!document.getElementById('reset').disabled")
    boot_count=len(row['operations'])-sum(g['operations'] for g in row['gestures'])
    equal(row['operations'][boot_count-1]['snapshot'],row['id']+'/boot')
    for count,gesture in enumerate(row['gestures']):
     key=gesture['input'];page.locator('button[data-packet="'+str(key['columns'])+','+str(key['rows'])+'"]').click()
     page.wait_for_function("!document.getElementById('reset').disabled")
     require(not page.locator('#error').inner_text(),'Scheduler UI failure')
     equal(gesture['final'],row['id']+'/'+str(count))
    trace=page.evaluate('window.__actual_device_operations');require(trace==row['operations'],'Actual JS C-operation trace differs '+row['id']);trace_states+=len(trace)
    observations.append({'recipe':row['id'],'actual_c_trace':trace})
   desktop=out/'desktop.png';page.screenshot(path=str(desktop),full_page=True)
   page.set_viewport_size({'width':390,'height':844});require(page.evaluate('document.documentElement.scrollWidth<=innerWidth'),'Mobile overflow');mobile=out/'mobile.png';page.screenshot(path=str(mobile),full_page=True)
   require(not errors and not any('/api/' in u for u in requests),'Runtime/API issue')
   for name in served:require(responses.get(name)==served[name],'Actual loaded prototype/module differs '+name)
   context.close();browser.close()
 except Exception as error:
  (out/'FAILED.json').write_text(json.dumps({'error':str(error),'states':states,'pixels':pixels,'errors':errors,'responses':responses},indent=2)+'\n');raise
 finally:server.shutdown();server.server_close()
 require(pins=={n:digest(ROOT/n) for n in pins},'Source/reference drift')
 require(digest(Path(native['library']))==native['library_sha256'],'Native library drift')
 require(served=={str(p.relative_to(web)):digest(p) for p in web.rglob('*') if p.is_file()},'Served artifact drift')
 for name in ('fx991sim.js','fx991sim.wasm','device/index.html','device/app.js','device/styles.css'):
  require(digest(a.dist.resolve()/name)==build['artifacts'][name]['sha256'],'Selected built artifact drift '+name)
 archive=out/'observations.json';archive.write_text(json.dumps(observations,indent=2)+'\n')
 report={'schema':1,'status':'pass','actual_c_operation_snapshots':trace_states,'actual_gesture_boot_dom_states':states,'actual_canvas_pixels':pixels,'native_report_sha256':digest(reference),'build_report_sha256':digest(build_path),'source_pins_before':pins,'source_pins_after':pins,'actual_loaded_response_sha256':responses,'served_artifacts':served,'archive_sha256':digest(archive),'screenshots':{n:digest(out/n) for n in ('desktop.png','mobile.png')},'errors':errors,'api_requests':0,'scope':'Actual adopted WASM ordinary-click scheduler on existing opaque C device. Saved fresh current host-C trace compared offline; no original CPU/host arithmetic/fabricated body completions. Semantic delays explicitly accelerated and bounded.'}
 (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps({'status':'pass','sha256':digest(out/'report.json'),'trace_states':trace_states,'dom_states':states,'pixels':pixels},indent=2))
if __name__=='__main__':main()
