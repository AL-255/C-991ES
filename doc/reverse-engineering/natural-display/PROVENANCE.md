# Provenance, reproduction and limits

Curated 2026-10-06 from the latest local source documents listed below. This migration records existing knowledge; it did not execute the original ROM, the Windows binaries or new C/browser tests. Original files remain local. Paths beginning analysis/ or eps-emu/ are **local-only evidence paths**, deliberately written as text rather than repository links.

## Curated textual sources

| Local-only source | SHA-256 at curation |
| --- | --- |
| analysis/exact-result-trace/README.md | 1a36d6f07e8d30b3ed667f822fe392901cc6ca6fba5c8c51c666630705e5cea8 |
| analysis/pi-result-trace/README.md | 430a9c42bc3b0fa9d7347c11a3e652c0ad0b1ba20fe24cb51a4943605c08af14 |
| analysis/special-angle-trace/README.md | 86fd7a23ed150dc69a132aae3e460242c2afa5a1e1dfea4495ebab2425f58f9a |
| analysis/qpi-independent-audit/README.md | 26eb21f19b913fd8b874de710e08dcb42f6f329f600b8f52ad70cacdd1aaa793 |
| analysis/qpi-independent-audit/HANDOFF.md | b91e1a71d4ff67b7236d3f0175777a35f23070b1f06dab71eb454fd020c2a4d0 |
| analysis/natural-textbook-output.md | 81e62fc63dee422d4f8181b662eef37cb2012cd19eb179bbcb07f5add93c2903 |
| analysis/pi-equation-solve-cold/README.md | d7bd114a45227821917784277d5597dc131595e80f17af082f672b3dcb250740 |

## Image and address conventions

Casio firmware has 131072 bytes, SHA-256 28b5c3907a67426a1601dbf82ebf62b850333e889fcc958d698786d3e5f5fb7d, ID LY727XA at 1FFF4. Casio addresses are linear code byte addresses (1C780 means segment 1,PC C780); data-segment state is separate. The extraction reconstructed original x86 initializer writes without running the Windows EXE; configured code memory was 192KiB with a zero last 64KiB. [Extraction tool](../../../tools/extract_firmware.py) and [metadata](../../../firmware/extraction.json) retain the source lineage. The pinned test CPU is under [tools/nxu8](../../../tools/nxu8/).

## Historical verification

The independent QPI review replayed 77 annotated traces:1709096 instructions at 7823 distinct PCs, all read-memory replay and instruction-start checks passed. It executed 168 fresh original-ROM controls, completed 2026-10-04T16:42:15.303133+00:00. The first attempt hit compiler temporary-disk quota; the successful rerun used private workspace scratch. That was infrastructure failure, not a firmware differential.

The individual routine-level series recorded 190844 exact-result instructions,1131241 pi-series instructions across 19 cases, and 387011 special-angle instructions across 14 cases. The 128 denominator sweep and 4 integer-helper boundary calls were actual executions but lacked full CSV traces. These original investigations do not imply complete implementation or all-mode parity. The later cold EQN/SOLVE evidence is separately scoped in numeric-recognition.md.

Maintained reproduction entry points, run from repository root:

~~~sh
python3 tools/trace_natural_result.py
python3 tools/trace_pi_recognition.py
python3 tools/trace_special_angles.py
python3 tools/analyze_firmware.py
python3 tools/verify_firmware.py
python3 tools/verify_rendering_edges.py
python3 tools/audit_coverage.py
~~~

Python 3/GCC are required for native tests; extraction additionally needs 7z/objdump. Tools recreate local analysis/ outputs. Independent historical review.py has a directory-depth assumption: copy it to analysis/build/qpi-original-trace/ and use private compiler TMPDIR, then run without Python optimization. That local-only script and its saved review/freeze records are not newly executed by this curation.

Local-only raw evidence: analysis/exact-result-trace/{manifest.json,*.annotated.csv.gz,*.calls.json.gz,*.milestones.json,*.initial-ram.bin.gz,result.bin}; corresponding pi-result-trace and special-angle-trace records; analysis/qpi-independent-audit/{review.py,review.json,freeze.json,input-only.json}; analysis/pi-equation-solve-cold/{summary.json,selected-observations.json}; analysis/native-fixtures/pi-equation-solve-cold/inputs.json; analysis/disassembly/complete.asm; analysis/verification/{behavior.json,rendering-edges.json,layout-samples.json,numeric-samples.json,coverage-audit.json}.

Static listing SHA-256:f9e715eee6fb521da0005c6c8967baa3e8141a2785898033f07dca143c41b19c. Cold EQN/SOLVE selected records preserve 306 source,72GNU-resource and 4 artifact pins;2494796 whole-session instructions versus 2494782 run-to accounting omit 14 real single-step advances. This selected subset is not a complete key archive or standalone replay tool.

## Selection and omissions

Preserved mechanisms, dispatch/record addresses, complete requested radical flow, pi scaling/precision controls, finite trig tables, cold EQN/SOLVE policy, token/layout/font/pixel semantics and original proof bounds. Omitted raw CSV/JSON/RAM binaries, images, large ASM, generated native libraries, duplicate narrative, historical percentage diaries and complete per-instruction rows. Raw evidence is retained locally, not converted into new test claims.
