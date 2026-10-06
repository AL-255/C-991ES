# Provenance, reproduction and limits

Curated 2026-10-06 from the latest local source documents listed below. This migration records existing knowledge; it did not execute the original ROM, the Windows binaries or new C/browser tests. Original files remain local. Paths beginning analysis/ or eps-emu/ are **local-only evidence paths**, deliberately written as text rather than repository links.

## Curated textual sources

| Local-only source | SHA-256 at curation |
| --- | --- |
| analysis/eps-firmware-lineage/README.md | 1bc53b8ff18821248644e4505fae7fa28c7e7f798ff92b572e0dda96dd380f4f |
| analysis/eps-firmware-lineage/01-inputs-and-method.md | a348de0f577f4bb274a82e1af80078d0999eade3a7dd4ed0e9287b319899f943 |
| analysis/eps-firmware-lineage/02-binary-and-resource-evidence.md | 946f3a6df287b446f27c831acee89908f2429a5e744bb98e14d47057e4fb3b16 |
| analysis/eps-firmware-lineage/03-numerical-and-algorithm-evidence.md | 0c8b25221e74d3e1268c6eceed3e851574e0e57a60fc659c1087394cae8520ca |
| analysis/eps-firmware-lineage/04-reproduction-and-open-questions.md | 10c14bf5c12a8f651c1ef27ed088f91941a814e0705d2274a5acf7cde45a1ea8 |
| analysis/eps-firmware-lineage/05-function-contracts.md | c8890362ed6cbf9a3e19cb3c1093e87c37a10f837d9fffe5ef0795d0f5962969 |
| analysis/eps-firmware-lineage/06-call-and-loop-structure.md | cc060546a1c1ae419e03196d83c459079def82e5213cfeaaac1ea3b0d8478e58 |
| analysis/eps-firmware-lineage/07-parser-and-stack-structure.md | fa9c4b51c7c4fe0342585bf79f3a734b2ba5000572901110c77d621aeae44ea5 |
| analysis/eps-firmware-lineage/08-structural-method-and-verification.md | 651b006a4bd4eec3a84040db63dd4dfa092ec03e246139c55e9f477d1053c16c |
| analysis/emulator-host-scheduling/README.md | 36cf7839f145ff738108f21f42bd4fda04699e0c4c844e03489ed137d8715c56 |
| analysis/emulator-host-scheduling/host-timer-audit.md | 41e4cace3f3e9b739df1fc970883efb4646030383f123762a351ebd41d8687b4 |

## Image and address conventions

Casio firmware has 131072 bytes, SHA-256 28b5c3907a67426a1601dbf82ebf62b850333e889fcc958d698786d3e5f5fb7d, ID LY727XA at 1FFF4. Casio addresses are linear code byte addresses (1C780 means segment 1,PC C780); data-segment state is separate. The extraction reconstructed original x86 initializer writes without running the Windows EXE; configured code memory was 192KiB with a zero last 64KiB. [Extraction tool](../../../tools/extract_firmware.py) and [metadata](../../../firmware/extraction.json) retain the source lineage. The pinned test CPU is under [tools/nxu8](../../../tools/nxu8/).

## Windows host payload pins

| Member | SHA-256 |
| --- | --- |
| fx_991es_plus_c_emulator.exe | ae338dbecd5f2723cfc0f6415c3f5702710ab7199b014f39b2fac4b36bd71c79 |
| simu 8.dll | 634051b2dd8f93663d618ac1a4370f5bdaec8de5f23d938c9915abb429ff4cbf |
| simu 8 engine.dll | b2d9ba345a0dbbed569c1e4a67cdfbf066fca7e1bbcc1b6aeb53ad22371d5105 |
| fxesplus_p16.dll | 337334de19ab05c374eb73983d72b6cd6f5e54806577b7d8590d5487c2ed41cf |

No Windows binary was executed. PE addresses are preferred-image-base VAs; ASLR can relocate a loaded image. Host scheduling source claims are static plus independent delay arithmetic, not a measured worker FPU state or physical timing.

Local-only lineage tools: analysis/eps-firmware-lineage/{inspect_firmware.py,probe_numeric.py,probe_structure.py,probe_key_structure.py,probe_parser_structure.py,inspect_structure.py,verify_structure.py,probe_bridge.c,structure_bridge.c}. Historical machine-readable evidence: evidence.json,numeric-evidence.json,structure-evidence.json,structure-positive-control.json,parser-structure-evidence.json,key-structure-evidence.json and structure-call-candidates.json in that directory.

These scripts require local original ePS/Casio cores and ROMs, Python 3/GCC; ePS assets are intentionally absent from repository history. Prepared calls use bounded native returns and deterministic instruction/table-read counters, not wall-clock performance. The initial script checked 12Casio unary cases,24HP unary calls,4Vinacal log 10 calls/ln intermediates and 2 division calls. Follow-up checked 84 numeric/helper and 40 stack calls, overlapping 32 earlier numerical records and native HP+ key sequences. HP 300s key evaluation remained unvalidated.

Local-only host sources: analysis/emulator-host-scheduling/{host_dispatch.asm,host_setup.asm,host_queue.asm,host_enqueue.asm,simu8_runner.asm,simu8_registration.asm,simu8_thread_start.asm,engine_stop.asm,engine_interrupt.asm,engine_interrupt_accept.asm,engine_writebit.asm,engine_ramwrite.asm,engine_rawstore.asm,p16_keycodes.asm,firmware_timer.asm,host_precision_init.asm,simu8_precision_init.asm,delay_conversion.py,delay_conversion.json,artifact_manifest.json}. Original temporary paths /tmp/casio-host-timer/ and /tmp/host-timer-audit-frozen describe historical working custody; focused copies survive locally. Three publication disassemblies normalized trailing whitespace while preserving origin hashes. Full PE inventories can be regenerated with objdump -p on the pinned extracted payload.

## Selection and omissions

Preserved pinned ROM identities/address ordering, numerical and ABI/loop/parser differences, HP positive controls, binary/font-search bounds, unresolved ancestry and original host queue/STOP/IRQ/cancellation/delay contracts. Omitted raw ROMs, ePS source/assets, binary or JSON evidence, screenshots, full ASM/PE dumps, compiled bridges, incidental execution diaries and superseded coverage percentages. The prose records technical inference, not authorship, licensing or a historical copying event.
