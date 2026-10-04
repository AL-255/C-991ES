#!/usr/bin/env python3
"""Embed immutable firmware data for the high-level C ports; no code execution."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'csrc/data'
SHA256 = '28b5c3907a67426a1601dbf82ebf62b850333e889fcc958d698786d3e5f5fb7d'


def main():
    rom=(ROOT/'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    assert len(rom)==0x20000
    assert hashlib.sha256(rom).hexdigest()==SHA256
    image=rom+bytes(0x10000)
    OUT.mkdir(parents=True,exist_ok=True)
    header='''/* Generated immutable data; see tools/generate_rom_data.py. */
#ifndef FX_ROM_DATA_H
#define FX_ROM_DATA_H
#include <stddef.h>
#include <stdint.h>
#define FX_ROM_DATA_SIZE 0x30000u
extern const uint8_t fx_rom_data[FX_ROM_DATA_SIZE];
extern const size_t fx_rom_data_size;
extern const char fx_rom_sha256[];
#endif
'''
    (OUT/'fx_rom_data.h').write_text(header)
    lines=['/* Generated immutable data; C ports read constants, never execute these bytes. */',
           '#include "fx_rom_data.h"',
           'const size_t fx_rom_data_size = FX_ROM_DATA_SIZE;',
           f'const char fx_rom_sha256[] = "{SHA256}";',
           'const uint8_t fx_rom_data[FX_ROM_DATA_SIZE] = {']
    for p in range(0,len(rom),16):
        lines.append('    '+', '.join(f'0x{b:02x}' for b in rom[p:p+16])+',')
    lines.append('};\n')
    (OUT/'fx_rom_data.c').write_text('\n'.join(lines))
    (OUT/'manifest.json').write_text(json.dumps({'source':'firmware/fx-991es-plus-c-ver4.bin',
        'sha256':SHA256,'source_bytes':len(rom),'mapped_bytes':len(image),
        'zero_tail_bytes':0x10000,'purpose':'Read-only constants, packed fonts, tables and vectors. No interpreter or instruction execution in high-level C implementation.'},indent=2)+'\n')


if __name__=='__main__': main()
