#!/usr/bin/env python3
"""Actual disposable-browser raw-device prototype proof, no original CPU replay."""
import argparse
import base64
import zlib
import functools
import hashlib
import http.server
import json
import os
from pathlib import Path
import shutil
import threading
import sys
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[2]
def require(v,m):
 if not v:raise ValueError(m)
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
class Quiet(http.server.SimpleHTTPRequestHandler):
 def log_message(self,*args):pass
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--dist',type=Path,default=ROOT/'simulator/dist');p.add_argument('--wasm-report',type=Path,required=True);p.add_argument('--native-report',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
 a=p.parse_args();wasm=a.dist.resolve();native_path=a.native_report.resolve();out=a.output.resolve()
 require(not (out/'report.json').exists(),'Existing proof refused');out.mkdir(parents=True,exist_ok=True)
 temporary=ROOT/('.dv-'+hashlib.sha256(str(out).encode()).hexdigest()[:6]);temporary.mkdir(exist_ok=True);os.environ['TMPDIR']=str(temporary)
 native=json.loads(native_path.read_text());wasmreportpath=a.wasm_report.resolve();wasmreport=json.loads(wasmreportpath.read_text())
 require(native['status']==wasmreport['status']=='pass' and wasmreport['native_report_sha256']==digest(native_path),'Reference binding')
 row=next(r for r in native['observations'] if r['id']=='arithmetic-v0')
 servebase=out/'served';web=servebase/'casio-explore';web.mkdir(parents=True,exist_ok=True)
 paths=[ROOT/'simulator/device'/n for n in ('index.html','app.js','styles.css')]
 sourcepins={str(p.relative_to(ROOT)):digest(p) for p in paths+[Path(__file__),native_path,wasmreportpath]}
 for name,wanted in wasmreport['artifacts_after'].items():require(digest(wasm/name)==wanted,'Combined dist differs from actual export proof '+name)
 shutil.copytree(wasm,web,dirs_exist_ok=True)
 servedpins={str(p.relative_to(web)):digest(p) for p in web.rglob('*') if p.is_file()}
 server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=str(servebase)))
 thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
 url='http://127.0.0.1:'+str(server.server_port)+'/casio-explore/device/'
 errors=[];responses={};requests=[];screenshots=[];states=0;pixels=0;guards=0;browser_observations=[]
 try:
  with sync_playwright() as play:
   browser=play.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox'])
   context=browser.new_context(viewport={'width':1200,'height':900},device_scale_factor=1)
   page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
   page.on('request',lambda request:requests.append(request.url))
   def response_handler(response):
    if response.status==200:
     key=response.url.removeprefix('http://127.0.0.1:'+str(server.server_port)+'/')
     if key.startswith('casio-explore/'):key=key[len('casio-explore/'):]
     if key=='device/':key='device/index.html'
     try:responses[key]=hashlib.sha256(response.body()).hexdigest()
     except Exception as error:errors.append('Response custody '+str(error))
   page.on('response',response_handler)
   page.goto(url);page.wait_for_function("!document.getElementById('reset').disabled")
   page.locator("#autopress").uncheck();page.locator("#create").click()
   page.wait_for_function("!document.getElementById('reset').disabled")
   def observation():return json.loads(page.locator('#observation').text_content())
   def equal(op):
    nonlocal states,pixels
    actual=observation();require(actual==op['snapshot'],'Actual UI snapshot/native differs '+op['operation'])
    rgba=page.locator('#lcd').evaluate('(canvas)=>Array.from(canvas.getContext("2d").getImageData(0,0,96,32).data)')
    framebuffer=bytes.fromhex(actual['framebuffer'])
    for y in range(32):
     for x in range(96):
      on=bool(framebuffer[y*12+(x>>3)]&(0x80>>(x&7)))
      offset=(y*96+x)*4
      require(rgba[offset:offset+4]==([33,54,44,255] if on else [192,203,179,255]),'Actual LCD canvas pixel differs')
      pixels+=1
    browser_observations.append({"operation":op["operation"],"args":op["args"],"actual_snapshot":actual,"actual_rgba_zlib_base64":base64.b64encode(zlib.compress(bytes(rgba))).decode()})
    states+=1
   for op in row['operations']:
    method=op['operation']
    if method=='submit_pair':
     packet=str(op['args'][0])+','+str(op['args'][1])
     page.locator('button[data-packet="'+packet+'"]').click()
    elif method!='create':
     identifier={'reset':'reset','step':'step','release':'release','ack_timer':'timer','take_callback':'callback'}[method]
     page.locator('#'+identifier).click()
     if method=='take_callback':require(page.locator('#error').inner_text()=='Drained callback '+str(op['result'])+'.','Actual callback UI result differs')
    equal(op)
   require(page.locator('#error').inner_text().startswith('Drained callback'),'Unexpected final UI failure')
   desktop=out/'desktop.png';page.screenshot(path=str(desktop),full_page=True);screenshots.append({'file':desktop.name,'sha256':digest(desktop)})
   for value in ('256','4294967296','1.5','-1',''):
    before=observation();page.locator('#variant').fill(value);page.locator('#create').click()
    require(observation()==before and page.locator('#error').inner_text(),'Invalid variant UI mutated observable device')
    guards+=1
   page.locator('#variant').fill('0')
   page.set_viewport_size({'width':390,'height':844})
   require(page.evaluate('document.documentElement.scrollWidth<=window.innerWidth'),'Mobile horizontal overflow')
   mobile=out/'mobile.png';page.screenshot(path=str(mobile),full_page=True);screenshots.append({'file':mobile.name,'sha256':digest(mobile)})
   require(not errors,'Browser runtime errors '+repr(errors))
   require(not any('/api/' in u for u in requests),'Unexpected HTTP engine/API access')
   for name in ('device/index.html','device/app.js','device/styles.css','fx991sim.js','fx991sim.wasm'):
    require(responses.get(name)==servedpins[name],'Actual combined loaded asset differs '+name)
   context.close();browser.close()
 finally:server.shutdown();server.server_close()
 require(sourcepins=={name:digest(ROOT/name) for name in sourcepins},'Prototype/reference/tool drift')
 require(servedpins=={str(p.relative_to(web)):digest(p) for p in web.rglob('*') if p.is_file()},'Served artifact drift')
 archive=out/'actual-browser-observations.json';archive.write_text(json.dumps(browser_observations,indent=2)+'\n')
 report={'schema':1,'status':'pass','actual_browser_snapshot_comparisons':states,'actual_canvas_pixel_comparisons':pixels,'ui_invalid_variant_guards':guards,
  'source_pins_before':sourcepins,'source_pins_after':sourcepins,'served_artifacts':servedpins,'actual_loaded_response_sha256':responses,
  'actual_browser_observations_file':archive.name,'actual_browser_observations_sha256':digest(archive),'screenshots':screenshots,'browser_errors':errors,'api_requests':0,
  'native_report_sha256':digest(native_path),'wasm_report_sha256':digest(wasmreportpath),
  'scope':'Actual final combined evaluator+device module served at a project subpath; one explicit step per click, raw packets and real C LCD. Saved fresh host-native reference; zero fresh original CPU executions. Existing Pages/UI assets unchanged.'}
 (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps({'status':'pass','report':str(out/'report.json'),'sha256':digest(out/'report.json'),'states':states,'pixels':pixels,'screenshots':len(screenshots)},indent=2))
if __name__=='__main__':main()
