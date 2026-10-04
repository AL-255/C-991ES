#!/usr/bin/env python3
"""Simulator C boundary safety: actual ports, client invariants, ASan/UBSan.

This is an application safety test, not a claim of original-ROM parity or
whole key/UI behavior. Expected numbers below are elementary client examples.
Transactional checks use independent sessions, never opaque-state inspection.
"""
import argparse
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import random
import re
import subprocess

from c_build_inputs import implementation_inputs

ROOT = Path(__file__).resolve().parents[1]
APP = ["csrc/app/fx_simulator_engine.c", "csrc/app/fx_simulator_input.c"]
GUARD = 19
KEYS = {"status", "native_status", "error", "error_position",
        "error_position_kind", "real", "imag", "tokens", "framebuffer",
        "width", "height", "plain"}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(command, *, env=None, timeout=180):
    result = subprocess.run(command, cwd=ROOT, env=env, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            timeout=timeout)
    if result.returncode:
        raise AssertionError({"command": command, "returncode": result.returncode,
                              "output": result.stdout[-12000:]})
    return result.stdout


def sources():
    cmake = (ROOT / "csrc/CMakeLists.txt").read_text()
    match = re.search(r"add_library\s*\(\s*fx991_firmware\s+STATIC\b(.*?)\)",
                      cmake, re.S)
    assert match, "Missing actual portable library source target"
    return list(dict.fromkeys(["csrc/" + s for s in
        re.findall(r"(?<![\w/])([\w/]+\.c)(?!\w)", match.group(1))] + APP))


def scalar_integer(value):
    if not value:
        return "00" * 10
    digits = str(abs(value))
    exponent = len(digits) - 1
    digits = digits.ljust(15, "0")
    return bytes([int(digits[0]), *[int(digits[n:n+2], 16)
        for n in range(1, 15, 2)], int(str(exponent), 16),
        6 if value < 0 else 1]).hex()


