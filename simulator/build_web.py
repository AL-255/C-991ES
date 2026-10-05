#!/usr/bin/env python3
"""Build the existing high-level C simulator as a static WebAssembly site."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SDK_VERSION = "6.0.11"
SDK_COMMIT = "dd8e25632640cfc1fb570c7fa4cc374e8a5e5a72"
RELEASE_BUILD = "f6264d4a4dd9ba24a9f0a5702835a44d1463de13"
SDK_ORIGIN = "https://github.com/emscripten-core/emsdk.git"
EXPORTS = ["_fxsim_create", "_fxsim_destroy", "_fxsim_reset", "_fxsim_evaluate", "_malloc", "_free"]
EXPORTS += ["_fx_device_browser_" + name for name in (
    "create", "destroy", "reset", "submit_pair", "release", "step",
    "ack_timer", "take_callback", "snapshot", "snapshot_free")]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def firmware_sources() -> list[Path]:
    """Use the authoritative target's literal source list, never a glob."""
    cmake = (ROOT / "csrc/CMakeLists.txt").read_text()
    target = re.search(r"add_library\(fx991_firmware\s+STATIC\s+(.*?)\)", cmake, re.S)
    if not target:
        raise ValueError("Cannot find the fx991_firmware STATIC source list")
    words = re.sub(r"#[^\n]*", "", target.group(1)).split()
    if not words or len(words) != len(set(words)):
        raise ValueError("Empty or duplicate firmware source list")
    result = []
    for word in words:
        path = (ROOT / "csrc" / word).resolve()
        if not word.endswith(".c") or not path.is_relative_to(ROOT / "csrc") or not path.is_file():
            raise ValueError(f"Unexpected firmware source: {word}")
        result.append(path)
    return result + [ROOT / "csrc/app/fx_simulator_engine.c", ROOT / "csrc/app/fx_simulator_input.c",
                     ROOT / "csrc/app/fx_device_session.c", ROOT / "csrc/app/fx_device_protocol.c",
                     ROOT / "csrc/app/fx_device_browser.c"]


def implementation_closure(sources: list[Path]) -> set[Path]:
    pending, found = list(sources), set()
    while pending:
        path = pending.pop().resolve()
        if path in found:
            continue
        found.add(path)
        for name in re.findall(r'^\s*#\s*include\s*"([^"]+)"', path.read_text(), re.M):
            candidates = [path.parent / name, ROOT / "csrc" / name]
            included = next((candidate.resolve() for candidate in candidates if candidate.is_file()), None)
            if included is None or not included.is_relative_to(ROOT / "csrc"):
                raise ValueError(f"Unresolved/nonlocal include {name} in {path}")
            pending.append(included)
    return found


