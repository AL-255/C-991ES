#!/usr/bin/env python3
"""Run implemented C suites and audit coverage/provenance without claiming full parity."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SUITES = ('tokens', 'platform', 'boot', 'boot_events', 'persistent', 'diagnostic_contrast', 'result_classify', 'main_loop', 'boot_main_ui', 'runtime', 'runtime_equation_canonical', 'equation_workflow', 'equation_commit', 'coordinate_workspace', 'coordinate_surd_workspace', 'odd_result', 'rich_ui', 'eval_c4_integral', 'eval_c4_derivative', 'complex_surd_continuation', 'complex_surd_binary_workspace', 'numeric_c4_integral', 'numeric_c4_derivative', 'keys', 'key_dispatch', 'key_wait', 'key_controller', 'annunciator', 'cursor', 'editor', 'editor_construct', 'input_codec', 'input_prepare', 'input_recover', 'input_controller', 'ui_controller', 'error_display', 'error_event', 'menu_navigator', 'mode_setup', 'mode_bank_menu', 'numeric', 'numeric_transcend', 'numeric_power', 'numeric_root', 'numeric_logbase', 'numeric_calculus', 'numeric_integral', 'numeric_integral_storage', 'numeric_derivative', 'numeric_derivative_storage', 'numeric_surd_components', 'numeric_base', 'numeric_sexagesimal', 'numeric_solver', 'numeric_solver_stage', 'numeric_solve', 'numeric_random', 'numeric_quotient', 'raw_decimal', 'raw_rational', 'combinatorics', 'complex', 'complex_angles', 'complex_round', 'complex_dispatch', 'linalg', 'linalg_reduce', 'linalg_store', 'linalg_dispatch', 'stats', 'stats_value', 'stats_cache', 'stats_editor', 'stats_normal', 'trig', 'trig_math', 'trig_inverse', 'trig_hyperbolic', 'math_context', 'render', 'render_complex', 'render_pair', 'render_linalg', 'format', 'format_base', 'format_budget', 'eval', 'eval_complex', 'eval_variables', 'eval_calculus', 'eval_integral_physical', 'eval_continuous', 'eval_base', 'eval_sexagesimal', 'eval_coordinate', 'eval_storage', 'eval_finish', 'eval_environment', 'solve_controller', 'calc_scan', 'eval_random', 'eval_rich', 'eval_rich_unary', 'eval_rich_reduce', 'eval_rich_parser', 'eval_stats', 'solve_outer', 'table', 'table_controller', 'table_composition', 'table_ui', 'base_word', 'cli', 'safety')


# Keep the canonical full run at the established differential workloads.
VERIFICATION_ARGUMENTS = {
    'numeric': ('--random-cases', '5000'),
    'numeric_base': ('--random-cases', '8000', '--exhaustive-bin'),
    'stats_editor': ('--random-cases', '3000'),
    'stats_normal': ('--random-cases', '3000', '--random-tables', '200'),
}


def audit():
    scope = json.loads((ROOT / 'csrc/scope.json').read_text())
    issues = []
    results = {}
    for name in SUITES:
        path = ROOT / 'analysis/c-verification' / (name + '.json')
        if not path.exists():
            issues.append(f'{name}: no canonical verification report'); continue
        report = json.loads(path.read_text())
        if report.get('status') != 'pass': issues.append(f'{name}: report does not pass')
        inputs = report.get('tested_inputs_sha256', {})
        if not inputs: issues.append(f'{name}: missing tested-source hashes')
        for file, digest in inputs.items():
            p = ROOT / file
            if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest() != digest:
                issues.append(f'{name}: changed or missing tested input {file}')
        cases = report.get('cases', report.get('total_cases', report.get('checks_total', report.get('checks', 0))))
        if isinstance(cases, dict):
            cases = report.get('total_cases', report.get('checks_total', sum(cases.values())))
        if type(cases) is not int or cases < 0:
            issues.append(f'{name}: invalid reported check count')
            cases = 0
        results[name] = {'status': report.get('status'), 'cases': cases,
                         'pinned_inputs': len(inputs)}
    for requirement in scope['requirements']:
        if 'manifest' in requirement and not (ROOT / 'csrc' / requirement['manifest']).exists():
            issues.append(f"{requirement['id']}: missing implementation manifest")
    # Reject an accidental link or include of the original execution oracle.
    for p in (ROOT / 'csrc').rglob('*'):
        if p.suffix not in ('.c', '.h') or p.name == 'fx_rom_data.c': continue
        source = p.read_text()
        for forbidden in ('harness_run(', 'harness_init(', 'SimU8/', 'nxu8/machine'):
            if forbidden in source:
                issues.append(f'original execution dependency in {p.relative_to(ROOT)}: {forbidden}')
    requirements_complete = all(r['status'] == 'complete' for r in scope['requirements'])
    if scope['complete'] and not requirements_complete:
        issues.append('Completion flag contradicts pending requirements')
    result = {'implemented_subset_verified': not issues, 'full_firmware_complete': scope['complete'],
              'suites': results, 'total_reported_cases': sum(r['cases'] for r in results.values()),
              'requirements': [{k: r[k] for k in ('id', 'status')} for r in scope['requirements']],
              'issues': issues,
              'limitation': 'Routine-level finite checks and a partial expression pipeline. This does not establish full firmware or reset/key-sequence equivalence.'}
    out = ROOT / 'analysis/c-verification/aggregate.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return not issues


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--audit-only', action='store_true', help='Validate existing reports without running tests')
    args = ap.parse_args()
    if not args.audit_only:
        subprocess.run(['cmake', '-S', 'csrc', '-B', 'analysis/build/c-port',
                        '-DCMAKE_BUILD_TYPE=Release'], cwd=ROOT, check=True)
        subprocess.run(['cmake', '--build', 'analysis/build/c-port', '-j4'], cwd=ROOT, check=True)
        for suite in SUITES:
            command = [sys.executable, str(ROOT / 'tools' / f'test_{suite}_c.py')]
            command += VERIFICATION_ARGUMENTS.get(suite, ())
            subprocess.run(command, cwd=ROOT, check=True)
    return 0 if audit() else 1


if __name__ == '__main__': raise SystemExit(main())
