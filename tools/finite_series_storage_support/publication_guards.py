import hashlib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];D=ROOT/'analysis/build/finite-series-storage-guards';D.mkdir(parents=True,exist_ok=True)
tool=ROOT/'tools/test_finite_series_storage_c.py';fixture=ROOT/'analysis/native-fixtures/finite-series/inputs.json'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
pins={str(p):sha(p)for p in [Path(__file__),tool,fixture,Path(sys.executable).resolve()]}
data=json.loads(fixture.read_text());rows=[]
def run(name,payload,args,expect):
 path=D/(name+'.json');path.write_text(json.dumps(payload)+'\n')
 result=subprocess.run([sys.executable,str(tool),'--fixture',str(path),*args],capture_output=True,text=True)
 ok=result.returncode!=0 and expect in result.stderr
 rows.append(dict(name=name,returncode=result.returncode,expected_error=expect,pass_result=ok,stdout=result.stdout,stderr=result.stderr))
 assert ok,name
run('custom-canonical-publication',data,[],'require --no-report')
result=subprocess.run([sys.executable,str(tool),'--source-root',str(D)],capture_output=True,text=True)
rows.append(dict(name='private-source-canonical-publication',returncode=result.returncode,pass_result=result.returncode!=0 and 'require --no-report'in result.stderr,stderr=result.stderr));assert rows[-1]['pass_result']
cases=[]
a=json.loads(json.dumps(data));a['rows'][0]['expected']='oracle output forbidden';cases.append(('oracle-field',a,'unexpected/missing input-only'))
a=json.loads(json.dumps(data));a['rows'][0]['x']=['37'];cases.append(('short-pair',a,'two records'))
a=json.loads(json.dumps(data));a['rows'][0]['abort_poll']=True;cases.append(('boolean-abort',a,'bounded abort poll'))
a=json.loads(json.dumps(data));a['rows'][0]['x'][0]='NaN';cases.append(('nonfinite-number',a,'nonfinite record'))
a=json.loads(json.dumps(data));a['rows'][0]['lower'][0]='raw:00';cases.append(('short-raw-record',a,'ten bytes'))
a=json.loads(json.dumps(data));a['expected_cases']=17;cases.append(('wrong-count',a,'recipe count'))
a=json.loads(json.dumps(data));a['rows'][1]['label']=a['rows'][0]['label'];cases.append(('duplicate-label',a,'distinct strings'))
for name,payload,expected in cases:run(name,payload,['--no-report'],expected)
changes={p:sha(p)for p,h in pins.items()if sha(p)!=h};assert not changes
(D/'report.json').write_text(json.dumps(dict(status='PASS',publication_or_schema_rejections=len(rows),rows=rows,pins=pins,changes=changes,scope='Actual subprocess preflight rejection; no C compilation/native observation was admitted by these malformed/private canonical requests.'),indent=2)+'\n')
print(json.dumps(dict(status='PASS',publication_or_schema_rejections=len(rows))))
