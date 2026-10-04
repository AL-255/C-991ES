#!/usr/bin/env python3
"""Run portable API bounds fuzzing under ASan and UBSan, without the ROM oracle."""
import json
import os
from pathlib import Path
import subprocess

from c_verification import ROOT, write_report


def main():
    build = ROOT / 'analysis/build/c-sanitized'
    subprocess.run(['cmake', '-S', str(ROOT / 'csrc'), '-B', str(build),
                    '-DFX_ENABLE_SANITIZERS=ON', '-DCMAKE_BUILD_TYPE=Debug'], check=True)
    subprocess.run(['cmake', '--build', str(build), '-j4'], check=True)
    env = os.environ.copy()
    # The execution host uses ptrace. LeakSanitizer cannot operate under it;
    # these APIs use caller-owned fixed buffers and allocate no heap objects.
    env['ASAN_OPTIONS'] = 'detect_leaks=0:halt_on_error=1'
    env['UBSAN_OPTIONS'] = 'halt_on_error=1:print_stacktrace=1'
    subprocess.run([str(build / 'fx991c_safety')], env=env, check=True)
    sources = [str(p.relative_to(ROOT)) for p in (ROOT / 'csrc').rglob('*')
               if p.suffix in ('.c', '.h') or p.name == 'CMakeLists.txt']
    report = write_report('analysis/c-verification/safety.json', {
        'cases': 140000, 'domain': 'Deterministic parser/formatter/glyph-line/ordinary-and-structured-editor/input-conversion/cursor-and-key bounds fuzzing plus long-literal and recursion boundaries',
        'comparison': 'API contracts and canaries under address/undefined-behavior instrumentation; no original firmware execution',
        'sanitizers': ['AddressSanitizer', 'UndefinedBehaviorSanitizer'],
        'leak_sanitizer': 'Disabled because host ptrace is incompatible; tested code uses caller-owned fixed buffers',
        'scope': 'Memory/undefined behavior check of implemented APIs; not a behavioral parity proof'},
        sources + ['tools/c_verification.py'], 'tools/test_safety_c.py')
    print(json.dumps({k: v for k, v in report.items() if k != 'tested_inputs_sha256'}, indent=2))


if __name__ == '__main__': main()
