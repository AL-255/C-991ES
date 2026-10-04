import ast,hashlib,os
from pathlib import Path
HERE=Path(os.environ['FX_TABLE_BUILD_ROOT'])
ROOT=Path(os.environ['FX_TABLE_REPOSITORY_ROOT'])
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pins(extra):
 paths=set((HERE/'csrc').rglob('*.c'))|set((HERE/'csrc').rglob('*.h'))
 paths.update(HERE/n for n in ('compile.py','evidence.py','abi.c','baseline-pins.json'))
 paths.update(ROOT/n for n in ('firmware/fx-991es-plus-c-ver4.bin','analysis/disassembly/complete.asm','tools/nxu8/harness.c','tools/nxu8/vendor/SimU8/core.c','tools/runtime_support/adapter.c','tools/nxu8/table_composition_events.c'))
 paths.update((ROOT/'tools/nxu8/vendor/SimU8').glob('*.h'))
 todo=[ROOT/'tools'/n for n in ('nxu8/machine.py','test_input_controller_c.py','test_table_controller_c.py','test_platform_c.py','trace_natural_result.py','test_table_c.py','test_table_composition_c.py')]
 todo.append(ROOT/'analysis/native-fixtures/table-controller-lifecycle/controller-final/collect.py')
 seen=set()
 while todo:
  p=todo.pop().resolve()
  if p in seen:continue
  seen.add(p)
  for node in ast.walk(ast.parse(p.read_text())):
   mods=[x.name for x in node.names]if isinstance(node,ast.Import)else [node.module]if isinstance(node,ast.ImportFrom)and node.module else []
   for mod in mods:
    q=ROOT/'tools'/Path(*mod.split('.')).with_suffix('.py')
    if q.is_file():todo.append(q)
 paths.update(seen);paths.update(Path(p)for p in extra)
 return {str(p):sha(p)for p in sorted(paths)}
def stable(expected):
 changed=[p for p,h in expected.items()if sha(p)!=h]
 if changed:raise RuntimeError('Evidence inputs changed: '+str(changed))
 return []
