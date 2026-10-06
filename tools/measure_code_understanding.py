#!/usr/bin/env python3
"""Measure documented instruction understanding without writing reports or history."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LISTING = ROOT / 'analysis/disassembly/complete.asm'
EXPECTED_LISTING_SHA256 = 'f9e715eee6fb521da0005c6c8967baa3e8141a2785898033f07dca143c41b19c'
EXPECTED_INSTRUCTION_COUNT = 46094


def measure():
    listing_digest = hashlib.sha256(LISTING.read_bytes()).hexdigest()
    if listing_digest != EXPECTED_LISTING_SHA256:
        raise ValueError('Disassembly changed; explicitly revise the documented denominator before reporting progress')
    instructions = set()
    boundaries = {0x20000}
    for line in LISTING.read_text().splitlines():
        if len(line) < 6 or any(c not in '0123456789ABCDEF' for c in line[:6]):
            continue
        address = int(line[:6], 16)
        boundaries.add(address)
        if '.db' not in line:
            instructions.add(address)
    if len(instructions) != EXPECTED_INSTRUCTION_COUNT:
        raise ValueError('Instruction count differs from the documented denominator')
    covered = set()
    subsystems = {}
    provenance = {}
    entries = []
    ledgers = sorted((ROOT / 'csrc').rglob('understood_ranges.json'))
    if not ledgers:
        raise ValueError('No understood-range ledgers')
    for ledger in ledgers:
        content = json.loads(ledger.read_text())
        subset = set()
        for entry in content['ranges']:
            start, end = int(entry['start'], 16), int(entry['end'], 16)
            if start not in instructions or end not in boundaries or start >= end:
                raise ValueError(f'{ledger.relative_to(ROOT)}: invalid instruction span {entry}')
            if not entry.get('scope'):
                raise ValueError(f'{ledger}: missing semantic scope')
            source = ROOT / entry['source']
            if not source.is_file():
                raise ValueError(f'{ledger}: missing semantic source {entry["source"]}')
            span = {address for address in instructions if start <= address < end}
            subset.update(span)
            entries.append(dict(entry, instruction_count=len(span), ledger=str(ledger.relative_to(ROOT))))
            provenance[entry['source']] = hashlib.sha256(source.read_bytes()).hexdigest()
        covered.update(subset)
        subsystems[str(ledger.relative_to(ROOT))] = len(subset)
        provenance[str(ledger.relative_to(ROOT))] = hashlib.sha256(ledger.read_bytes()).hexdigest()
    provenance[str(LISTING.relative_to(ROOT))] = listing_digest
    provenance['tools/measure_code_understanding.py'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return {
        'metric': 'code understood: unique documented understood instruction addresses divided by all decoded instruction addresses',
        'understood_instructions': len(covered),
        'total_disassembled_instructions': len(instructions),
        'percentage': round(100 * len(covered) / len(instructions), 2),
        'interpretation': 'Conservative documented lower bound. Each entry records an understood semantic span; this is not a test-coverage or firmware-completion percentage. Shared spans are counted once. ROM data and undecoded bytes are excluded.',
        'denominator_policy': 'The current complete.asm instruction listing is pinned by SHA256; a changed listing requires an explicit denominator revision.',
        'per_ledger_instruction_counts_before_overlap_removal': subsystems,
        'ranges': entries,
        'inputs_sha256': provenance,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.parse_args()
    report = measure()
    summary = {key: report[key] for key in ('understood_instructions', 'total_disassembled_instructions', 'percentage', 'interpretation')}
    print(json.dumps(summary, indent=2))


if __name__ == '__main__': main()
