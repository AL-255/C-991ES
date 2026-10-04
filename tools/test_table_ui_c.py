#!/usr/bin/env python3
"""Fresh whole-D9EE and reset-to-TABLE differential proof of handwritten C.

The original machine receives only physical key pairs and an explicit ready
external poll device. The C implementation calculates, commits and paints every
TABLE body. Original RAM and return values are used only for comparisons.

Use --no-report for a private source tree or O3 replay. Canonical publication is
restricted to O2 and the current repository source tree. Saved-Math restoration,
parameter-calculus cancellation and pathological grid iterators remain outside
this bounded interaction proof; the existing TABLE corpus retains their gaps.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

SCRIPT_ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--optimization', choices=('O2', 'O3'), default='O2')
    parser.add_argument('--repository-root', type=Path, default=SCRIPT_ROOT,
                        help='Location of the original ROM, oracle tools and input recipes')
    parser.add_argument('--source-root', type=Path,
                        help='C source tree; defaults to the repository root')
    parser.add_argument('--build-dir', type=Path,
                        help='Diagnostic artifacts; defaults to analysis/build/table-ui-runtime')
    parser.add_argument('--no-report', action='store_true')
    args = parser.parse_args()
    repository = args.repository_root.resolve()
    source = (args.source_root or repository).resolve()
    if not args.no_report and (repository != SCRIPT_ROOT or source != repository or args.optimization != 'O2'):
        parser.error('Canonical publication requires the current repository sources at O2; use --no-report')
    build = (args.build_dir or repository / 'analysis/build/table-ui-runtime').resolve()
    build.mkdir(parents=True, exist_ok=True)
    support = Path(__file__).resolve().parent / 'table_ui_support'
    required = ('compile.py', 'evidence.py', 'whole.py', 'runtime.py', 'odd.py', 'transitions.py', 'adapter.c', 'native.c')
    inputs = {str(path): digest(path) for path in (source / 'csrc').rglob('*')
              if path.is_file() and (path.suffix in ('.c', '.h') or path.name == 'CMakeLists.txt')}
    inputs.update({str(support / name): digest(support / name) for name in required})
    inputs.update({str(path): digest(path) for path in (repository / 'tools').rglob('*')
                   if path.is_file() and path.suffix in ('.c', '.h', '.py')})
    for path in ('firmware/fx-991es-plus-c-ver4.bin', 'analysis/disassembly/complete.asm',
                 'analysis/native-fixtures/runtime/inputs.json',
                 'analysis/native-fixtures/table-controller-lifecycle/controller-final/collect.py'):
        inputs[str(repository / path)] = digest(repository / path)
    inputs[str(Path(__file__).resolve())] = digest(__file__)
    # Capture publication's complete dependency baseline before any compilation.
    sys.path.insert(0, str(repository / 'tools'))
    from c_verification import write_report
    for name in required:
        target = {'adapter.c': 'abi.c', 'native.c': 'runtime-native.c'}.get(name, name)
        shutil.copy2(support / name, build / target)
    (build / 'baseline-pins.json').write_text(json.dumps(inputs, indent=2) + '\n')
    source_link = build / 'csrc'
    if source_link.is_symlink():
        if source_link.resolve() != source / 'csrc':
            source_link.unlink()
    elif source_link.exists():
        raise ValueError('Build directory contains a non-symlink csrc directory')
    if not source_link.exists():
        source_link.symlink_to(source / 'csrc', target_is_directory=True)
    environment = dict(os.environ, FX_TABLE_REPOSITORY_ROOT=str(repository),
                       FX_TABLE_BUILD_ROOT=str(build))

    def run(script, *arguments):
        subprocess.run([sys.executable, str(build / script), *arguments], env=environment, check=True)

    run('compile.py', args.optimization)
    run('whole.py', args.optimization)
    for variant in ('single', 'two', 'linear'):
        run('runtime.py', args.optimization, variant)
    run('odd.py', args.optimization)
    run('transitions.py', args.optimization)
    paths = [build / ('proof-' + args.optimization + '.json')]
    paths += [build / ('runtime-' + variant + '-' + args.optimization) / 'proof.json'
              for variant in ('single', 'two', 'linear')]
    paths += [build / ('odd-' + args.optimization) / 'proof.json']
    paths += [build / ('transitions-' + args.optimization) / 'proof.json']
    reports = [json.loads(path.read_text()) for path in paths]
    expected = [(206, 880), (118, 354), (128, 384), (126, 378), (27, 54), (88, 352)]
    for report, (count, checks) in zip(reports, expected):
        if report.get('cases', report.get('observations')) != count or report['checks'] != checks:
            raise ValueError('A bounded proof cohort or checkpoint count changed')
        if report['failures'] or report['source_changes']:
            raise ValueError('A failing or changed-input proof cannot publish')
    changes = [path for path, value in inputs.items() if digest(path) != value]
    if changes:
        raise RuntimeError('Inputs changed during the combined proof: ' + str(changes))
    dependencies = set(inputs)
    for report in reports:
        dependencies.update(report['input_pins'])
    tested_inputs = {path: digest(path) for path in sorted(dependencies)}
    artifacts = {str(path): digest(path) for path in paths}
    for path in build.rglob('*'):
        if path.is_file() and path.suffix in ('.so', '.gz'):
            artifacts[str(path)] = digest(path)
    report = dict(status='pass', optimization=args.optimization, original_calls=324,
                  cases=693, checks=sum(row['checks'] for row in reports), failures=[], source_changes=[],
                  whole_D9EE_cases=206, reset_TABLE_sequences=3, reset_TABLE_checkpoints=372,
                  odd_address_cases=27, error_transition_cases=88, original_subordinate_outputs_supplied_to_C=False,
                  whole_D9EE_TABLE_bounded_interactions_complete=True, full_TABLE_mode_complete=False,
                  full_firmware_complete=False, tested_inputs_sha256=tested_inputs,
                  artifact_sha256=artifacts,
                  limits=['Only individually witnessed original CPU-frame writes are omitted. Numeric register scratch8000..80DB differences are inventoried in each detailed report.',
                          'The supplied whole-F12A CPU context is excluded only in the nine prepared physical-address controls; uninterrupted sequences use no context injection.',
                          'Saved-Math restoration, parameter-calculus cancellation, general odd/malformed SURD conversion and pathological grid iterators remain outside this bounded interaction proof.',
                          'Existing prepared TABLE reports retain120 matching native grid nonreturn prefixes; these are not deleted or recounted as whole-runtime successes.'],
                  cohort_reports=[str(path) for path in paths])
    (build / ('result-' + args.optimization + '.json')).write_text(json.dumps(report, indent=2) + '\n')
    if not args.no_report:
        sources = [str(Path(path).relative_to(repository)) for path in tested_inputs
                   if Path(path).is_relative_to(repository)
                   and (Path(path).suffix in ('.c', '.h', '.py', '.json', '.bin') or Path(path).name == 'CMakeLists.txt')
                   and not Path(path).is_relative_to(build)]
        # Analysis collectors/listings are explicitly pinned before and after,
        # while the standard writer captures analysis JSON dependencies only.
        external_analysis = {name: tested_inputs[str(repository / name)]
                             for name in sorted(set(sources))
                             if name.startswith('analysis/') and Path(name).suffix != '.json'}
        listing = 'analysis/disassembly/complete.asm'
        external_analysis[listing] = tested_inputs[str(repository / listing)]
        eligible = sorted(set(sources) - set(external_analysis))
        canonical = write_report('analysis/c-verification/table_ui.json', report, eligible,
                                 'tools/test_table_ui_c.py')
        canonical['tested_inputs_sha256'].update(external_analysis)
        (repository / 'analysis/c-verification/table_ui.json').write_text(json.dumps(canonical, indent=2) + '\n')
    print(json.dumps(dict(optimization=args.optimization, whole_D9EE_cases=206,
                          reset_TABLE_sequences=3, reset_TABLE_checkpoints=372,
                          odd_address_cases=27, error_transition_cases=88, checks=report['checks'], failures=0,
                          canonical_published=not args.no_report)))


if __name__ == '__main__':
    main()
