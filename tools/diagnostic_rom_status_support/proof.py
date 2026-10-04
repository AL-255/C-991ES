#!/usr/bin/env python3
"""Read-only recomputation of a diagnostic proof's archived observations.

This does not execute either implementation. It checks the pinned artifact
custody, archived original transactions/RAM, and recorded cross-build agreement.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[2]


def digest(value):
    return hashlib.sha256(value).hexdigest()


def require(condition, description):
    if not condition:
        raise ValueError(description)


def transactions(image, fault_at=0, sample=0x44, retention_fault=False):
    data = bytearray()
    iteration = 0
    for bank, limit, base in [(8, 65536, 0), (1, 65532, 65536)]:
        if bank == 1:
            data.extend(bytes([4, 0, 0, 0, 0x5a]))
        for address in range(limit):
            iteration += 1
            value = image[base + address] if base + address < len(image) else 0
            sampled = sample if iteration == fault_at else 0x44
            data.extend(bytes([1, bank, address & 255, address >> 8, value,
                               2, 0, 0, 0, 0x44, 3, 0, 0, 0, sampled]))
            if (sampled & 0xf4) != 0x44:
                return bytes(data), 0, iteration
    data.extend(bytes([5, 0, 0, 0, 0x5b if retention_fault else 0x5a]))
    return bytes(data), 0 if retention_fault else 0xa5, iteration


def verify(report, folder):
    require(report['status'] == 'pass', 'Report is not successful')
    before, after = report['source_pins_before'], report['source_pins_after']
    require(before == after, 'Source pin drift within execution')
    for relative, wanted in before.items():
        require(digest((ROOT / relative).read_bytes()) == wanted, 'Current source pin mismatch: ' + relative)
    require(report['artifacts_before'] == report['artifacts_after'], 'Artifact pin drift within execution')
    for name, wanted in report['artifacts_before'].items():
        require(digest((folder / name).read_bytes()) == wanted, 'Compiled artifact mismatch: ' + name)
    fixture = json.loads((ROOT / 'analysis/native-fixtures/diagnostic-rom-status/inputs.json').read_text())
    recipes = {recipe['id']: recipe for recipe in fixture['original_recipes']}
    rows = report['original_rows']
    require(len(rows) == report['original_executions'] == len(recipes) == 10, 'Original execution census differs')
    require(len({row['id'] for row in rows}) == len(rows), 'Duplicate original observation')
    stock = (ROOT / 'firmware/fx-991es-plus-c-ver4.bin').read_bytes()
    observed_digests = {}
    for row in rows:
        require(row['id'] in recipes, 'Unregistered original observation')
        recipe = recipes[row['id']]
        image = bytearray(stock)
        for patch in recipe['rom_patches']:
            require(not 0x7334 <= patch['address'] < 0x7382, 'Modified original instruction')
            image[patch['address']] ^= patch['xor']
        require(digest(image) == row['rom_sha256'], 'Image recipe mismatch')
        archived = (folder / row['stream_file']).read_bytes()
        expected, returned, count = transactions(image)
        require(archived == expected, 'Complete archived transaction sequence differs')
        require(len(archived) == 393206 * 5 and returned == row['return'] == 0xa5 and count == 131068,
                'Normal diagnostic return/count differs')
        require(digest(archived) == row['stream']['sha256'], 'Archived stream digest mismatch')
        actual_counts = {str(kind): 0 for kind in range(1, 6)}
        for kind, _, _, _ in struct.iter_unpack('<BBHB', archived):
            actual_counts[str(kind)] += 1
        require(actual_counts == row['stream']['kind_counts'], 'Transaction census differs')
        require(row['steps'] == 1310697 and row['callback'] == 0, 'Original execution terminal differs')
        require(not row['status_failure_branches_reached'], 'Native failure boundary relabeled')
        require(row['actual_frame_written_addresses'] == list(range(0x8de2, 0x8ded)),
                'Original frame-write exclusion differs')
        ram = bytearray((address * 17 + recipe['ram_seed'] * 29 + 0x5a) & 255 for address in range(65536))
        require(digest(ram) == row['initial_ram_sha256'], 'Authored initial RAM mismatch')
        registers = [(index * 13 + recipe['register_seed'] * 17) & 255 for index in range(16)]
        require(registers == row['initial_registers'], 'Authored initial registers mismatch')
        require(row['returned_registers'] == [0xa5] + registers[1:], 'Original preservation mismatch')
        ram[0x8de2:0x8dea] = bytes(registers[8:16])
        ram[0x8dea:0x8ded] = bytes([0xfe, 0xff, 2])
        archived_ram = (folder / row['ram_file']).read_bytes()
        require(archived_ram == ram and digest(archived_ram) == row['ram_sha256'],
                'Archived original RAM differs, including the unwritten padding byte')
        observed_digests[row['id']] = digest(archived)
    builds = report['candidate_builds']
    require(set(builds) == {'O2', 'O3'}, 'Missing optimized build')
    require(builds['O2'] == builds['O3'], 'Recorded optimized builds disagree')
    for name, build in builds.items():
        pairs = build['original_pairs']
        require(len(pairs) == 10 and len({pair['id'] for pair in pairs}) == 10, 'Pair census differs')
        for pair in pairs:
            require(pair['id'] in observed_digests and pair['stream_sha256'] == observed_digests[pair['id']],
                    'Original/C pair digest differs')
            require(pair['status'] == 0 and pair['return'] == 0xa5 and pair['all_ordered_transactions_equal']
                    and pair['all_calculator_ram_equal_authored_input'], 'Pair observation differs')
            require(pair['software_resource_status'] == 0x44 and pair['software_resource_retention'] == 0x5a,
                    'Normal modeled resource storage differs')
        controls = build['modeled_resource_and_api_controls']
        require(len(controls) == build['control_count'] == 311, 'Modeled/API control census differs')
        for control in controls:
            kind = control['kind']
            expected = None
            if kind == 'modeled_status_byte':
                expected = transactions(stock, 1, control['sampled'])
            elif kind == 'modeled_boundary_status_fault':
                expected = transactions(stock, control['cycle'], 0x44 ^ (1 << control['changed_bit']))
            elif kind == 'modeled_final_ignored_bits':
                expected = transactions(stock, 131068, control['sampled'])
            elif kind == 'modeled_retention_corruption':
                expected = transactions(stock, retention_fault=True)
            elif kind in ('modeled_unmapped_rom', 'modeled_null_zero_size_rom'):
                expected = transactions(b'')
            elif kind.startswith('unavailable_'):
                require(control['status'] == -2, 'Missing resource relabeled as firmware failure')
            elif kind == 'invalid_platform':
                require(control['status'] == -1, 'Invalid input admitted')
            elif kind == 'actual_storage_roundtrip':
                require(control['readback'] == control['status_byte'] | control['retention_byte'] << 8,
                        'Actual storage roundtrip differs')
            else:
                raise ValueError('Unrecognized control kind')
            if expected is not None:
                data, returned, reads = expected
                require(digest(data) == control['stream_sha256'] and returned == control['return']
                        and reads == control['rom_reads'], 'Modeled control digest/return/count differs')
    boundary = report['evidence_boundaries']
    require(boundary['native_success_only'] and not boundary['native_failure_branches_executed']
            and not boundary['original_cpu_register_pc_patching_after_entry']
            and boundary['composed_71ec_screen_not_in_this_test'] and not boundary['full_firmware_complete'],
            'Evidence boundary changed')
    return {'source_pins': len(before), 'compiled_artifacts': len(report['artifacts_before']),
            'archived_original_streams': len(rows), 'archived_original_ram_images': len(rows),
            'original_candidate_pairs': 20, 'recorded_modeled_controls_per_build': 311,
            'all_recorded_optimized_outputs_equal': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    args = parser.parse_args()
    report_path = args.report.resolve()
    report = json.loads(report_path.read_text())
    summary = verify(report, report_path.parent)
    mutations = []
    altered = copy.deepcopy(report)
    first = next(iter(altered['source_pins_before']))
    altered['source_pins_before'][first] = '0' * 64
    altered['source_pins_after'][first] = '0' * 64
    mutations.append(('source_pin', altered))
    altered = copy.deepcopy(report)
    altered['artifacts_before']['O3.so'] = altered['artifacts_after']['O3.so'] = '0' * 64
    mutations.append(('artifact_pin', altered))
    altered = copy.deepcopy(report)
    altered['original_rows'].pop()
    mutations.append(('missing_original_row', altered))
    altered = copy.deepcopy(report)
    altered['original_rows'][0]['stream']['sha256'] = '0' * 64
    mutations.append(('archived_stream_pin', altered))
    altered = copy.deepcopy(report)
    altered['candidate_builds']['O3']['original_pairs'][0]['return'] = 0
    mutations.append(('cross_build_return', altered))
    altered = copy.deepcopy(report)
    altered['evidence_boundaries']['native_failure_branches_executed'] = True
    mutations.append(('native_failure_claim', altered))
    rejected = []
    for name, altered in mutations:
        try:
            verify(altered, report_path.parent)
        except ValueError:
            rejected.append(name)
        else:
            raise AssertionError('Custody checker admitted ' + name)
    output = {'schema': 1, 'status': 'pass', 'kind': 'read-only archived evidence recomputation; no executions',
              'parent_report': str(report_path), 'parent_report_sha256': digest(report_path.read_bytes()),
              'checker_sha256': digest(Path(__file__).read_bytes()), 'checks': summary,
              'negative_custody_controls_rejected': rejected,
              'native_failure_execution_claim': False, 'full_firmware_complete': False}
    target = report_path.parent / 'custody.json'
    target.write_text(json.dumps(output, indent=2) + '\n')
    print(json.dumps({'status': 'pass', 'custody': str(target), 'sha256': digest(target.read_bytes()),
                      'negative_controls': len(rejected)}, indent=2))


if __name__ == '__main__':
    main()
