#!/usr/bin/env python3
"""Print a chosen ROM interval, without claiming data bytes are instructions."""
import argparse
from pathlib import Path
from nxu8.decoder import Decoder

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('start', type=lambda x: int(x, 0))
parser.add_argument('end', type=lambda x: int(x, 0))
args = parser.parse_args()
rom = (Path(__file__).resolve().parents[1] / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
decoder = Decoder()
address = args.start
while address < args.end:
    instruction = decoder.decode(rom, address)
    print(instruction.line() if instruction else f'{address:06X}   {rom[address:address+2].hex()}   .word')
    address += instruction.size if instruction else 2
