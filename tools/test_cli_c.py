#!/usr/bin/env python3
"""Compare the standalone CPU-free C executable's records, tokens and PBM with ROM output."""
import json
import random
import subprocess

from c_verification import ROOT, write_report
from nxu8.machine import Machine
from trace_natural_result import settings


def main():
    build = ROOT / 'analysis/build/c-port'
    subprocess.run(['cmake', '-S', str(ROOT / 'csrc'), '-B', str(build), '-DCMAKE_BUILD_TYPE=Release'], check=True)
    subprocess.run(['cmake', '--build', str(build), '-j4'], check=True)
    executable = build / 'fx991c'
    m = Machine((ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes(), ROOT / 'analysis/build/cli/oracle')
    rng = random.Random(0xb070)
    inputs = [bytes.fromhex('2898393938292d9839393729294f3939'), b'6\x4f2(1+2)',
              b'1\xae3', b'1\x4f3', b'1\xae2\xae3', b'\x81', b'\x82', b'\x98998)',
              b'0', b'1\x7499', b'1\x74\x6099', b'\xa030)', b'\xa045)', b'\xa215)',
              b'\xa030)+\xa160)', b'\xa045)\x4e\xa145)', b'\xa0\x982))',
              b'2^3', b'2^\x601', b'\x982)\x75', b'2\x76', b'3\xae2^2', b'30\x86',
              b'\xb0.5)', b'\xb1.5)', b'\xb21)', b'\xa0\xb0.5))', b'\xb0\x98.5))',
              b'\x6810)', b'\xa3\x81)', b'\xa3\x98.5))']
    for _ in range(100):
        a, b, c = (str(rng.randrange(1, 100)).encode() for _ in range(3))
        inputs.append(b'(' + a + b'\xae' + b + b'-\x98' + c + b'))')
    pbm = ROOT / 'analysis/c-verification/cli-last.pbm'
    for tokens in inputs:
        m.reset(); settings(m)
        for i, b in enumerate(tokens + b'\0'): m.ram[0x8200+i] = b
        m.word(0x8190, 0x8200); m.er(0, 0x8190); m.er(2, 0x8300); m.call(0x171f4)
        assert m.reg(0) == 0, tokens.hex()
        expected_record = bytes(m.ram[0x8300:0x8314]).hex()
        expected_consumed = m.word(0x8190) - 0x8200
        m.call(0xc034)
        # Compare the standalone formatter alphabet separately from B070's
        # alternate raw-character alphabet used for scientific suffixes.
        m.er(0, 0x8300); m.er(2, 0x8500); m.word(0x8dee, 0); m.call(0xc060)
        expected_tokens = bytes(m.ram[0x8500:0x8700]).split(b'\0', 1)[0].hex()
        # Recreate native evaluation context, since isolated formatting writes
        # numeric scratch that is not part of the ordinary controller entry.
        m.reset(); settings(m)
        for i, b in enumerate(tokens + b'\0'): m.ram[0x8200+i] = b
        m.word(0x8190, 0x8200); m.er(0, 0x8190); m.er(2, 0x8300); m.call(0x171f4)
        m.call(0xc034); m.er(0, 0x8300); m.call(0xb070); m.call(0x3cfc)
        frame = b''.join(bytes(m.ram[0xf800+16*y:0xf80c+16*y]) for y in range(32))
        actual = json.loads(subprocess.run([str(executable), '--eval', tokens.hex(), '--pbm', str(pbm)],
                                          check=True, capture_output=True, text=True).stdout)
        assert actual['eval_status'] == actual['format_status'] == actual['bitmap_status'] == 0
        assert (actual['record'], actual['consumed'], actual['tokens']) == (
                expected_record, expected_consumed, expected_tokens), (tokens.hex(), actual)
        assert pbm.read_bytes() == b'P4\n96 32\n' + frame, (tokens.hex(), 'standalone C PBM differs')
    for args in [[], ['--eval', 'z'], ['--eval', '0'], ['--format', 'ff'], ['--token', '100'],
                 ['--token', 'xyz'], ['--eval', '31', '--unknown'], ['--format', '0'*20, '--unknown']]:
        assert subprocess.run([str(executable), *args], capture_output=True).returncode == 2, args
    for tokens, status in [(b'1+', 2), (b'1\x4f0', 3), (b'\x9330', -1)]:
        proc = subprocess.run([str(executable), '--eval', tokens.hex()], capture_output=True, text=True)
        assert proc.returncode == 1 and json.loads(proc.stdout)['eval_status'] == status
    sources = [str(p.relative_to(ROOT)) for p in (ROOT / 'csrc').rglob('*')
               if p.suffix in ('.c', '.h') or p.name == 'CMakeLists.txt']
    report = write_report('analysis/c-verification/cli.json', {
        'cases': len(inputs) + 11, 'successful_expression_PBM_cases': len(inputs),
        'invalid_argument_cases': 8, 'evaluator_error_cases': 3,
        'comparison': 'Standalone executable JSON status,20-byte record,consumed pointer,formatter tokens and all96x32 PBM pixels versus original171F4/C034/C060/B070/3CFC.',
        'scope': 'Prepared ordinary Math COMP context; no reset/key UI, complex or other modes'},
        sources + ['tools/c_verification.py', 'tools/trace_natural_result.py'], 'tools/test_cli_c.py')
    print(json.dumps({k: v for k, v in report.items() if k != 'tested_inputs_sha256'}, indent=2))


if __name__ == '__main__': main()
