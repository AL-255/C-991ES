#!/usr/bin/env python3
"""Fresh prepared polynomial UI parity, with input-only recipes and closed pins.

The original ROM runs only in the passive test oracle. The C controller runs
first and receives the same authored initial state and physical keys. Outputs
from either implementation never become the other implementation's inputs.
"""
import argparse
import base64
import copy
import ctypes as C
import datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid
import zlib


CANONICAL_FIXTURE = "analysis/native-fixtures/polynomial-equation-workflow/inputs.json"
CANONICAL_FIXTURE_SHA256 = "7fae86f17853cbd8a32b43441c06e8512d79cbcc24f2ed997088db9882ad150a"


def publication_allowed(root, source_root, tool, fixture, fixture_hash, optimization):
    return (source_root == root and tool == root / "tools/test_polynomial_equation_workflow_c.py" and
            fixture == root / CANONICAL_FIXTURE and fixture_hash == CANONICAL_FIXTURE_SHA256 and
            optimization == "both")


def imported_tool_paths(root):
    result = set()
    for module in tuple(sys.modules.values()):
        name = getattr(module, "__file__", None)
        if name:
            path = Path(name).resolve()
            if path.is_file() and path.suffix == ".py" and path.is_relative_to(root / "tools"):
                result.add(path)
    return result


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def changes(pins):
    return {str(p): {"before": h, "after": digest(p)}
            for p, h in pins.items() if digest(p) != h}


def packed(data):
    return base64.b64encode(zlib.compress(bytes(data))).decode("ascii")


