"""Read-only custody validation of fresh device-session proof archives.

This independent guard does not execute or modify either machine. Its own
source hash is recorded separately from the frozen differential worker.
"""
import base64
import gzip
import hashlib
import json
from pathlib import Path
import zlib


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def decode(record, name):
    value = zlib.decompress(base64.b64decode(record[name], validate=True))
    require(len(value) == 65536, f'{name}: expected complete RAM image')
    return value


def validate_archive(path, report):
    checkpoints, retained, completed = [], [], []
    with gzip.open(path, 'rt') as stream:
        for line in stream:
            record = json.loads(line)
            kind = record.get('type')
            if kind == 'host-only-retained-body':
                data = decode(record, 'ram_zlib_base64')
                require(hashlib.sha256(data).hexdigest() == record['ram_sha256'], 'retained RAM hash mismatch')
                require(record['native_completion_claim'] is False, 'fabricated native completion')
                retained.append({k:v for k,v in record.items() if k not in ('type','ram_zlib_base64')})
                continue
            if kind == 'native-completed-former-body-control':
                completed.append({k:v for k,v in record.items() if k != 'type'})
                continue
            require(kind is None, 'unknown archive record')
            c_ram = decode(record, 'c_ram_zlib_base64')
            native_ram = decode(record, 'native_ram_zlib_base64')
            frame = decode(record, 'frame_writes_zlib_base64')
            require(hashlib.sha256(c_ram).hexdigest() == record['ram_sha256'], 'C RAM hash mismatch')
            require(hashlib.sha256(native_ram).hexdigest() == record['native_ram_sha256'], 'original RAM hash mismatch')
            floor = record['minimum_sp']
            require(type(floor) is int and 0 <= floor <= 0x8dee, 'invalid witnessed stack floor')
            require(all(v in (0,1) and (not v or floor <= i < 0x8dee) for i,v in enumerate(frame)), 'invalid witnessed frame mask')
            require(sum(frame) == record['frame_bytes'], 'frame count mismatch')
            differences = [[i,a,b] for i,(a,b) in enumerate(zip(native_ram,c_ram)) if a != b and not frame[i]]
            require(differences == record['numeric_residuals'], 'forged or undocumented RAM difference')
            require(all(0x8000 <= row[0] < 0x80dc for row in differences), 'persistent RAM gap')
            require(not record['unexpected'] and not record['semantic'], 'failed checkpoint')
            require(record['native_stop'] == 100 and record['callback'] == record['native_callback'], 'original boundary/callback mismatch')
            require(record['native_pc'] in (0xd7ae,0xd9ee,0xc978,0xca7c,0xda58,
                0xd87e,0xd98e,0xd99e,0xc9e8,0xc9f4,0xd7b4,0xecaa,0xeca6,
                0x1d8d0,0x1d8a4,0xd0cc,0x53ce,0xcd66,0xf02c,0xe1be),
                'unrecognized original retained boundary')
            # The witness mask must never hide the specifically claimed
            # persistent result/editor/real-variable/PreAns/replay/imaginary
            # banks. MMIO and LCD already lie above the permitted frame area.
            require(c_ram[0x80dc:0x821c] == native_ram[0x80dc:0x821c]
                and c_ram[0x8226:0x8294] == native_ram[0x8226:0x8294]
                and c_ram[0x829e:0x83fe] == native_ram[0x829e:0x83fe]
                and c_ram[0x8408:0x846c] == native_ram[0x8408:0x846c],
                'protected persistent state mismatch')
            require(all(c_ram[0xf800+16*y+x] == native_ram[0xf800+16*y+x] for y in range(32) for x in range(12)), 'visible LCD mismatch')
            checkpoints.append({k:v for k,v in record.items() if k not in ('c_ram_zlib_base64','native_ram_zlib_base64','frame_writes_zlib_base64')})
    require(checkpoints == report['rows'], 'archive rows differ from report')
    require(len(checkpoints) == report['observations'], 'checkpoint count mismatch')
    require(retained == report['pending_bodies'], 'retained controls differ from report')
    require(completed == report['completed_former_body_controls'], 'completed controls differ from report')
    # Labels describe semantic boundaries and legitimately repeat at each
    # subsequent key wait. Archive position is the checkpoint identity.
    return {'checkpoints':len(checkpoints),'retained':len(retained),'completed':len(completed)}


def validate_report(report, expected_pins, variant_directory):
    require(report['input_pins'] == expected_pins and report['end_pins'] == expected_pins and not report['source_changes'], 'source closure/custody changed')
    require(all(digest(p) == h for p,h in expected_pins.items()), 'source differs from tested source')
    require(not report['failures'], 'failing variant cannot publish')
    directory = Path(variant_directory).resolve()
    require(report['optimization'] == directory.name, 'optimization identity mismatch')
    artifacts = {str(directory / p) for p in ('device-session.so','native/nxu8-harness.so','observations.jsonl.gz')}
    observed = {str(Path(p).resolve()):h for p,h in report['artifacts'].items()}
    require(set(observed) == artifacts, 'incomplete or foreign artifact closure')
    require(all(digest(p) == h for p,h in observed.items()), 'artifact changed')
    counts = validate_archive(directory / 'observations.jsonl.gz', report)
    require(all(digest(p) == h for p,h in observed.items()), 'artifact changed during archive validation')
    require(all(digest(p) == h for p,h in expected_pins.items()), 'source changed during archive validation')
    return counts