def run(command: list[str], environment: dict[str, str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, env=environment, check=True, text=True, **kwargs)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, default=ROOT / "analysis/build/emsdk",
                        help="Official emsdk clone at the pinned 6.0.11 tag, installed and activated")
    parser.add_argument("--output", type=Path, default=ROOT / "simulator/dist")
    parser.add_argument("--report", type=Path, default=ROOT / "analysis/build/simulator-wasm/build-report.json")
    args = parser.parse_args()
    sdk, output, report_path = args.sdk.resolve(), args.output.resolve(), args.report.resolve()
    if output == ROOT or output.is_relative_to(ROOT / "csrc") or output.is_relative_to(ROOT / "simulator/web"):
        raise ValueError("Output must be a distinct build directory")
    emcc = sdk / "upstream/emscripten/emcc"
    if not emcc.is_file() or not (sdk / ".emscripten").is_file():
        raise ValueError(f"Install/activate official emsdk {SDK_VERSION} in {sdk} first")
    scratch = ROOT / "analysis/build/simulator-wasm/compiler-tmp"
    scratch.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, TMPDIR=str(scratch), EM_CONFIG=str(sdk / ".emscripten"))
    sdk_commit = run(["git", "-C", str(sdk), "rev-parse", "HEAD"], environment, capture_output=True).stdout.strip()
    sdk_origin = run(["git", "-C", str(sdk), "remote", "get-url", "origin"], environment, capture_output=True).stdout.strip()
    tags_path, manifest_path = sdk / "emscripten-releases-tags.json", sdk / "emsdk_manifest.json"
    tags = json.loads(tags_path.read_text())
    if sdk_commit != SDK_COMMIT or sdk_origin.removesuffix(".git") != SDK_ORIGIN.removesuffix(".git") or tags["releases"].get(SDK_VERSION) != RELEASE_BUILD:
        raise ValueError("SDK origin, pinned tag or official release-build metadata differs")
    archive = sdk / "downloads" / (RELEASE_BUILD + "-wasm-binaries.tar.xz")
    tool_paths = [tags_path, manifest_path, emcc, sdk / ".emscripten",
                  sdk / "upstream/emscripten/emscripten-version.txt",
                  sdk / "upstream/bin/clang", sdk / "upstream/bin/wasm-ld", sdk / "upstream/bin/wasm-opt"]
    tool_paths.extend(sdk.glob("node/*/bin/node"))
    if archive.is_file():
        tool_paths.append(archive)
    compiler_pins = {str(path.relative_to(sdk)): sha256(path) for path in tool_paths if path.is_file()}
    version = run([str(emcc), "--version"], environment, capture_output=True).stdout
    if not re.search(r"\b" + re.escape(SDK_VERSION) + r"\b", version.splitlines()[0]):
        raise ValueError(f"Compiler is not the pinned Emscripten {SDK_VERSION}: {version}")
    sources = firmware_sources()
    assets = [ROOT / "simulator/web" / name for name in ("index.html", "app.js", "styles.css", "engine.js")]
    device_assets = [ROOT / "simulator/device" / name for name in
                     ("index.html", "app.js", "styles.css", "calculator-face.svg")]
    inputs = implementation_closure(sources) | set(assets) | set(device_assets) | {Path(__file__).resolve(), ROOT / "csrc/CMakeLists.txt"}
    input_pins = {str(path.relative_to(ROOT)): sha256(path) for path in sorted(inputs)}
    output.mkdir(parents=True, exist_ok=True)
    command = [str(emcc), "-std=c99", "-O3", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "csrc"),
               *map(str, sources), "--no-entry", "-sMODULARIZE=1", "-sEXPORT_ES6=1",
               "-sEXPORT_NAME=createFx991Simulator", "-sENVIRONMENT=web,worker,node", "-sFILESYSTEM=0",
               "-sALLOW_MEMORY_GROWTH=1", "-sINITIAL_MEMORY=16777216", "-sMAXIMUM_MEMORY=67108864",
               "-sSTACK_SIZE=2097152", "-sEXPORTED_FUNCTIONS=" + json.dumps(EXPORTS),
               '-sEXPORTED_RUNTIME_METHODS=["UTF8ToString","HEAPU8"]', "-o", str(output / "fx991sim.js")]
    run(command, environment)
    for source in assets:
        if source.name == "index.html":
            html = source.read_text()
            if "fxsim-backend" in html or "<head>" not in html:
                raise ValueError("Unexpected static backend marker/head in source HTML")
            (output / source.name).write_text(html.replace("<head>", '<head>\n  <meta name="fxsim-backend" content="wasm">', 1))
        else:
            shutil.copyfile(source, output / source.name)
    (output / "device").mkdir(exist_ok=True)
    for source in device_assets:
        shutil.copyfile(source, output / "device" / source.name)
    (output / ".nojekyll").write_text("")
    # ES modules can also be consumed by the actual Node-based verification.
    (output / "package.json").write_text('{"type":"module"}\n')
    changed = {name: sha256(ROOT / name) for name, digest in input_pins.items() if sha256(ROOT / name) != digest}
    if changed:
        raise ValueError(f"Source changed during compilation: {changed}")
    artifacts = {name: {"sha256": sha256(output / name), "bytes": (output / name).stat().st_size}
                 for name in ("fx991sim.js", "fx991sim.wasm", "index.html", "app.js", "styles.css", "engine.js", ".nojekyll", "package.json",
                              "device/index.html", "device/app.js", "device/styles.css", "device/calculator-face.svg")}
    compiler_changes = {name: sha256(sdk / name) for name, digest in compiler_pins.items() if sha256(sdk / name) != digest}
    if compiler_changes:
        raise ValueError(f"Compiler input changed during invocation: {compiler_changes}")
    report = {"schema": 1, "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
              "sdk": {"version": SDK_VERSION, "git_commit": sdk_commit, "origin": sdk_origin,
                      "release_build_identifier": RELEASE_BUILD, "tool_pins": compiler_pins},
              "compiler_version": version, "command": command, "source_files": [str(p.relative_to(ROOT)) for p in sources],
              "input_pins": input_pins, "pre_post_source_changes": changed,
              "pre_post_compiler_changes": compiler_changes, "artifacts": artifacts,
              "output_directory": str(output), "exports": EXPORTS,
              "scope": "Actual C-to-WebAssembly build provenance. This build report alone does not establish numerical or browser parity."}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"output": str(output), "report": str(report_path), "sources": len(sources), "pins": len(input_pins), "artifacts": artifacts}))


if __name__ == "__main__":
    main()