def object_keys(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= value.keys() or \
            value.keys() - set(required) - set(optional):
        raise ValueError("Invalid fixture object keys")


def uint(value, upper=255):
    if type(value) is not int or not 0 <= value <= upper:
        raise ValueError("Invalid unsigned fixture integer")


def validate_fixture(recipe):
    object_keys(recipe, ("schema", "basis", "seed_fixture", "seed_fixture_sha256",
                         "seed_key", "scenarios"))
    if recipe["schema"] != 1 or not isinstance(recipe["basis"], str) or \
            not re.fullmatch(r"[a-f0-9]{64}", recipe["seed_fixture_sha256"]):
        raise ValueError("Invalid fixture schema/provenance")
    if not isinstance(recipe["scenarios"], list) or not recipe["scenarios"]:
        raise ValueError("No authored scenarios")
    labels = set()
    for row in recipe["scenarios"]:
        common = ("label", "workflow", "selector", "math")
        kind = row.get("workflow")
        if kind == "success":
            object_keys(row, common + ("coefficients", "replay_steps"),
                        ("solve_key", "commit_key", "post_keys",
                         "post_commit_navigation_keys", "require_stored_kinds"))
        elif kind == "error":
            object_keys(row, common + ("coefficients", "cancel_at",
                                       "ignored_token", "recovery_token"))
        elif kind == "navigation":
            object_keys(row, common + ("coefficients", "replay_steps", "busy",
                                       "navigation_keys"))
        elif kind == "commit-prefix":
            object_keys(row, common + ("page", "column", "source", "source_bytes"))
            uint(row["source"], 65526)
            if row["source"] < 0x8000 or not re.fullmatch(r"[a-f0-9]{20}", row["source_bytes"]):
                raise ValueError("Invalid authored copy source")
            if row["page"] not in range(1, 1 + (2 if row["selector"] == 4 else 1)) or \
                    row["column"] not in (1, 2, 3):
                raise ValueError("Invalid authored grid position")
        else:
            raise ValueError("Unknown workflow")
        if not isinstance(row["label"], str) or not row["label"] or row["label"] in labels:
            raise ValueError("Invalid or duplicate label")
        labels.add(row["label"])
        if type(row["selector"]) is not int or row["selector"] not in (3, 4) or \
                type(row["math"]) is not int or row["math"] not in (0, 1):
            raise ValueError("Invalid polynomial admission")
        if kind != "commit-prefix":
            expected_count = 0 if kind == "navigation" else row["selector"]
            if not isinstance(row["coefficients"], list) or len(row["coefficients"]) != expected_count:
                raise ValueError("Coefficient arity mismatch")
            for text in row["coefficients"]:
                if not isinstance(text, str) or not re.fullmatch(r"(?:[a-f0-9]{2}){1,64}", text):
                    raise ValueError("Invalid authored coefficient tokens")
            if kind != "error":
                uint(row["replay_steps"], 16)
        for key in ("solve_key", "commit_key"):
            if key in row and row[key] not in (0xed, 0xf0):
                raise ValueError("Unsupported execution key")
        if kind == "error":
            uint(row["cancel_at"], 3)
            uint(row["ignored_token"])
            if row["recovery_token"] not in (0xe6, 0xe2, 0xe3):
                raise ValueError("Unsupported recovery key")
        if kind == "navigation":
            uint(row["busy"])
            if not isinstance(row["navigation_keys"], list) or not row["navigation_keys"] or \
                    any(type(v) is not int or v not in (0xe0, 0xe1, 0xe2, 0xe3, 0xe6)
                        for v in row["navigation_keys"]):
                raise ValueError("Invalid authored navigation")
        for key, admitted in (("post_keys", (0xe6,)),
                              ("post_commit_navigation_keys", (0xe0, 0xe1, 0xe2, 0xe3))):
            if key in row and (not isinstance(row[key], list) or
                    any(type(v) is not int or v not in admitted for v in row[key])):
                raise ValueError("Invalid additional authored keys")
        if "require_stored_kinds" in row and (
                not isinstance(row["require_stored_kinds"], list) or
                len(row["require_stored_kinds"]) != row["selector"] or
                any(v not in ("DECIMAL", "SURD", "RATIONAL") for v in row["require_stored_kinds"])):
            raise ValueError("Invalid stored-kind route invariant")
    return recipe


def repository_root():
    for parent in Path(__file__).resolve().parents:
        if (parent / "firmware/fx-991es-plus-c-ver4.bin").is_file() and \
                (parent / "tools/nxu8/machine.py").is_file():
            return parent
    raise RuntimeError("Cannot locate repository")


class Control(C.Structure):
    _fields_ = [("cancelled", C.c_void_p), ("userdata", C.c_void_p)]


class Point(C.Structure):
    _fields_ = [("pc", C.c_uint32), ("ordinal", C.c_uint64),
                *[(name, C.c_uint8) for name in
                  ("r0", "selector", "screen", "submode", "page", "row", "column")]]


def main():
    root = repository_root()
    sys.path.insert(0, str(root / "tools"))
    from nxu8.machine import Machine
    from test_platform_c import Platform
    from c_build_inputs import implementation_inputs
    parser = argparse.ArgumentParser(description=__doc__)
    package = Path(__file__).resolve().parents[1]
    parser.add_argument("--fixture", type=Path, default=package /
                        "analysis/native-fixtures/polynomial-equation-workflow/inputs.json")
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--no-report", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--optimization", choices=("O2", "O3", "both"), default="both")
    args = parser.parse_args()
    source_root = args.source_root.resolve() if args.source_root else root
    if source_root != root and not args.no_report:
        parser.error("Private implementation overrides require --no-report")
    if Path(__file__).resolve() != root / "tools/test_polynomial_equation_workflow_c.py" and not args.no_report:
        parser.error("A private verifier cannot publish a canonical report")
    writer = None
    if not args.no_report:
        from c_verification import write_report
        writer = write_report
    fixture = args.fixture.resolve()
    fixture_hash = digest(fixture)
    if not args.no_report and not publication_allowed(root, source_root,
            Path(__file__).resolve(), fixture, fixture_hash, args.optimization):
        parser.error("Canonical publication requires the exact frozen fixture and both O2/O3; use --no-report for previews")
    recipe = validate_fixture(json.loads(fixture.read_text()))
    # Actual schema rejections: these copies are never passed to either engine.
    schema_guards = []
    for label, mutate in (
            ("output-field", lambda r: r["scenarios"][0].update(expected_record="00")),
            ("unknown-top-field", lambda r: r.update(expected_outputs=[])),
            ("invalid-selector", lambda r: r["scenarios"][0].update(selector=2)),
            ("boolean-selector", lambda r: r["scenarios"][0].update(selector=True)),
            ("coefficient-arity", lambda r: r["scenarios"][0]["coefficients"].pop()),
            ("unknown-workflow", lambda r: r["scenarios"][0].update(workflow="replayed-output")),
            ("invalid-key", lambda r: r["scenarios"][0].update(solve_key=0xff)),
            ("duplicate-label", lambda r: r["scenarios"].append(copy.deepcopy(r["scenarios"][0])))):
        invalid = copy.deepcopy(recipe)
        mutate(invalid)
        try:
            validate_fixture(invalid)
        except ValueError:
            schema_guards.append({"label": label, "rejected": True})
        else:
            raise RuntimeError("Fixture schema accepted " + label)
    publication_guards = []
    for label, params in (
            ("custom-fixture", (root, root, root / "tools/test_polynomial_equation_workflow_c.py",
                                root / "subset.json", CANONICAL_FIXTURE_SHA256, "both")),
            ("changed-fixture", (root, root, root / "tools/test_polynomial_equation_workflow_c.py",
                                 root / CANONICAL_FIXTURE, "0" * 64, "both")),
            ("single-optimization", (root, root, root / "tools/test_polynomial_equation_workflow_c.py",
                                     root / CANONICAL_FIXTURE, CANONICAL_FIXTURE_SHA256, "O2")),
            ("private-source", (root, root / "private", root / "tools/test_polynomial_equation_workflow_c.py",
                                root / CANONICAL_FIXTURE, CANONICAL_FIXTURE_SHA256, "both")),
            ("private-tool", (root, root, root / "private.py", root / CANONICAL_FIXTURE,
                              CANONICAL_FIXTURE_SHA256, "both"))):
        rejected = not publication_allowed(*params)
        if not rejected:
            raise RuntimeError("Publication guard accepted " + label)
        publication_guards.append({"label": label, "rejected": rejected})
    seed_fixture = root / recipe["seed_fixture"]
    if not seed_fixture.resolve().is_relative_to(root) or digest(seed_fixture) != recipe["seed_fixture_sha256"]:
        raise ValueError("Seed fixture identity changed")
    initial = bytes.fromhex(json.loads(seed_fixture.read_text())["initial_ram"][recipe["seed_key"]])
    if len(initial) != 65536:
        raise ValueError("Seed RAM extent mismatch")
    cmake = source_root / "csrc/CMakeLists.txt"
    cmake_hash = digest(cmake)
    discovery_pins = {p.resolve(): digest(p) for p in (source_root / "csrc").rglob("*")
                      if p.is_file() and p.suffix in (".c", ".h")}
    match = re.search(r"add_library\(fx991_firmware\s+STATIC\s+(.*?)\)", cmake.read_text(), re.S)
    if not match:
        raise ValueError("No actual firmware target")
    names = re.findall(r"(?<![\w/])([\w/]+\.c)(?!\w)", match.group(1))
    required_modules = ("ui/fx_polynomial_equation_controller.c", "render/fx_result_status_workflow.c")
    additions = [name for name in required_modules if name not in names]
    if additions and source_root == root:
        raise ValueError("Production CMake has not adopted polynomial workflow dependencies")
    names += additions
    sources = ["csrc/" + name for name in names]
    support = Path(__file__).resolve().parent / "polynomial_equation_workflow_support"
    implementation = [source_root / name for name in implementation_inputs(source_root, sources)]
    input_paths = implementation + [cmake, Path(__file__).resolve(), fixture, seed_fixture,
        root / "tools/test_platform_c.py", root / "tools/c_build_inputs.py",
        root / "tools/c_verification.py", root / "tools/equation_support/workflow_native.c",
        root / "firmware/fx-991es-plus-c-ver4.bin", root / "analysis/disassembly/complete.asm",
        root / "tools/nxu8/vendor/SimU8/provenance.json", root / "tools/nxu8/vendor/SimU8/COPYING"]
    input_paths += [p for p in support.rglob("*") if p.is_file() and p.suffix in (".c", ".h")]
    input_paths += [p for p in (root / "tools/nxu8").rglob("*")
                    if p.is_file() and p.suffix in (".c", ".h", ".py", ".txt")]
    python_helpers = imported_tool_paths(root)
    input_paths += list(python_helpers)
    compiler = Path(shutil.which("gcc")).resolve()
    compiler_version = subprocess.check_output([str(compiler), "--version"], text=True)
    compiler_paths = {compiler}
    for name in ("cc1", "collect2", "as", "ld"):
        path = subprocess.check_output([str(compiler), "-print-prog-name=" + name], text=True).strip()
        resolved = Path(path) if Path(path).is_absolute() else Path(shutil.which(path) or path)
        if not resolved.is_file():
            raise RuntimeError("Cannot pin compiler executable " + name)
        compiler_paths.add(resolved.resolve())
    compiler_pins = {p: digest(p) for p in compiler_paths}
    pins = {p.resolve(): digest(p) for p in sorted(set(input_paths))}
    if pins[fixture] != fixture_hash or pins[cmake] != cmake_hash:
        raise RuntimeError("Parsed input changed before compile guard")
    if any(p not in discovery_pins or pins[p] != discovery_pins[p]
           for p in (path.resolve() for path in implementation)):
        raise RuntimeError("Implementation changed while discovering its header closure")
    output = args.output or package / "analysis/build/polynomial-equation-workflow" / \
        (datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex)
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    compiler_temp = output / "compiler-tmp"
    compiler_temp.mkdir()
    environment = dict(os.environ, TMPDIR=str(compiler_temp))
    os.environ["TMPDIR"] = str(compiler_temp)
    rom = (root / "firmware/fx-991es-plus-c-ver4.bin").read_bytes()
    variants = []
    for optimization in (("O2", "O3") if args.optimization == "both" else (args.optimization,)):
        run = output / optimization
        run.mkdir()
        commands = [
            [str(compiler), "-std=c99", "-" + optimization, "-Wall", "-Wextra", "-Werror", "-shared", "-fPIC",
             "-Wl,--no-undefined", "-Wl,--wrap=fx_timer_start", "-I", str(source_root / "csrc"),
             *[str(source_root / name) for name in sources], str(support / "error_adapter.c"),
             "-o", str(run / "candidate.so")],
            [str(compiler), "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror", "-shared", "-fPIC",
             "-I", str(root / "tools"), str(support / "error_native.c"),
             str(root / "tools/nxu8/vendor/SimU8/core.c"), "-o", str(run / "native.so")]]
        for command in commands:
            subprocess.run(command, check=True, env=environment)
        artifacts = {p: digest(p) for p in (run / "candidate.so", run / "native.so")}
        # Build the generic harness before Machine loads it, then prove Machine
        # selected those exact bytes instead of silently recompiling a helper.
        base_oracle = run / "base-oracle"
        base_oracle.mkdir()
        harness_path = base_oracle / "nxu8-harness.so"
        harness_command = [str(compiler), "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
            "-fPIC", "-shared", str(root / "tools/nxu8/harness.c"),
            str(root / "tools/nxu8/vendor/SimU8/core.c"), "-o", str(harness_path)]
        subprocess.run(harness_command, check=True, env=environment)
        commands.append(harness_command)
        artifacts[harness_path] = digest(harness_path)
        machine = Machine(rom, base_oracle)
        if digest(harness_path) != artifacts[harness_path]:
            raise RuntimeError("Machine changed the preloaded harness artifact")
        native = C.CDLL(str(run / "native.so"))
        lib = C.CDLL(str(run / "candidate.so"))
        for name in ("harness_init", "harness_set_pc", "harness_get_pc", "harness_set_reg",
                     "harness_get_reg", "harness_set_sp", "harness_get_sp", "harness_set_lr",
                     "harness_ram", "harness_run"):
            getattr(native, name).argtypes = getattr(machine.lib, name).argtypes
            getattr(native, name).restype = getattr(machine.lib, name).restype
        machine.lib = native
        machine.ram = native.harness_ram().contents
        native.polynomial_run.argtypes = [C.c_uint64, C.c_uint32, C.c_uint]
        native.polynomial_queue_key.argtypes = [C.c_uint8, C.c_uint8]
        native.polynomial_point_size.restype = C.c_size_t
        native.polynomial_point_offset.argtypes = [C.c_uint]
        lib.polynomial_ui_size.restype = lib.polynomial_controller_size.restype = C.c_size_t
        lib.polynomial_host_abi.argtypes = [C.c_uint]
        lib.polynomial_host_abi.restype = C.c_size_t
        abi = [C.sizeof(Platform), *[getattr(Platform, key).offset for key in
               ("rom", "rom_size", "ram", "callback_pending", "status")],
               C.sizeof(Control), Control.cancelled.offset, Control.userdata.offset, 0, 1, 4]
        if abi != [lib.polynomial_host_abi(i) for i in range(len(abi))] or \
                C.sizeof(Point) != native.polynomial_point_size() or \
                [getattr(Point, name).offset for name, _ in Point._fields_] != \
                [native.polynomial_point_offset(i) for i in range(len(Point._fields_))]:
            raise RuntimeError("Compiled ABI disagrees with observer/ctypes")
        pp = C.POINTER(Platform)
        for name in ("polynomial_initialize", "fx_take_callback"):
            getattr(lib, name).argtypes = [pp]
        for name in ("polynomial_begin", "fx_polynomial_equation_controller_tick"):
            getattr(lib, name).argtypes = [pp, C.c_void_p]
        lib.fx_ui_controller_begin.argtypes = [pp, C.c_void_p, C.c_uint8, C.c_void_p]
        lib.fx_ui_controller_tick.argtypes = [pp, C.c_void_p]
        lib.polynomial_ui_return.argtypes = lib.polynomial_return.argtypes = [C.c_void_p]
        lib.polynomial_c_reset.argtypes = [C.c_uint]
        lib.polynomial_c_queue_key.argtypes = [C.c_uint8, C.c_uint8]
        lib.fx_polynomial_equation_commit_coefficient.argtypes = [pp, C.c_uint16]
        lib.fx_polynomial_equation_move_selection.argtypes = [pp, C.c_uint8]
        for name in ("fx_polynomial_equation_present_coefficients", "fx_polynomial_equation_present_root_caption"):
            getattr(lib, name).argtypes = [pp]
        lib.fx_polynomial_equation_controller_begin.argtypes = [pp, C.c_void_p, C.c_void_p]
        lib.fx_polynomial_equation_controller_finish.argtypes = [C.c_void_p, C.POINTER(C.c_uint8)]
        lib.fx_polynomial_equation_controller_export_mask.argtypes = [C.c_void_p]
        lib.fx_polynomial_equation_controller_export_mask.restype = C.c_uint8
        rom_c = (C.c_uint8 * len(rom)).from_buffer_copy(rom)
        ram = (C.c_uint8 * 65536)()
        platform = Platform(rom_c, len(rom), ram, 0, 0)
        frames = (C.c_uint8 * 65536).in_dll(native, "lifecycle_frames")
        n_polls = C.c_uint.in_dll(native, "lifecycle_polls")
        c_polls = C.c_uint.in_dll(lib, "polynomial_c_polls")
        n_poll_ram = ((C.c_uint8 * 65536) * 256).in_dll(native, "lifecycle_poll_ram")
        c_poll_ram = ((C.c_uint8 * 65536) * 256).in_dll(lib, "polynomial_c_poll_ram")
        n_instructions = C.c_uint64.in_dll(native, "polynomial_instructions")
        points = (Point * 128).in_dll(native, "polynomial_points")
        point_count = C.c_uint.in_dll(native, "polynomial_point_count")
        rows, failures, host_rows = [], [], []
        checks = len(abi) + 1 + len(Point._fields_) + len(schema_guards) + len(publication_guards)
        archive = run / "observations.jsonl.gz"
        with gzip.open(archive, "wt") as stream:
            for scenario in recipe["scenarios"]:
                machine.reset()
                C.memmove(machine.ram, initial, 65536)
                C.memmove(ram, initial, 65536)
                platform.callback_pending = platform.status = 0
                ram[0x80fa] = machine.ram[0x80fa] = scenario["selector"]
                ram[0x8106] = machine.ram[0x8106] = scenario["math"]
                ram[0x80f4] = machine.ram[0x80f4] = scenario.get("busy", initial[0x80f4])
                seen_frames = bytearray(65536)
                paused = [None]

                def state_buffer(size):
                    box = (C.c_uint8 * (size + 32))(*([0xa5] * (size + 32)))
                    C.memset(C.byref(box, 16), 0, size)
                    return box, C.byref(box, 16)

                def step(kind, token, label, stop=0x2fffe, cancel_at=0, expected_status=1, pair=None):
                    nonlocal checks
                    if token is not None:
                        ram[0x80f5] = machine.ram[0x80f5] = token
                        ram[0x80f7] = machine.ram[0x80f7] = 1
                    native.polynomial_reset()
                    lib.polynomial_c_reset(cancel_at)
                    if pair is not None:
                        for address in (0x8e01, 0x8e02):
                            ram[address] = machine.ram[address] = 0
                        lib.polynomial_c_queue_key(*pair)
                        native.polynomial_queue_key(*pair)
                    box = None
                    if kind == "initialize":
                        entry, returned = 0x1d31a, None
                        lib.polynomial_initialize(C.byref(platform))
                        status = 1
                    elif kind == "input":
                        entry = 0xd9ee
                        box, state = state_buffer(lib.polynomial_ui_size())
                        status = lib.fx_ui_controller_begin(C.byref(platform), state, 0, None)
                        for _ in range(20):
                            if status != 4:
                                break
                            status = lib.fx_ui_controller_tick(C.byref(platform), state)
                        returned = lib.polynomial_ui_return(state)
                    elif kind == "continuation":
                        entry = None
                        box, state = paused[0]
                        status = lib.fx_polynomial_equation_controller_tick(C.byref(platform), state)
                        returned = lib.polynomial_return(state)
                    elif kind == "commit-prefix":
                        entry, returned = 0xe782, None
                        status = 1 if lib.fx_polynomial_equation_commit_coefficient(
                            C.byref(platform), scenario["source"]) == 0 else -1
                        machine.reg(8, scenario["source"] & 255)
                        machine.reg(9, scenario["source"] >> 8)
                    else:
                        entry = 0xe862
                        box, state = state_buffer(lib.polynomial_controller_size())
                        paused[0] = (box, state)
                        status = lib.polynomial_begin(C.byref(platform), state)
                        for _ in range(20):
                            if status != 4:
                                break
                            status = lib.fx_polynomial_equation_controller_tick(C.byref(platform), state)
                        returned = lib.polynomial_return(state)
                    if entry is not None:
                        machine.reg(0, 0)
                        native.harness_set_sp(0x8dee)
                        native.harness_set_lr(0x2fffe)
                        native.harness_set_pc(entry)
                    elif native.harness_get_pc() == stop:
                        if native.harness_run(1, 0x2fffe, False) != 103:
                            raise RuntimeError("Cannot resume original error wait")
                    native_status = native.polynomial_run(50000000, stop, cancel_at)
                    for address in range(65536):
                        seen_frames[address] |= frames[address]

                    def differences(first, second):
                        return [[a, first[a], second[a]] for a in range(65536)
                                if first[a] != second[a] and not (
                                    seen_frames[a] or 0x8000 <= a < 0x80dc)]

                    final_diff = differences(ram, machine.ram)
                    actual_callback = lib.fx_take_callback(C.byref(platform))
                    expected_callback = native.harness_callback()
                    poll_diffs = []
                    for index in range(min(c_polls.value, n_polls.value, 256)):
                        diff = differences(c_poll_ram[index], n_poll_ram[index])
                        poll_diffs.append(diff)
                        stream.write(json.dumps({"scenario": scenario["label"], "stage": label,
                            "kind": "poll", "index": index, "differences": diff,
                            "c_ram": packed(c_poll_ram[index]), "native_ram": packed(n_poll_ram[index])}) + "\n")
                    point_rows = [{key: getattr(points[i], key) for key, _ in Point._fields_}
                                  for i in range(point_count.value)]
                    canary = box is None or (bytes(box[:16]) == bytes([0xa5] * 16) and
                                             bytes(box[-16:]) == bytes([0xa5] * 16))
                    mandatory = True
                    if label.startswith("solve-"):
                        calls = [row for row in point_rows if row["pc"] == 0x14f0c]
                        mandatory = len(calls) == 1 and n_polls.value in (1, 2, 3)
                        if scenario["workflow"] == "success":
                            mandatory &= any(row["pc"] == 0xe884 and row["r0"] == 0 for row in point_rows)
                            mandatory &= any(row["pc"] == 0x15658 for row in point_rows)
                            mandatory &= machine.reg(0) == 0
                        elif cancel_at:
                            mandatory &= n_polls.value == cancel_at and any(
                                row["pc"] == 0xe884 and row["r0"] == 1 for row in point_rows)
                        else:
                            mandatory &= any(row["pc"] in (0xe884, 0x1387a) and row["r0"] == 3
                                             for row in point_rows)
                    row = {"scenario": scenario["label"], "stage": label, "kind": kind,
                        "token": token, "stop": stop, "c_status": status, "c_return": returned,
                        "native_status": native_status, "native_return": machine.reg(0),
                        "native_instructions": n_instructions.value, "c_polls": c_polls.value,
                        "native_polls": n_polls.value, "c_callback": actual_callback,
                        "native_callback": expected_callback, "final_differences": final_diff,
                        "poll_differences": poll_diffs, "points": point_rows,
                        "native_minimum_sp": C.c_uint.in_dll(native, "lifecycle_floor").value,
                        "excluded_written_stack_bytes": sum(bool(v) for v in seen_frames),
                        "state_canary": canary, "mandatory_native_route": bool(mandatory)}
                    rows.append(row)
                    checks += 7 + len(poll_diffs)
                    stream.write(json.dumps(dict(row, c_ram=packed(ram), native_ram=packed(machine.ram),
                                                 written_frame_mask=packed(seen_frames))) + "\n")
                    if status != expected_status or native_status != 100 or \
                            (stop == 0x2fffe and returned is not None and returned != machine.reg(0)) or \
                            c_polls.value != n_polls.value or c_polls.value > 256 or \
                            actual_callback != expected_callback or final_diff or any(poll_diffs) or \
                            not canary or not mandatory:
                        failures.append(row)
                    print(optimization, scenario["label"], label, status, native_status,
                          len(final_diff), [len(diff) for diff in poll_diffs], flush=True)

                step("initialize", None, "original-equation-initialize")
                step("screen", 0, "initial-grid")
                if scenario["workflow"] == "commit-prefix":
                    for address, value in ((0x811c, scenario["page"]), (0x811d, 1),
                                           (0x811e, scenario["column"])):
                        ram[address] = machine.ram[address] = value
                    raw = bytes.fromhex(scenario["source_bytes"])
                    for offset, value in enumerate(raw):
                        ram[scenario["source"] + offset] = machine.ram[scenario["source"] + offset] = value
                    step("commit-prefix", None, "ordered-copy-prefix", stop=0xe6e4)
                    continue
                for index, text in enumerate(scenario["coefficients"]):
                    for position, token in enumerate(bytes.fromhex(text)):
                        step("input", token, f"coefficient-{index}-token-{position}")
                    key = scenario.get("commit_key", 0xed)
                    step("input", key, f"coefficient-{index}-commit")
                    step("screen", key, f"coefficient-{index}-grid")
                if "require_stored_kinds" in scenario:
                    for index, kind in enumerate(scenario["require_stored_kinds"]):
                        address = 0x82f8 if index == 3 else 0x829e + 10 * index
                        expected = {"DECIMAL": 0, "RATIONAL": 2, "SURD": 8}[kind]
                        actual = machine.ram[address] >> 4
                        checks += 1
                        if actual != expected:
                            failures.append({"scenario": scenario["label"],
                                "mandatory_stored_kind": kind,
                                "native_record": bytes(machine.ram[address:address + 10]).hex()})
                for index, token in enumerate(scenario.get("post_commit_navigation_keys", [])):
                    step("screen", token, f"stored-coefficient-navigation-{index}-{token:02x}")
                if scenario["workflow"] == "navigation":
                    for index, token in enumerate(scenario["navigation_keys"]):
                        step("screen", token, f"navigation-{index}-{token:02x}")
                elif scenario["workflow"] == "error":
                    step("screen", 0xed, "solve-error-wait", stop=0x1d8a4,
                         cancel_at=scenario["cancel_at"], expected_status=0)
                    key_pairs = {rom[0x7fe + 8 * col + row]: (1 << col, 1 << row)
                                 for col in range(8) for row in range(8)}
                    step("continuation", None, "ignored-error-key", stop=0x1d8a4,
                         expected_status=0, pair=key_pairs[scenario["ignored_token"]])
                    step("continuation", None, "accepted-error-key",
                         pair=key_pairs[scenario["recovery_token"]])
                    for address in (0x8e01, 0x8e02):
                        ram[address] = machine.ram[address] = 0
                    step("screen", scenario["recovery_token"], "recovery-coefficient-grid")
                else:
                    step("screen", scenario.get("solve_key", 0xed), "solve-once")
                    for index in range(scenario["replay_steps"]):
                        step("input", 0xed, f"replay-{index + 1}")
                    for index, token in enumerate(scenario.get("post_keys", [])):
                        step("input", token, f"result-reset-{index}-{token:02x}")
        # Host-only admission and no-write controls use the real compiled API.
        C.memmove(ram, initial, 65536)
        ram[0x80fa] = 3
        lib.polynomial_initialize(C.byref(platform))
        ram[0x80f5] = ram[0x80fd] = 0
        state = C.create_string_buffer(lib.polynomial_controller_size())

        def no_write(label, call, expected):
            nonlocal checks
            before = bytes(ram)
            actual = call()
            ok = actual == expected and bytes(ram) == before
            host_rows.append({"label": label, "actual": actual, "expected": expected,
                              "ram_unchanged": bytes(ram) == before})
            checks += 2
            if not ok:
                failures.append({"host_guard": host_rows[-1]})

        no_write("null-platform-begin", lambda: lib.fx_polynomial_equation_controller_begin(None, state, None), -1)
        no_write("null-state-begin", lambda: lib.fx_polynomial_equation_controller_begin(C.byref(platform), None, None), -1)
        no_write("inactive-tick", lambda: lib.fx_polynomial_equation_controller_tick(C.byref(platform), state), -1)
        answer = C.c_uint8(0xad)
        no_write("inactive-finish", lambda: lib.fx_polynomial_equation_controller_finish(state, C.byref(answer)), -1)
        no_write("inactive-export", lambda: lib.fx_polynomial_equation_controller_export_mask(state), 0)
        if answer.value != 0xad:
            failures.append({"host_guard": "invalid finish overwrote returned canary"})
        checks += 1
        for address, invalid in ((0x80f9, 0xc1), (0x80fa, 2), (0x80fa, 5), (0x80fc, 1),
                                 (0x811c, 0), (0x811c, 3), (0x811d, 0), (0x811d, 2),
                                 (0x811e, 0), (0x811e, 4)):
            saved = ram[address]
            ram[address] = invalid
            no_write(f"invalid-admission-{address:04x}-{invalid}", lambda:
                lib.fx_polynomial_equation_controller_begin(C.byref(platform), state, None), -1)
            ram[address] = saved
        for key in (0xed, 0xf0):
            ram[0x80f5], ram[0x80f7], ram[0x80fd] = key, 0, 0
            no_write(f"no-ready-solve-{key:02x}", lambda:
                lib.fx_polynomial_equation_controller_begin(C.byref(platform), state, None), -1)
        ram[0x80f5] = 0
        for source in (0, 0x7fff, 0xfff7, 0xffff):
            no_write(f"invalid-copy-source-{source:04x}", lambda source=source:
                lib.fx_polynomial_equation_commit_coefficient(C.byref(platform), source), -1)
        for label, field in (("null-ram", "ram"), ("null-rom", "rom")):
            bad = Platform.from_buffer_copy(platform)
            setattr(bad, field, None)
            no_write(label, lambda: lib.fx_polynomial_equation_controller_begin(C.byref(bad), state, None), -1)
        # A completed grid state must export its returned byte once, then
        # reject repeated finish/tick calls without touching calculator RAM.
        ram[0x80f5] = ram[0x80fd] = 0
        status = lib.fx_polynomial_equation_controller_begin(C.byref(platform), state, None)
        checks += 1
        if status != 1:
            failures.append({"host_guard": "valid grid setup for finish", "actual": status})
        no_write("completed-finish", lambda:
            lib.fx_polynomial_equation_controller_finish(state, C.byref(answer)), 1)
        checks += 1
        if answer.value != 1:
            failures.append({"host_guard": "completed returned byte", "actual": answer.value})
        answer.value = 0xad
        no_write("second-finish", lambda:
            lib.fx_polynomial_equation_controller_finish(state, C.byref(answer)), -1)
        checks += 1
        if answer.value != 0xad:
            failures.append({"host_guard": "second finish overwrote output"})
        no_write("finished-state-tick", lambda:
            lib.fx_polynomial_equation_controller_tick(C.byref(platform), state), -1)
        source_changes = changes(pins)
        artifact_changes = changes(artifacts)
        compiler_changes = changes(compiler_pins)
        helper_changes = sorted(str(p) for p in imported_tool_paths(root) - python_helpers)
        checks += len(pins) + len(artifacts) + len(compiler_pins) + 1
        mutation_guards = []
        for label, source in (("artifact", run / "candidate.so"),
                              ("header", source_root / "csrc/ui/fx_polynomial_equation_controller.h"),
                              ("fixture", fixture), ("archive", archive)):
            changed_copy = run / (label + "-changed-copy")
            changed_copy.write_bytes(source.read_bytes() + b"\nchanged-copy-only\n")
            detected = bool(changes({changed_copy: digest(source)}))
            mutation_guards.append({"label": label, "detected": detected,
                                    "original_sha256": digest(source),
                                    "changed_copy_sha256": digest(changed_copy)})
            checks += 1
            if not detected:
                failures.append({"mutation_guard": label})
        variant = {"status": "PASS" if not (failures or source_changes or artifact_changes or
                    compiler_changes or helper_changes) else "FAIL",
            "optimization": optimization, "cases": len(recipe["scenarios"]), "native_calls": len(rows),
            "native_instructions": sum(row["native_instructions"] for row in rows), "checks": checks,
            "failures": failures, "rows": rows, "host_controls": host_rows, "abi": abi,
            "compiled_artifacts": {str(p): h for p, h in artifacts.items()},
            "artifact_changes": artifact_changes, "source_changes": source_changes,
            "compiler_changes": compiler_changes, "new_imported_helpers": helper_changes,
            "schema_guards": schema_guards, "publication_guards": publication_guards,
            "mutation_guards": mutation_guards,
            "commands": commands, "archive": str(archive), "archive_sha256": digest(archive)}
        (run / "report.json").write_text(json.dumps(variant, indent=2) + "\n")
        variants.append(variant)
    final_changes = changes(pins)
    report = {"schema": 1, "status": "PASS" if not final_changes and all(
        row["status"] == "PASS" for row in variants) else "FAIL", "variants": variants,
        "native_calls": sum(row["native_calls"] for row in variants),
        "native_instructions": sum(row["native_instructions"] for row in variants),
        "checks": sum(row["checks"] for row in variants),
        "source_pins": {str(p): h for p, h in pins.items()}, "source_changes": final_changes,
        "compiler_pins": {str(p): h for p, h in compiler_pins.items()},
        "compiler_version": compiler_version, "imported_python_helpers": [str(p) for p in sorted(python_helpers)],
        "private_cmake_additions": additions, "fixture_sha256": fixture_hash,
        "scope": "Prepared E862/D9EE polynomial coefficient input, one solve, actual timer publications, roots/vertex replay, grid navigation and error-key continuation. C runs before fresh original from the same authored initial RAM/keys. All retained RAM and full timer RAM compare outside only actually written measured original stack bytes and 8000..80DB arithmetic scratch. Eight D142 alias recipes stop at E6E4 before the borrowed F12A epilogue. No whole boot-main/matrix-scan or arbitrary malformed coefficient claim."}
    (output / "proof.json").write_text(json.dumps(report, indent=2) + "\n")
    if report["status"] == "PASS" and writer is not None:
        owned = [p.relative_to(root) for p in pins if p.is_relative_to(root) and
                 (p.suffix in (".c", ".h", ".py", ".json", ".bin") or p.name == "CMakeLists.txt")]
        report["verified_extra_inputs_sha256"] = {str(p.relative_to(root)): h for p, h in pins.items()
            if p.is_relative_to(root) and p.relative_to(root) not in owned}
        writer("analysis/c-verification/polynomial_equation_workflow.json", report,
                     owned, Path(__file__).resolve().relative_to(root))
    print(json.dumps({key: report[key] for key in ("status", "native_calls", "checks", "source_changes")}))
    print(output / "proof.json")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
