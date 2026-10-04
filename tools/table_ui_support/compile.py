#!/usr/bin/env python3
import os
"""Compile the private whole-TABLE candidate with strict diagnostics."""
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(os.environ['FX_TABLE_BUILD_ROOT'])
ROOT = Path(os.environ['FX_TABLE_REPOSITORY_ROOT'])
optimization = sys.argv[1] if len(sys.argv) > 1 else 'O2'
if optimization not in ('O2', 'O3'):
    raise SystemExit('Optimization must be O2 or O3')
cmake_sources = (HERE / 'csrc/CMakeLists.txt').read_text().split(
    'add_library(fx991_firmware STATIC', 1)[1].split(')', 1)[0]
sources = list(dict.fromkeys(re.findall(r'([\w/]+\.c)', cmake_sources) + ['table/fx_table_body.c']))
output = HERE / ('table-ui-' + optimization + '.so')
subprocess.run([
    'gcc', '-std=c99', '-' + optimization, '-Wall', '-Wextra', '-Werror',
    '-shared', '-fPIC', '-Wl,--no-undefined', '-I' + str(HERE / 'csrc'),
    *[str(HERE / 'csrc' / name) for name in sources], str(HERE / 'abi.c'),
    str(ROOT / 'tools/runtime_support/adapter.c'), '-o', str(output),
], check=True)
print(output)
