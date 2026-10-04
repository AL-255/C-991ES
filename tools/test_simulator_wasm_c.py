#!/usr/bin/env python3
"""Actual browser WASM ABI safety and saved native-observation comparisons.

The 55 observations are retained original-ROM evidence, not freshly executed
firmware. Reference data is comparison-only and never enters C/WASM calls.
This suite does not claim whole key/UI or physical-RAM parity.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright

from c_build_inputs import implementation_inputs

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "analysis/native-fixtures/simulator/inputs.json"
REFERENCE = ROOT / "analysis/native-observations/simulator/native-55.json"
FIXTURE_SHA = "8578435bfa9f7683e887a2254db31349d2b1d85b9d329f54d2618df83ff005c7"
REFERENCE_SHA = "994fb7377426f2d6c10014d940d77744ca201a9c681b261ccceb7d4447d31792"
WIRE_KEYS = {"status", "native_status", "error", "error_position", "error_position_kind",
             "real", "imag", "tokens", "framebuffer", "width", "height", "plain"}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pins(paths):
    return {str(Path(p).resolve()): digest(p) for p in sorted(set(paths))}


def drift(before):
    return {p: {"before": h, "after": digest(p) if Path(p).is_file() else None}
            for p, h in before.items() if not Path(p).is_file() or digest(p) != h}


def wasm_abi(module_path, wasm_path):
    """Inspect actual binary signatures; do not assume the native ABI sizes."""
    data = wasm_path.read_bytes()
    if data[:8] != b"\0asm\x01\0\0\0":
        raise ValueError("Expected a version1 WebAssembly module")
    offset = 8
    types, imported_types, local_types, exports, imports, memories = [], [], [], {}, [], []

    def uint(raw, cursor):
        value, shift = 0, 0
        while True:
            byte = raw[cursor]; cursor += 1
            value |= (byte & 127) << shift
            if not byte & 128:
                return value, cursor
            shift += 7
            if shift > 35:
                raise ValueError("Unbounded WebAssembly integer")

    def name(raw, cursor):
        size, cursor = uint(raw, cursor)
        return raw[cursor:cursor + size].decode("utf-8"), cursor + size

    def limits(raw, cursor):
        flags, cursor = uint(raw, cursor)
        minimum, cursor = uint(raw, cursor)
        maximum = None
        if flags & 1:
            maximum, cursor = uint(raw, cursor)
        return {"flags": flags, "minimum_pages": minimum, "maximum_pages": maximum}, cursor

    while offset < len(data):
        section = data[offset]; size, offset = uint(data, offset + 1)
        raw = data[offset:offset + size]; offset += size
        if len(raw) != size:
            raise ValueError("Truncated WebAssembly section")
        cursor = 0
        if section == 1:
            count, cursor = uint(raw, cursor)
            for _ in range(count):
                if raw[cursor] != 0x60:
                    raise ValueError("Unexpected non-function type")
                count, cursor = uint(raw, cursor + 1)
                params = list(raw[cursor:cursor + count]); cursor += count
                count, cursor = uint(raw, cursor)
                result = list(raw[cursor:cursor + count]); cursor += count
                types.append({"parameters": params, "results": result})
        elif section == 2:
            count, cursor = uint(raw, cursor)
            for _ in range(count):
                namespace, cursor = name(raw, cursor); symbol, cursor = name(raw, cursor)
                kind = raw[cursor]; cursor += 1
                entry = {"module": namespace, "name": symbol, "kind": kind}
                if kind == 0:
                    index, cursor = uint(raw, cursor); imported_types.append(index)
                    entry["type"] = index
                elif kind == 1:
                    cursor += 1; entry["limits"], cursor = limits(raw, cursor)
                elif kind == 2:
                    entry["limits"], cursor = limits(raw, cursor); memories.append(entry["limits"])
                elif kind == 3:
                    cursor += 2
                else:
                    raise ValueError("Unexpected WebAssembly import kind")
                imports.append(entry)
        elif section == 3:
            count, cursor = uint(raw, cursor)
            for _ in range(count):
                index, cursor = uint(raw, cursor); local_types.append(index)
        elif section == 5:
            count, cursor = uint(raw, cursor)
            for _ in range(count):
                value, cursor = limits(raw, cursor); memories.append(value)
        elif section == 7:
            count, cursor = uint(raw, cursor)
            for _ in range(count):
                symbol, cursor = name(raw, cursor); kind = raw[cursor]; cursor += 1
                index, cursor = uint(raw, cursor); exports[symbol] = {"kind": kind, "index": index}
    js = module_path.read_text()
    mappings = dict(re.findall(r'Module\["(_(?:fxsim_\w+|malloc|free))"\]=wasmExports\["([^"\]]+)"\]', js))
    expected = {"_fxsim_create": ([], [127]), "_fxsim_destroy": ([127], []),
                "_fxsim_reset": ([127], []), "_fxsim_evaluate": ([127] * 7, [127]),
                "_malloc": ([127], [127]), "_free": ([127], [])}
    functions = imported_types + local_types
    signatures = {}
    for public, (params, results) in expected.items():
        export = exports[mappings[public]]
        if export["kind"] != 0:
            raise ValueError("C symbol is not a function export")
        signature = types[functions[export["index"]]]
        if signature != {"parameters": params, "results": results}:
            raise ValueError("Actual wasm32 C signature mismatch for " + public)
        signatures[public] = signature
    if any(value in (124, 125) for entry in types for value in entry["parameters"] + entry["results"]):
        raise ValueError("Floating-point function types in the actual module")
    if len(memories) != 1 or memories[0]["flags"] & 4:
        raise ValueError("Expected a single wasm32 memory")
    import_object = re.search(r"var wasmImports=\{([^}]+)\}", js)
    import_map = dict(re.findall(r'([\w]+):([\w]+)', import_object.group(1))) if import_object else {}
    if len(imports) != 1 or imports[0]["kind"] != 0 or import_map != {
            imports[0]["name"]: "_emscripten_resize_heap"}:
        raise ValueError("Unexpected host imports; explicit review required")
    if types[imports[0]["type"]] != {"parameters": [127], "results": [127]}:
        raise ValueError("Unexpected heap-growth import signature")
    return {"status": "PASS", "signatures": signatures, "imports": imports,
            "memory": memories[0], "function_type_count": len(types),
            "host_import_semantics": "Only Emscripten integer heap growth; no host numerical/CPU imports",
            "scope": "Actual wasm32 pointer/unsigned/size_t C API signatures and all function types"}


def validate_reference(fixture, reference):
    if digest(FIXTURE) != FIXTURE_SHA or digest(REFERENCE) != REFERENCE_SHA:
        raise ValueError("Frozen authored fixture or native observation identity changed")
    fixture_keys = {"version", "sessions", "pixel_points", "encoder_rejections"}
    reference_keys = {"version", "status", "fixture_path", "fixture_sha256",
                      "source_report_path", "source_report_sha256", "source_tool_sha256",
                      "native_calls", "native_instructions", "expression_controls",
                      "served_release_sha256", "native_fields", "C_only_field", "scope", "rows"}
    if set(fixture) != fixture_keys or set(reference) != reference_keys:
        raise ValueError("Unexpected fixture/reference schema")
    if fixture.get("version") != 1 or reference.get("version") != 1 or reference["status"] != "pass":
        raise ValueError("Unknown fixture/reference version")
    for session in fixture["sessions"]:
        if set(session) != {"label", "reset_each", "steps"} or type(session["reset_each"]) is not bool:
            raise ValueError("Unexpected session recipe schema")
        for step in session["steps"]:
            if set(step) != {"label", "text", "native_tokens", "mode", "angle", "math"}:
                raise ValueError("Unexpected authored input schema")
            if not step["text"].isascii() or "\0" in step["text"] or len(step["text"]) > 4096:
                raise ValueError("Invalid authored ASCII source")
            for field, maximum in (("mode", 5), ("angle", 2), ("math", 1)):
                if type(step[field]) is not int or not 0 <= step[field] <= maximum:
                    raise ValueError("Invalid authored mode/angle/Math setting")
    steps = [(s["label"], x) for s in fixture["sessions"] for x in s["steps"]]
    rows = reference["rows"]
    if len(steps) != 55 or len(rows) != 55 or reference["expression_controls"] != 55:
        raise ValueError("The complete saved 55-row inventory is required")
    if reference["fixture_sha256"] != FIXTURE_SHA:
        raise ValueError("Reference does not bind the authored inputs")
    for index, ((session, step), row) in enumerate(zip(steps, rows)):
        if set(row) != {"index", "session", "input", "encoder_admitted", "native",
                        "expected_engine_contract", "release_actual"}:
            raise ValueError("Unexpected saved observation row schema")
        if row["index"] != index + 1 or row["session"] != session or row["input"] != step:
            raise ValueError("Reference/session order differs from the authored fixture")
        if type(row["encoder_admitted"]) is not bool:
            raise ValueError("Missing explicit encoder-admission classification")
        if not isinstance(row["native"], dict) or not isinstance(row["release_actual"], dict):
            raise ValueError("Missing retained observation")
        for key in ("real", "imag", "tokens", "framebuffer"):
            raw = row["release_actual"][key]
            if not isinstance(raw, str) or not re.fullmatch(r"(?:[0-9a-f]{2})*", raw):
                raise ValueError("Malformed saved byte field")
        if len(row["release_actual"]["framebuffer"]) != 768:
            raise ValueError("Saved LCD extent differs")


def validate_wire(response, step):
    if type(response) is not dict or set(response) != WIRE_KEYS | {"expression"}:
        raise ValueError("Actual facade response must have the exact12 C fields plus expression")
    if response["expression"] != step["text"]:
        raise ValueError("Facade input label differs")
    if response["status"] not in ("ok", "error", "unsupported"):
        raise ValueError("Unclear result status")
    if type(response["native_status"]) is not int or type(response["error_position"]) is not int:
        raise ValueError("Native status/cursor must be integers")
    if not 0 <= response["error_position"] <= 8193:
        raise ValueError("Unbounded native token cursor")
    if response["error_position_kind"] not in ("ascii-byte", "native-token"):
        raise ValueError("Unknown cursor unit")
    if response["error_position_kind"] == "ascii-byte" and response["error_position"] > len(step["text"].encode("ascii")):
        raise ValueError("ASCII cursor exceeds authored source")
    for field, exact in (("real", 20), ("imag", 20), ("framebuffer", 768)):
        if type(response[field]) is not str or not re.fullmatch(r"[0-9a-f]{" + str(exact) + r"}", response[field]):
            raise ValueError("Wrong byte field extent: " + field)
    if type(response["tokens"]) is not str or not re.fullmatch(r"(?:[0-9a-f]{2}){0,1024}", response["tokens"]):
        raise ValueError("Unbounded display tokens")
    if response["width"] != 96 or response["height"] != 32 or type(response["plain"]) is not str:
        raise ValueError("Wrong LCD/presentation schema")
    if response["status"] == "ok":
        if response["error"] is not None:
            raise ValueError("Stale error on successful response")
    elif type(response["error"]) is not str or not response["error"]:
        raise ValueError("Missing error/unsupported explanation")


# This receives only a module URL. Authored inputs for the separate collector
# contain no expected output; retained observations are never supplied here.
ABI_CHECKS = r"""async ({moduleURL}) => {
  const rows = [], failures = [], encoder = new TextEncoder(), decoder = new TextDecoder();
  const check = (condition, label, detail=null) => {
    rows.push({label,passed:!!condition,detail});
    if (!condition) throw new Error(label + ': ' + JSON.stringify(detail));
  };
  const factory = (await import(moduleURL)).default;
  check(typeof factory === 'function', 'ES module default factory');
  const m = await factory(), other = await factory();
  const required = ['_fxsim_create','_fxsim_destroy','_fxsim_reset','_fxsim_evaluate','_malloc','_free'];
  for (const name of required) check(typeof m[name] === 'function', 'export ' + name);
  check(m.HEAPU8 instanceof Uint8Array, 'current byte heap view');
  check(m.HEAPU8.buffer !== other.HEAPU8.buffer, 'factory instance memory isolation');
  const live = new Set(), history = [];
  const create = () => {
    const p=m._fxsim_create();
    check(Number.isInteger(p) && p>0, 'session allocation'); live.add(p); return p;
  };
  const destroy = p => {m._fxsim_destroy(p);live.delete(p);};
  const call = (p,text='1',mode=0,angle=0,math=1,cap=32768,expected=0) => {
    const data=text===null?null:encoder.encode(text+'\0');
    let input=0, output=0;
    try {
      if(data){input=m._malloc(data.length);check(input!==0,'input allocation');m.HEAPU8.set(data,input);}
      output=m._malloc(cap+32);check(output!==0,'output allocation');
      m.HEAPU8.fill(0xad,output,output+cap+32);
      const result=m._fxsim_evaluate(p,input,mode,angle,math,output+16,cap);
      check(result===expected,'C return',{text:text?.slice(0,80),cap,result,expected});
      // Reacquire after C: allocation in the engine may have grown memory.
      check(m.HEAPU8.slice(output,output+16).every(x=>x===0xad) &&
        m.HEAPU8.slice(output+16+cap,output+32+cap).every(x=>x===0xad),'output capacity canaries');
      if(data)check(data.every((x,i)=>m.HEAPU8[input+i]===x),'immutable input');
      if(result){check(!cap||m.HEAPU8[output+16]===0,'failed response cleared');return null;}
      const bytes=m.HEAPU8.slice(output+16,output+16+cap),end=bytes.indexOf(0);
      check(end>=0,'bounded JSON terminator');
      const wire=decoder.decode(bytes.slice(0,end)),value=JSON.parse(wire);
      check(['ok','error','unsupported'].includes(value.status),'explicit response status');
      check(value.width===96&&value.height===32&&value.framebuffer.length===768,'LCD extent');
      check(value.real.length===20&&value.imag.length===20,'numeric record extent');
      check(value.status==='ok'?value.error===null:typeof value.error==='string'&&!!value.error,'clear error contract');
      history.push({text,mode,angle,math,capacity:cap,return:result,result:value});
      return {value,wire};
    } finally {if(output)m._free(output);if(input)m._free(input);}
  };
  const same = (a,b,label) => check(JSON.stringify(a)===JSON.stringify(b),label,{a,b});
  try {
    const a=create(),b=create();
    for(const p of [a,b]) {call(p,'7->A');call(p,'11');call(p,'2+3');}
    for(const cap of [0,1,2,31,127,511]) {
      call(a,'99->A',0,0,1,cap,-1);call(a,'Ran#',0,0,1,cap,-1);
    }
    for(const args of [[a,'99',6,0,1],[a,'99',0,3,1],[a,'99',0,0,2],[a,null,0,0,1],[0,'99',0,0,1]])
      call(...args,32,-1);
    call(a,'1'+' '.repeat(4096),0,0,1,32,-1);
    for(const text of ['A','Ans','PreAns','Ran#'])same(call(a,text).value,call(b,text).value,'failed request state retention '+text);
    const boundary=create(), twin=create();
    const expected=call(twin,'13->A');
    call(boundary,'13->A',0,0,1,encoder.encode(expected.wire).length,-1);
    same(call(boundary,'13->A',0,0,1,encoder.encode(expected.wire).length+1).value,expected.value,'exact JSON capacity');
    const c=create();check(call(c,'A').value.real==='00000000000000000000','independent session variable');
    m._fxsim_reset(a);m._fxsim_reset(b);
    same(call(a,'Ran#').value,call(b,'Ran#').value,'reset seed equality');
    m._fxsim_reset(a);check(call(a,'Ans').value.real==='00000000000000000000','reset answer');
    // Exercise replacement of heap views before another actual C evaluation.
    const old=m.HEAPU8.buffer,block=m._malloc(old.byteLength+65536);
    check(block!==0,'growth allocation');
    check(m.HEAPU8.buffer!==old,'memory growth replaces view');m._free(block);
    check(call(a,'2+3').value.real==='05000000000000000001','post-growth C result');
    for(const text of ['foo(1)','1@2','1+','sqrt(','('.repeat(33)+'1'+')'.repeat(33)])
      check(call(a,text).value.status==='unsupported','malformed text explained');
    const recycled=[];
    for(let i=0;i<64;i++){const p=create();recycled.push(p);call(p,'1+1');destroy(p);}
    check(new Set(recycled).size<=2,'bounded allocator reuse after session destroy',{unique:new Set(recycled).size});
    m._fxsim_destroy(0);m._fxsim_reset(0);
    const facade=await import(new URL('./engine.js',location.href).href);
    check((await facade.request('/api/evaluate',{expression:'9->A'})).status==='ok','facade actual C request');
    for(const [path,body] of [['/bad',{}],['/api/evaluate',{expression:'1',mode:6}],
      ['/api/evaluate',{expression:'1',angle:3}],['/api/evaluate',{expression:'1',math:2}],
      ['/api/evaluate',{expression:'1\0ignored'}],['/api/evaluate',{expression:'1'+' '.repeat(4096)}]]) {
      let message='';try{await facade.request(path,body);}catch(e){message=String(e);}
      check(!!message,'facade invalid request explained',{path,message});
    }
    window.dispatchEvent(new PageTransitionEvent('pagehide',{persisted:true}));
    check((await facade.request('/api/evaluate',{expression:'A'})).real==='09000000000000000001','BFcache preserves session');
    window.dispatchEvent(new PageTransitionEvent('pagehide',{persisted:false}));
    window.dispatchEvent(new PageTransitionEvent('pagehide',{persisted:false}));
    for(const path of ['/api/evaluate','/api/reset']){
      let message='';try{await facade.request(path,{expression:'A'});}catch(e){message=String(e);}
      check(message.includes('closed'),'disposed facade rejects later use',{path,message});
    }
  } catch(e) {failures.push(String(e));}
  finally {for(const p of live)m._fxsim_destroy(p);live.clear();}
  return {status:failures.length?'FAIL':'PASS',checks:rows.length,rows,failures,history,
    factory_instances:2,heap_bytes:m.HEAPU8.byteLength,scope:'Actual browser WASM C ABI; no original CPU calls'};
}"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Actual served static page, including a subpath")
    parser.add_argument("--dist", type=Path, default=ROOT / "simulator/dist")
    parser.add_argument("--module-name", default="fx991sim.js")
    parser.add_argument("--browser", default="/usr/bin/google-chrome")
    parser.add_argument("--disassembler", type=Path,
                        default=ROOT / "analysis/build/emsdk/upstream/bin/wasm-dis")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--build-report", type=Path,
                        default=ROOT / "analysis/build/simulator-wasm/build-report.json",
                        help="Exact provenance report for the selected compiled module")
    args = parser.parse_args()
    fixture, reference = json.loads(FIXTURE.read_text()), json.loads(REFERENCE.read_text())
    validate_reference(fixture, reference)
    from test_simulator_browser import collect_wasm_fixture
    dist = args.dist.resolve()
    module = dist / args.module_name
    wasm = module.with_suffix(".wasm")
    if not module.is_file() or not wasm.is_file():
        parser.error("Actual generated factory and .wasm are required; this test does not build them")
    output = (args.output or ROOT / "analysis/build/simulator-wasm-review" /
              datetime.now(timezone.utc).strftime("proof-%Y%m%dT%H%M%S.%fZ")).resolve()
    output.mkdir(parents=True, exist_ok=False)
    cmake = ROOT / "csrc/CMakeLists.txt"
    source_text = cmake.read_text()
    sources = []
    for target in ("fx991_firmware", "fx991_simulator", "fx991_device"):
        match = re.search(r"add_library\(\s*" + target + r"\s+(?:STATIC|SHARED)\s+(.*?)\)", source_text, re.S)
        if not match:
            raise ValueError("Missing actual CMake source target " + target)
        sources += ["csrc/" + p for p in re.findall(r"(?<![\w/])([\w/]+\.c)(?!\w)", match[1])]
    paths = [ROOT / p for p in implementation_inputs(ROOT, sources)]
    paths += [Path(__file__).resolve(), ROOT / "tools/test_simulator_browser.py",
              ROOT / "tools/c_build_inputs.py", cmake, FIXTURE, REFERENCE,
              ROOT / "simulator/build_web.py", ROOT / "simulator/web/engine.js"]
    paths += [p for p in dist.rglob("*") if p.is_file()]
    build_report_path = args.build_report.resolve()
    browser_binary = Path(args.browser).resolve().with_name("chrome")
    paths += [args.disassembler.resolve(), Path(args.browser).resolve(), build_report_path]
    if browser_binary.is_file():
        paths.append(browser_binary)
    before = pins(paths)
    report = {"status": "FAIL", "source_and_artifact_before": before,
              "url": args.url, "reference_sha256": REFERENCE_SHA, "fixture_sha256": FIXTURE_SHA,
              "scope": "55 saved native observations, actual browser WASM; no original-ROM reruns or full key/RAM parity"}
    failure = None
    try:
        build = json.loads(build_report_path.read_text())
        if build["pre_post_source_changes"] or build["pre_post_compiler_changes"]:
            raise AssertionError("Build reported source/compiler drift")
        for path, expected in build["input_pins"].items():
            if digest(ROOT / path) != expected:
                raise AssertionError("Built source no longer matches " + path)
        for name, artifact in build["artifacts"].items():
            if digest(dist / name) != artifact["sha256"]:
                raise AssertionError("Actual selected dist differs from build: " + name)
        report["build_report_sha256"] = digest(build_report_path)
        report["binary_ABI"] = wasm_abi(module, wasm)
        command = [str(args.disassembler.resolve()), str(wasm), "--all-features"]
        result = subprocess.run(command, check=True, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=60)
        (output / "actual-module.wat").write_text(result.stdout)
        floating = sorted(set(re.findall(r"\b(?:f32|f64)\.[a-zA-Z0-9_]+", result.stdout)))
        if floating:
            raise AssertionError({"floating_point_instructions": floating})
        report["disassembly"] = {"command": command, "sha256": digest(output / "actual-module.wat"),
                                 "floating_point_instructions": floating}
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=args.browser, headless=True)
            try:
                observed = collect_wasm_fixture(browser, args.url, FIXTURE, output / "wasm55-collected.json", dist=dist)
                if isinstance(observed, Path):
                    observed = json.loads(observed.read_text())
                report["browser_collection"] = observed
                if not observed["pass"] or observed["api_requests"] or observed["browser_errors"]:
                    raise AssertionError("Actual static browser collection failed or made HTTP API calls")
                expected_resets = []
                for session in fixture["sessions"]:
                    expected_resets.append((session["label"], None))
                    if session["reset_each"]:
                        expected_resets += [(session["label"], step["label"]) for step in session["steps"]]
                if [(row["session"], row["before_step"]) for row in observed["resets"]] != expected_resets:
                    raise AssertionError("Collector reset/session recipe differs")
                observed = observed["rows"]
                report["native_comparisons"] = []
                for row, actual in zip(reference["rows"], observed):
                    if actual["index"] != row["index"] - 1 or actual["session"] != row["session"] or actual["input"] != row["input"]:
                        raise AssertionError("Collected authored input/session/order differs")
                    if actual["request"] != {"expression": row["input"]["text"], **{
                            key: row["input"][key] for key in ("mode", "angle", "math")}}:
                        raise AssertionError("Actual WASM request is not the authored input")
                    expected = row["expected_engine_contract"]
                    response = actual["actual"]
                    validate_wire(response, row["input"])
                    delta = {key: {"expected": value, "actual": response.get(key)}
                             for key, value in expected.items() if response.get(key) != value}
                    full_delta = {key: {"expected": value, "actual": response.get(key)}
                                  for key, value in row["release_actual"].items() if response.get(key) != value}
                    report["native_comparisons"].append({"index": row["index"], "input": row["input"],
                        "encoder_admitted": row["encoder_admitted"], "native_differences": delta,
                        "saved_C_presentation_differences": full_delta, "actual": response})
                if len(observed) != 55 or any(r["native_differences"] or r["saved_C_presentation_differences"]
                                             for r in report["native_comparisons"]):
                    raise AssertionError("Saved complete55 native/C presentation comparison failed")
                context = browser.new_context()
                try:
                    page = context.new_page()
                    page.goto(args.url, wait_until="networkidle")
                    report["ABI"] = page.evaluate(ABI_CHECKS, {"moduleURL": urljoin(args.url, args.module_name)})
                    if report["ABI"]["status"] != "PASS":
                        raise AssertionError("Actual WASM ABI controls failed")
                finally:
                    context.close()
            finally:
                browser.close()
    except Exception as error:
        failure = repr(error)
    report["changes"] = drift(before)
    report["failure"] = failure
    report["status"] = "PASS" if failure is None and not report["changes"] else "FAIL"
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "report": str(output / "report.json"),
                      "saved_native_rows": len(report.get("native_comparisons", [])),
                      "ABI_checks": report.get("ABI", {}).get("checks"),
                      "failure": failure, "changes": report["changes"]}, indent=2))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
