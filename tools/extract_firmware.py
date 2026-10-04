#!/usr/bin/env python3
"""Recover calculator code memory from the bundled Ver.4.00 installer.

Requires Python 3, 7z, and objdump. Does not execute any Windows code.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile


INSTALLER = "fx-991ES PLUS C Emulator Ver.4.00.exe"
PAYLOAD = "fx_991es_plus_c_emulator.exe"
LOADERS = (0x414C20, 0x428C10, 0x43C9B0, 0x450860, 0x4649B0, 0x4785C0)
WRITE_CODE_IAT = 0x4841EC
MEMORY_SIZE = 0x30000
PAYLOAD_SHA256 = "ae338dbecd5f2723cfc0f6415c3f5702710ab7199b014f39b2fac4b36bd71c79"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def instructions(executable, start):
    listing = run("objdump", "-d", "-Mintel", f"--start-address={start}",
                  str(executable))
    for line in listing.splitlines():
        match = re.match(r"\s*([0-9a-f]+):\s+(?:[0-9a-f]{2}\s+)+\t(\w+)\s*(.*)", line)
        if match:
            address, op, operands = match.groups()
            yield int(address, 16), op, operands.strip()
            if op == "ret":
                return


def reconstruct(executable):
    rom = bytearray(MEMORY_SIZE)  # SetCodeMemoryDefaultCode(0)
    written = bytearray(MEMORY_SIZE)
    records = []
    counts = []
    aliases = {}
    for full, short, low, high in (("eax", "ax", "al", "ah"),
                                   ("ebx", "bx", "bl", "bh"),
                                   ("ecx", "cx", "cl", "ch"),
                                   ("edx", "dx", "dl", "dh")):
        for name, shift, bits in ((full, 0, 32), (short, 0, 16),
                                  (low, 0, 8), (high, 8, 8)):
            aliases[name] = full, shift, bits
    aliases["esi"] = "esi", 0, 32

    for start in LOADERS:
        registers = {}
        local = {}
        stack = []
        active = False
        count = 0

        def get_register(name):
            full, shift, bits = aliases[name]
            value, known = registers.get(full, (0, 0))
            mask = ((1 << bits) - 1) << shift
            if known & mask != mask:
                raise ValueError(f"Uninitialized register {name} at {address:#x}")
            return (value & mask) >> shift

        def set_register(name, value):
            full, shift, bits = aliases[name]
            old, known = registers.get(full, (0, 0))
            mask = ((1 << bits) - 1) << shift
            registers[full] = (old & ~mask | (value << shift) & mask, known | mask)

        def read(operand):
            if operand in aliases:
                return get_register(operand)
            return int(operand, 0)

        for address, op, operands in instructions(executable, start):
            if not active:
                if op == "mov" and operands == f"esi,DWORD PTR ds:{WRITE_CODE_IAT:#x}":
                    active = True
                continue
            # The only subsequent direct call is the stack-cookie check.
            if op == "call" and operands != "esi":
                if stack:
                    raise ValueError("Unconsumed arguments at end of loader")
                break
            if op == "pop":
                continue
            if op == "mov" and operands == "ecx,DWORD PTR [ebp-0x4]":
                continue  # Stack cookie; never part of the ROM.
            if op == "xor" and operands == "ecx,ebp":
                continue
            if op == "lea":
                match = re.fullmatch(r"(eax|ecx|edx),\[ebp-(0x[0-9a-f]+)\]", operands)
                if not match:
                    raise ValueError(f"Unexpected lea at {address:#x}: {operands}")
                set_register(match[1], -int(match[2], 16) & 0xFFFFFFFF)
            elif op == "mov":
                dest, source = operands.split(",", 1)
                match = re.fullmatch(r"(BYTE|WORD|DWORD) PTR \[ebp-(0x[0-9a-f]+)\]", dest)
                if match:
                    size = {"BYTE": 1, "WORD": 2, "DWORD": 4}[match[1]]
                    offset = -int(match[2], 16) & 0xFFFFFFFF
                    value = read(source) & ((1 << (size * 8)) - 1)
                    for i, byte in enumerate(value.to_bytes(size, "little")):
                        local[offset + i] = byte
                else:
                    set_register(dest, read(source))
            elif op == "xor":
                dest, source = operands.split(",", 1)
                if dest != source:
                    raise ValueError(f"Unexpected xor at {address:#x}")
                set_register(dest, 0)
            elif op == "push":
                stack.append(read(operands))
            elif op == "call" and operands == "esi":
                if len(stack) != 3:
                    raise ValueError(f"Expected three WriteCodeMemory arguments at {address:#x}")
                pointer, size, target = stack
                stack.clear()
                if not 0 < size <= 16 or not 0 <= target < target + size <= MEMORY_SIZE:
                    raise ValueError(f"Invalid ROM write at {address:#x}")
                data = bytes(local[pointer + i] for i in range(size))
                if any(written[target:target + size]):
                    raise ValueError(f"Overlapping ROM write at {target:#x}")
                rom[target:target + size] = data
                written[target:target + size] = b"\1" * size
                records.append((target, size))
                count += 1
                for reg in ("eax", "ecx", "edx"):
                    registers.pop(reg, None)  # Volatile across stdcall.
            else:
                raise ValueError(f"Unexpected instruction at {address:#x}: {op} {operands}")
        if not active or not count:
            raise ValueError(f"Missing ROM loader at {start:#x}")
        counts.append({"virtual_address": hex(start), "writes": count})

    ranges = []
    for address, flag in enumerate(written):
        if flag and (address == 0 or not written[address - 1]):
            begin = address
        if flag and (address == MEMORY_SIZE - 1 or not written[address + 1]):
            ranges.append({"start": hex(begin), "end_exclusive": hex(address + 1)})
    return bytes(rom), {
        "loader_functions": counts,
        "write_count": len(records),
        "write_sizes": dict(sorted(Counter(size for _, size in records).items())),
        "explicitly_written_bytes": sum(written),
        "written_ranges": ranges,
        "highest_written_address": hex(max(target + size - 1 for target, size in records)),
        "unwritten_fill_byte": "0x00",
    }


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer", type=Path, default=root / INSTALLER)
    parser.add_argument("--output", type=Path, default=root / "firmware")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="casio-firmware-") as temporary:
        work = Path(temporary)
        run("7z", "x", "-y", f"-o{work / 'msi'}", str(args.installer.resolve()), "Data1.cab")
        run("7z", "x", "-y", f"-o{work / 'payload'}", str(work / "msi/Data1.cab"), PAYLOAD)
        executable = work / "payload" / PAYLOAD
        if sha256(executable.read_bytes()) != PAYLOAD_SHA256:
            raise ValueError("Unrecognized emulator payload; loader addresses are version-specific")
        code_memory, metadata = reconstruct(executable)
        # The highest supplied ROM byte is 0x1ffff. The emulator also
        # allocates an empty third 64 KiB bank; keep that separately.
        firmware_size = int(metadata["highest_written_address"], 16) + 1
        rom = code_memory[:firmware_size]
        metadata.update({
            "installer": args.installer.name,
            "installer_sha256": sha256(args.installer.read_bytes()),
            "payload": PAYLOAD,
            "payload_sha256": sha256(executable.read_bytes()),
            "firmware_file": "fx-991es-plus-c-ver4.bin",
            "firmware_size": len(rom),
            "firmware_sha256": sha256(rom),
            "firmware_address_range": f"0x00000-{firmware_size - 1:#x}",
            "code_memory_file": "fx-991es-plus-c-ver4-code-memory.bin",
            "code_memory_size": len(code_memory),
            "code_memory_sha256": sha256(code_memory),
            "code_memory_address_range": "0x00000-0x2ffff",
        })
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / metadata["firmware_file"]).write_bytes(rom)
    (args.output / metadata["code_memory_file"]).write_bytes(code_memory)
    (args.output / "extraction.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
