# Project handoff

## Objective and current state

The user wants a readable, handwritten high-level C implementation of every
firmware subsystem, comparison against original execution, and an interactive
calculator published at https://al-255.github.io/C-991ES/.
The CPU under `tools/nxu8` is a test oracle only; assembly translation or a CPU
interpreter is not an acceptable C engine.

The full firmware audit is paused at the user's request and remains incomplete.
The published calculator uses the committed 130-module engine. The working tree
contains pending 144-module engine and harness work: preserve it and do not
include it accidentally in documentation or UI commits. `csrc/scope.json` retains
`complete=false`. Documented understanding is 46,094/46,094 instruction addresses
(100%); this is distinct from implementation completion and behavioral parity.
`tools/measure_code_understanding.py` measures the local pinned listing and
semantic ledgers without recording history or generating plots. The old
Matplotlib/CSV progress workflow was retired at the user's request.

## Repository and evidence

- Durable findings: `doc/reverse-engineering/README.md`.
- `analysis/`, `eps-emu/` and `.vscode/` are local ignored directories removed
  from tracked history. Preserve existing contents. Original traces, disassembly,
  fixtures and private proposals cited below are local evidence, absent from
  fresh clones.
- Firmware images and provenance: `firmware/`; extraction procedure:
  `doc/firmware-extraction.txt`; original execution tools: `tools/nxu8`.
- Engine sources, manifests and instruction ledgers: `csrc/`. The authored
  SVG/HTML/CSS UI in `simulator/device/` retains the original keypad layout.
  No original interface bitmaps are bundled. Webpage branding, titles and
  accessibility text must use `C-991ES`; historical Casio references may remain
  in repository research documentation.
- Authorized destination: remote `explore`,
  `git@github.com:AL-255/C-991ES.git`, branch `main`.
  Commit/push/Pages publishing has already been explicitly authorized.
- History cleanup records: `doc/history-rewrite.json` and
  `doc/history-cleanup.json`. Recovery bundles are local-only; never upload them.

## Build and UI

From the repository root:

```sh
cmake -S csrc -B analysis/build/c-port -DCMAKE_BUILD_TYPE=Release
cmake --build analysis/build/c-port -j4
python3 simulator/serve.py
```

See `csrc/README.md` and `simulator/README.md` for native/WASM builds and APIs.
Pages builds committed C with pinned Emscripten 6.0.11 and uploads
`simulator/dist/`. Native/browser builds do not require `eps-emu/` or prior
analysis artifacts. Original differential tests need local fixtures/disassembly;
do not claim a fresh clone contains those inputs or old proof reports.

The raw-key browser API owns persistent RAM and controllers. Of the 384 LCD
snapshot bytes, the first 12 contain segment controls, not visible matrix pixels.
`simulator/device/lcd-indicators.js` decodes 18 original labels; visible matrix
rows 1–31 retain C pixels. Two reserved control bits remain unlabeled.
Normal ON, all 49 matrix keys, keyboard input and small-screen layouts were
tested on the committed engine. UI success does not establish firmware parity.

## Main blocker when the firmware audit resumes

A genuine current warm STAT discrepancy remains: nine boundaries differ in
30 RAM bytes at `829E..82BB` (270 byte-observations). Values, LCD, statuses,
semantic outcomes and 41 poll comparisons matched in the four-input O2 replay.
The original publishes scratch/cache metadata where C retains `5A` bytes.
O3 and a candidate fix have not run.

Read local evidence:

- `analysis/build/root144-warm-stat-current-investigation/HANDOFF.json`,
  its `CURRENT-DIAGNOSTIC.json` and `FREEZE.json`.
- `analysis/verification/stat-warm-cache-residual.json`.
- `analysis/build/root144-component-current-turn-handoff/HANDOFF.json`.

Investigate numeric-service scratch/resource publication near
`statistics_advanced()` in `csrc/parse/fx_eval.c`: inputs at `8CAC`/`8CA6`,
the 20-byte normalizer workspace, three-byte continuation/padding writes and
their order/source identities. Do not infer an output address from a numeric
record value, hardcode captured bytes or overwrite a valid flag-1 cache.
Prepare a private readable C candidate, peer-review it, then replay the exact
warm O2/O3 workloads and preservation controls before adopting it.

## Remaining verification work

The stopping inventory had 151 current passing, two stale/noncommon and three
missing canonical records across 156 suites. This is historical local evidence,
not a source-current pass after tool changes. Details:
`analysis/build/root-session-handoff-20261005/INVENTORY.json` and
`analysis/build/runtime-turn-handoff-20261005/`.

- BASE UI: adopt the reviewed publication-schema successor and rerun its real
  default. Proposal: `analysis/build/base-ui-canonical-schema-successor-01/`.
- Distribution admission: reviewed two-file owned-prefix harness successor,
  not adopted/executed. Proposal:
  `analysis/build/distribution-list-admission-owned-prefix-successor-02/`.
- Device protocol: old controls expect generic STAT admission. Preserve eight
  archived recipes and derive owned-body continuations. Proposal:
  `analysis/build/device-protocol-ownership-successor-01/`.
- Device session: native MAIN stop map lacks operation 7 for the owned MATRIX
  body. Correct the observer rather than fabricate external completion.
- TABLE UI: run after the final C/tool epoch because it has broad input guards.

`tools/test_canonical_receipts.py` pins broad source/tool/fixture trees. Tool
changes, including the plotting retirement, stale affected receipts. Do not drop
pins or relabel failed/stale evidence. Freeze final fixes together, then rerun
actual affected workloads. The aggregate validates stored receipts; it does not
execute originals or resolve the warm discrepancy.

After fixes, rebuild native/WASM, recollect source-current browser traces,
commit intended files only, push, inspect the real Pages run/artifact and compare
served hashes and behavior. Keep source epochs and limitations explicit.

## Collaboration and workspace care

Use available parallel agents with separate ownership; they share the filesystem.
Root owns source adoption, Git and aggregate/scope publication. Do not resume
the paused firmware audit during unrelated cleanup work.

Default sandbox calls have failed before execution with a `/tmp/.git` quota error;
bounded task-specific escalated calls worked. Use workspace-local compiler/cache
directories rather than adding pressure to `/tmp`. Preserve private proposals,
failed epochs and pending C work.
Do not stage browser/compiler scratch or the pre-existing untracked
`browser_proof.py`, `collect_wasm.mjs`, `native_proof.py`, `wasm_proof.py` under
`tools/device_browser_support/` during unrelated changes.
