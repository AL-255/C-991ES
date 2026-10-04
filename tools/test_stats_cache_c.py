#!/usr/bin/env python3
"""Verify native statistics moment-cache copies and every persistent byte."""
import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from nxu8.machine import Machine
from c_verification import write_report


class Cache(C.Structure):
    _fields_ = [('records', C.c_uint8 * 80)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--random-cases', type=int, default=1000)
    args = parser.parse_args()
    build = ROOT / 'analysis/build/stats-cache'
    build.mkdir(parents=True, exist_ok=True)
    library = build / 'fx-stats-cache.so'
    sources = ['csrc/stats/fx_stats_cache.c']
    subprocess.run(['gcc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-pedantic',
                    '-fPIC', '-shared', *(str(ROOT / p) for p in sources), '-o', str(library)], check=True)
    lib = C.CDLL(str(library))
    lib.fx_stats_cache_load.argtypes = [C.POINTER(C.c_uint8), C.POINTER(Cache)]
    lib.fx_stats_cache_store.argtypes = [C.POINTER(C.c_uint8), C.POINTER(Cache)]
    rom = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    m = Machine(rom, build / 'stats-cache-oracle')
    rng = random.Random(0x118b2)
    counts = {}

    def run(direction, position, flag, seed):
        background = random.Random(seed).randbytes(65536)
        ram = (C.c_uint8 * 65536).from_buffer_copy(background)
        m.reset(); C.memmove(m.ram, background, 65536)
        ram[0x812a] = m.ram[0x812a] = flag
        cache = C.cast(C.byref(ram, position), C.POINTER(Cache))
        m.er(14, (position + 170) & 65535)
        m.call(0x118b2 if direction == 'load' else 0x118c4)
        if direction == 'load': lib.fx_stats_cache_load(ram, cache)
        else: lib.fx_stats_cache_store(ram, cache)
        actual, expected = bytes(ram), bytes(m.ram)
        assert actual[:0x8d00] == expected[:0x8d00] and actual[0x8dee:] == expected[0x8dee:], (direction, position, flag, seed)
        assert m.reg(0) == 0
        counts[direction + '_full_ram'] = counts.get(direction + '_full_ram', 0) + 1

    positions = [0x8010, 0x80ff, 0x812a, 0x8154, 0x8300, 0x83a8, 0x8a56]
    positions += [0x829e + offset for offset in range(-80, 81)]
    for direction in ['load', 'store']:
        for position in positions:
            for flag in [0, 1, 2, 255]: run(direction, position, flag, rng.getrandbits(64))
        for _ in range(args.random_cases):
            run(direction, rng.randrange(0x8000, 0x8c00), rng.randrange(256), rng.getrandbits(64))
    report = {'status': 'pass', 'rom_sha256': hashlib.sha256(rom).hexdigest(),
              'random_seed': '0x118b2', 'random_cases_per_direction': args.random_cases,
              'checks': counts, 'checks_total': sum(counts.values()),
              'scope': 'Original118b2/118c4 cache copy/flag semantics, overlapping aliases and full RAM excluding CPU stack8d00..8ded; no numeric interpretation of cached bytes'}
    write_report('analysis/c-verification/stats_cache.json', report,
                 sources + ['csrc/stats/fx_stats_cache.h', 'csrc/stats/fx_stats.h',
                            'csrc/numeric/fx_numeric.h', 'tools/c_verification.py'],
                 'tools/test_stats_cache_c.py')
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