class Safety:
    def __init__(self, path):
        self.library = C.CDLL(str(path))
        self.library.fxsim_create.restype = C.c_void_p
        self.library.fxsim_destroy.argtypes = [C.c_void_p]
        self.library.fxsim_reset.argtypes = [C.c_void_p]
        self.library.fxsim_evaluate.argtypes = [C.c_void_p, C.c_char_p,
            C.c_uint, C.c_uint, C.c_uint, C.c_void_p, C.c_size_t]
        self.library.fxsim_evaluate.restype = C.c_int
        for name in ("fxsim_encode_expression", "fxsim_encode_expression_mode"):
            fn = getattr(self.library, name)
            fn.argtypes = [C.c_char_p] + ([C.c_uint] if name.endswith("_mode") else []) + [
                C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t), C.POINTER(C.c_size_t)]
            fn.restype = C.c_int
        self.checks = 0
        self.calls = 0
        self.groups = {}
        self.handles = []

    def check(self, condition, detail):
        self.checks += 1
        assert condition, detail

    def create(self):
        handle = self.library.fxsim_create()
        self.check(bool(handle), "Session allocation")
        self.handles.append(handle)
        return handle

    def close(self):
        for handle in self.handles:
            self.library.fxsim_destroy(handle)
        self.handles.clear()
        self.library.fxsim_destroy(None)
        self.library.fxsim_reset(None)

    def evaluate(self, handle, expression, mode=0, angle=0, math=1,
                 capacity=32768, expected_return=0):
        expression = expression.encode("utf-8") if isinstance(expression, str) else expression
        # Capacity is truthful. Every byte outside that region is a canary.
        storage = (C.c_ubyte * (capacity + 2 * GUARD))(*([0xad] * (capacity + 2 * GUARD)))
        pointer = C.cast(C.byref(storage, GUARD), C.c_void_p)
        source = C.create_string_buffer(expression) if expression is not None else None
        source_before = bytes(source) if source is not None else None
        result = self.library.fxsim_evaluate(handle,
            C.cast(source, C.c_char_p) if source is not None else None,
            mode, angle, math, pointer, capacity)
        self.calls += 1
        self.check(result == expected_return,
            (expression[:100] if expression else expression, mode, angle, math,
             capacity, result, expected_return))
        self.check(bytes(storage[:GUARD]) == b"\xad" * GUARD and
                   bytes(storage[GUARD + capacity:]) == b"\xad" * GUARD,
                   ("Output capacity canary", expression, capacity))
        self.check(source is None or bytes(source) == source_before, "Input mutation")
        if result:
            self.check(capacity == 0 or storage[GUARD] == 0, "Failed response not cleared")
            return None
        raw = bytes(storage[GUARD:GUARD + capacity])
        self.check(b"\0" in raw, "JSON missing terminator")
        response = json.loads(raw.split(b"\0", 1)[0].decode("ascii"))
        self.check(set(response) == KEYS, ("JSON schema", response))
        self.check(response["status"] in ("ok", "error", "unsupported"), "Wire status")
        self.check(isinstance(response["native_status"], int), "Native status type")
        self.check(response["width"] == 96 and response["height"] == 32, "LCD dimensions")
        self.check(len(bytes.fromhex(response["framebuffer"])) == 384, "LCD byte extent")
        self.check(len(bytes.fromhex(response["real"])) == 10 and
                   len(bytes.fromhex(response["imag"])) == 10, "Exact record extent")
        self.check(len(bytes.fromhex(response["tokens"])) <= 1024, "DISPLAY token extent")
        self.check(isinstance(response["plain"], str), "Plain field")
        self.check(isinstance(response["error_position"], int) and
                   0 <= response["error_position"] <= 8193, "Cursor extent")
        self.check(response["error_position_kind"] in ("ascii-byte", "native-token"),
                   "Cursor unit")
        if response["status"] == "ok":
            self.check(response["error"] is None, "Success with stale error")
        else:
            self.check(isinstance(response["error"], str) and bool(response["error"]),
                       "Error/unsupported request has no explicit explanation")
        return response

    def encode(self, text, capacity=8192, mode=0, expect=None, null_length=False):
        text = text.encode("utf-8") if isinstance(text, str) else text
        storage = (C.c_ubyte * (capacity + 2 * GUARD))(*([0xa5] * (capacity + 2 * GUARD)))
        before = bytes(storage)
        length, position = C.c_size_t(0x1234), C.c_size_t(0x5678)
        source = C.create_string_buffer(text) if text is not None else None
        saved = bytes(source) if source is not None else None
        result = self.library.fxsim_encode_expression_mode(
            C.cast(source, C.c_char_p) if source is not None else None, mode,
            C.cast(C.byref(storage, GUARD), C.c_void_p), capacity,
            None if null_length else C.byref(length), C.byref(position))
        self.calls += 1
        self.check(result in (0, -1, -2), ("Encoder return", result))
        if expect is not None:
            self.check(result == expect, ("Encoder expected status", text, capacity, result, expect))
        self.check(source is None or bytes(source) == saved, "Encoder input mutated")
        self.check(bytes(storage[:GUARD]) == b"\xa5" * GUARD and
                   bytes(storage[GUARD + capacity:]) == b"\xa5" * GUARD,
                   "Encoder wrote outside capacity")
        if result:
            self.check(bytes(storage) == before, "Encoder failure changed output")
            if not null_length:
                self.check(length.value == 0, "Failed encoder length")
            self.check(position.value <= (len(text) if text is not None else 0),
                       ("ASCII cursor outside source", position.value, text))
            return result, None, position.value
        self.check(1 <= length.value <= capacity, "Encoder successful extent")
        data = bytes(storage[GUARD:GUARD + length.value])
        self.check(data[-1] == 0, "Encoder length excludes terminator")
        return result, data, position.value

    def encoder_boundaries(self):
        for text in ("2+3", "2(3+4)", "sqrt(2)", "sin(0)", "1/3", "7->A",
                     "2^3", " \t2+\r\n3\v\f"):
            _, data, _ = self.encode(text, expect=0)
            for capacity in range(len(data) + 2):
                self.encode(text, capacity, expect=0 if capacity >= len(data) else -2)
        _, base, _ = self.encode("2+3", expect=0)
        self.check(self.encode(b"2+3\0unsupported-after-NUL", expect=0)[1] == base,
                   "Embedded NUL policy")
        for text in (b"", b"@", b"\xff", b"\xc3\xa9", b"\x012",
                     b"unknown(1)", b"1 " + b"\xc3\xa9", b"1\"" ):
            self.encode(text, expect=-1)
        self.encode(None, expect=-1)
        self.encode("1", null_length=True, expect=-1)
        self.encode("1", mode=6, expect=-1)
        self.encode("1", mode=0xffffffff, expect=-1)
        self.encode("1" + " " * 4095, expect=0)
        self.encode("1" + " " * 4096, expect=-1)
        self.encode("(" * 32 + "1" + ")" * 32, expect=0)
        self.encode("(" * 33 + "1" + ")" * 33, expect=-1)
        # API failure must remain transactional even with a null output pointer.
        length, position = C.c_size_t(7), C.c_size_t(7)
        result = self.library.fxsim_encode_expression_mode(
            b"1", 0, None, 0, C.byref(length), C.byref(position))
        self.check(result == -1 and length.value == 0, "Encoder null output")

    def clients_and_errors(self):
        handle = self.create()
        for mode in range(6):
            for angle in range(3):
                for math in range(2):
                    r = self.evaluate(handle, "1+1", mode, angle, math)
                    self.check(r["status"] == "ok" and r["real"] == scalar_integer(2),
                               ("Simple arithmetic options", mode, angle, math, r))
        invalid_digit = self.evaluate(handle, "2+3", mode=2)
        self.check(invalid_digit["status"] == "error" and invalid_digit["native_status"] == 2,
                   "BIN invalid digit reaches native Syntax")
        for mode, expected in ((2, 3), (3, 9), (4, 11), (5, 17)):
            r = self.evaluate(handle, "10+1", mode)
            self.check(r["status"] == "ok" and r["real"] == scalar_integer(expected),
                       ("Selected radix input", mode, r))
        for expression, angle in (("sin(90)", 0), ("sin(100)", 2)):
            r = self.evaluate(handle, expression, angle=angle)
            self.check(r["status"] == "ok" and r["real"] == scalar_integer(1),
                       ("Angle interpretation", expression, angle, r))
        error = self.evaluate(handle, "1/0")
        self.check(error["status"] == "error" and error["native_status"] == 3 and
                   error["error_position_kind"] == "native-token", "Math error publication")
        unsupported = self.evaluate(handle, "definitely_unknown(1)")
        self.check(unsupported["status"] == "unsupported" and
                   unsupported["error_position_kind"] == "ascii-byte",
                   "Encoder error publication")
        for expression in ("2+", "(", "sqrt(", "1,,2", "2->", "2->Z", "2))",
                           "';drop table x;'", "NaN", "Infinity", "\u221a2",
                           "integral(X,0,1)", "MatA"):
            self.evaluate(handle, expression)
        self.evaluate(handle, "1" + " " * 4095)
        self.evaluate(handle, "1" + " " * 4096, expected_return=-1)
        nul = self.evaluate(handle, b"2+3\0ignored")
        self.check(nul["real"] == scalar_integer(5), "Engine embedded NUL")

    def continuation(self, a, b):
        for text in ("A", "Ans", "Ans+1", "Ran#"):
            left = self.evaluate(a, text)
            right = self.evaluate(b, text)
            self.check(left == right, ("Session diverged after failed request", text, left, right))

    def transactions(self):
        a, b = self.create(), self.create()
        for text in ("7->A", "11", "2+3"):
            self.check(self.evaluate(a, text) == self.evaluate(b, text), "Session setup")
        for kwargs in ({"mode": 6}, {"mode": 0xffffffff}, {"angle": 3},
                       {"angle": 0xffffffff}, {"math": 2}, {"math": 0xffffffff}):
            self.evaluate(a, "9->A", expected_return=-1, **kwargs)
        self.evaluate(a, None, expected_return=-1)
        self.evaluate(a, "1" + " " * 4096, expected_return=-1)
        self.evaluate(None, "9->A", expected_return=-1)
        self.check(self.library.fxsim_evaluate(a, b"9->A", 0, 0, 1, None, 4096) == -1,
                   "Null engine output")
        for expression in ("9->A", "Ran#", "1/0"):
            for capacity in (0, 1, 2, 17, 128, 512):
                self.evaluate(a, expression, capacity=capacity, expected_return=-1)
        self.continuation(a, b)
        # Derive exact JSON size from an independent fresh session. Exercise
        # both sides of the capacity boundary without committing the failed one.
        reference, actual = self.create(), self.create()
        full = self.evaluate(reference, "9->A")
        wire = json.dumps(full, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        self.evaluate(actual, "9->A", capacity=len(wire), expected_return=-1)
        fit = self.evaluate(actual, "9->A", capacity=len(wire) + 1)
        self.check(fit == full, "Exact JSON capacity")
        self.continuation(actual, reference)
        # Separate handles isolate stored values and reset restores zero/random.
        stored, untouched = self.create(), self.create()
        self.evaluate(stored, "7->A")
        self.check(self.evaluate(untouched, "A")["real"] == scalar_integer(0),
                   "Cross-session variable mutation")
        self.library.fxsim_reset(stored)
        fresh = self.create()
        self.continuation(stored, fresh)

    def fuzz(self):
        rng = random.Random(0x9915afe)
        alphabet = b"0123456789ABCXYZ+-*/^(),. \t\n#@[]{}!'\"\\"
        handle = self.create()
        corpus = [bytes(rng.choice(alphabet) for _ in range(rng.randrange(0, 90)))
                  for _ in range(128)]
        corpus += [b"(" * n + b"1" + b")" * n for n in (31, 32, 33, 128)]
        for expression in corpus:
            self.encode(expression)
            self.evaluate(handle, expression)


SMOKE = r"""
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "app/fx_simulator_engine.h"
#include "app/fx_simulator_input.h"
static void evaluate(fx_simulator *s, const char *text, unsigned mode,
                     unsigned angle, unsigned math, size_t cap) {
    unsigned char *p = malloc(cap + 38); char *out;
    int result; size_t n;
    assert(p); memset(p, 0xad, cap + 38); out = (char *)(p + 19);
    result = fxsim_evaluate(s, text, mode, angle, math, out, cap);
    assert(result == 0 || result == -1);
    for(n=0;n<19;n++) assert(p[n]==0xad && p[19+cap+n]==0xad);
    if(result==0) assert(memchr(out,0,cap));
    else if(cap) assert(out[0]==0);
    free(p);
}
int main(void) {
    fx_simulator *s=fxsim_create(); unsigned mode,angle,math,n;
    char longtext[4098]; uint8_t output[130]; size_t length,position;
    static const char *cases[]={"2+3","7->A","A","Ans","Ran#","1/0","sqrt(2)",
        "2+","(","unknown(1)","2->Z","2))","sin(90)","1,,2","MatA","NaN"};
    assert(s);
    for(mode=0;mode<6;mode++) for(angle=0;angle<3;angle++) for(math=0;math<2;math++)
        evaluate(s,"2+3",mode,angle,math,32768);
    for(n=0;n<sizeof cases/sizeof cases[0];n++) {
        evaluate(s,cases[n],0,0,1,32768);
        evaluate(s,cases[n],0,0,1,1);
    }
    memset(longtext,' ',sizeof longtext); longtext[0]='1';longtext[4096]=0;
    evaluate(s,longtext,0,0,1,32768);longtext[4096]=' ';longtext[4097]=0;
    evaluate(s,longtext,0,0,1,32768);
    evaluate(s,NULL,0,0,1,32768);evaluate(NULL,"1",0,0,1,32768);
    evaluate(s,"9->A",6,0,1,32768);evaluate(s,"9->A",0,3,1,32768);
    for(n=0;n<128;n++) {
        memset(output,0xa5,sizeof output);length=7;position=7;
        assert(fxsim_encode_expression_mode("2+3",0,output+1,n,&length,&position)<=0);
        assert(output[0]==0xa5 && output[n+1]==0xa5);
    }
    fxsim_reset(s);fxsim_reset(NULL);fxsim_destroy(s);fxsim_destroy(NULL);
    puts("simulator sanitizer smoke PASS");return 0;
}
"""


def audit_sources(names, library):
    # Scan code rather than comments/string literals. Firmware constants and
    # lookup descriptors are expected; original execution/interpreters are not.
    forbidden = []
    for name in names:
        source = (ROOT / name).read_text()
        code = re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|'
                      r"'(?:\\.|[^'\\])*'", " ", source, flags=re.S)
        for pattern in (r"\b(?:float|double|_Float\d+|__float128)\b",
                        r"\b(?:atof|strtof|strtod|coreRun|core_run|harness_run)\s*\(",
                        r"\b(?:fopen|freopen|open|creat|unlink|system|execve)\s*\("):
            if re.search(pattern, code):
                forbidden.append({"source": name, "pattern": pattern})
    symbols = run(["nm", "-D", "--undefined-only", str(library)])
    for name in ("sin", "cos", "tan", "asin", "acos", "atan", "atan2", "sqrt",
                 "pow", "exp", "log", "log10", "strtod", "core_run", "harness_run"):
        if re.search(r"\b" + name + r"(?:@|\s|$)", symbols):
            forbidden.append({"undefined_symbol": name})
    assert not forbidden, forbidden
    assert not any("/nxu8/" in n or "/SimU8/" in n for n in names), names
    return {"linked_C_sources": len(names), "forbidden_matches": forbidden,
            "undefined_symbols": symbols}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-dir", type=Path,
                        default=ROOT / "analysis/build/simulator-safety")
    parser.add_argument("--library", type=Path)
    parser.add_argument("--skip-sanitizers", action="store_true")
    args = parser.parse_args()
    build = args.build_dir.resolve(); build.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy(); tmp = build / "compiler-tmp"; tmp.mkdir(exist_ok=True)
    env["TMPDIR"] = str(tmp)
    names = sources()
    inputs = implementation_inputs(ROOT, names) + ["csrc/CMakeLists.txt",
        "tools/c_build_inputs.py", str(Path(__file__).relative_to(ROOT))]
    pins = {n: sha(ROOT / n) for n in sorted(set(inputs))}
    commands = []
    library = args.library.resolve() if args.library else build / "simulator-safety.so"
    if not args.library:
        command = ["gcc", "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
            "-fPIC", "-shared", "-I", str(ROOT / "csrc"),
            *[str(ROOT/n) for n in names], "-o", str(library)]
        commands.append(command); run(command, env=env)
    artifact_before = sha(library)
    safety = Safety(library)
    failure = None
    try:
        for name in ("encoder_boundaries", "clients_and_errors", "transactions", "fuzz"):
            before = safety.checks
            getattr(safety, name)()
            safety.groups[name] = safety.checks - before
    except Exception as error:
        failure = {"type": type(error).__name__, "message": str(error)}
    finally:
        safety.close()
    source_audit = audit_sources(names, library)
    sanitizer = {"status": "not run"}
    if not failure and not args.skip_sanitizers:
        smoke = build / "sanitizer_smoke.c"; smoke.write_text(SMOKE)
        exe = build / "sanitizer_smoke"
        command = ["gcc", "-std=c99", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
            "-fno-omit-frame-pointer", "-fsanitize=address,undefined",
            "-I", str(ROOT / "csrc"), str(smoke), *[str(ROOT/n) for n in names],
            "-o", str(exe)]
        commands.append(command); run(command, env=env)
        sanenv = env.copy(); sanenv["ASAN_OPTIONS"] = "detect_leaks=1:halt_on_error=1"
        sanenv["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
        exe_before = sha(exe)
        output = run([str(exe)], env=sanenv)
        trace = build / "runtime-files.trace"
        sanenv["ASAN_OPTIONS"] = "detect_leaks=0:halt_on_error=1"
        run(["strace", "-f", "-o", str(trace), "-e",
            "trace=open,openat,creat,unlink,unlinkat,rename,renameat,mkdir,mkdirat,truncate",
            str(exe)], env=sanenv)
        writes = [line for line in trace.read_text().splitlines()
                  if re.search(r"(?:O_WRONLY|O_RDWR|O_CREAT|creat\(|unlink|rename|mkdir|truncate)", line)]
        assert not writes, writes
        assert sha(exe) == exe_before, "Sanitizer executable drift"
        sanitizer = {"status": "PASS", "output": output,
                     "binary_sha256": exe_before, "filesystem_writes": writes,
                     "trace_sha256": sha(trace)}
    drift = {n: sha(ROOT/n) for n,h in pins.items() if sha(ROOT/n) != h}
    artifact_after = sha(library)
    report = {"status": "FAIL" if failure or drift or artifact_before != artifact_after else "PASS",
        "checks": safety.checks, "calls": safety.calls, "groups": safety.groups,
        "failure": failure, "source_inputs": pins, "source_drift": drift,
        "library": str(library), "library_before": artifact_before,
        "library_after": artifact_after, "commands": commands,
        "source_audit": source_audit, "sanitizer": sanitizer,
        "scope": "Application boundary safety, client examples, independent-session "
                 "transaction/isolation checks, ASan/UBSan and no-filesystem-write smoke. "
                 "No original-ROM parity or complete key/UI transaction claim."}
    path = build / "report.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k:report[k] for k in ("status","checks","calls","groups","failure",
                                         "source_drift","sanitizer")}, indent=2))
    assert report["status"] == "PASS", str(path)


if __name__ == "__main__":
    main()
