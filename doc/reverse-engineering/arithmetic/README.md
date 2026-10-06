# Arithmetic reverse engineering

This guide preserves the useful parser and numerical contracts recovered from
the fx-991ES PLUS C firmware. Native addresses are hexadecimal. A prepared entry
contract describes a particular calling boundary; it does not imply that every
raw record, alias, application mode or complete keypress workflow is supported.

| Guide | Contents |
| --- | --- |
| [Parser](parser.md) | Token decoding, stacks, priorities, operand admission and completion |
| [Numeric records](numeric-records.md) | Stored/raw ABI, decimal precision, rational and surd ordering |
| [Numerical kernels](kernels.md) | Major algorithms, native entries and handwritten C sources |
| [Corrections and limits](corrections.md) | Findings that supersede earlier interpretations and proof boundaries |

The completed instruction ledger classifies **46,094 / 46,094 instruction
starts (100.00%)** in the pinned disassembly. This measures explained instruction
addresses, not implemented C, executed paths, test coverage or firmware parity.
The independent audit also identifies data outside that instruction denominator.
The implementation remains incomplete: see [C scope](../../../csrc/scope.json)
and [implementation overview](../../../csrc/README.md). The session handoff in
`AGENTS.md` records a current warm STAT scratch/cache discrepancy and remaining
verification work; no new firmware audit or fix is implied by this guide.

Production code is readable handwritten C. Original firmware execution through
`tools/nxu8` serves only as the independent test oracle. Production C retains
immutable ROM data for fonts, tables and constants. Semantic prototypes and
native-only traces in `analysis/understanding/` are evidence, not automatically
production implementations. Source-pinned receipts in `analysis/c-verification/`
state the narrower tested inputs, outputs, status and memory boundaries.

Primary scope evidence: `analysis/understanding/final-closure/semantics/FINAL-100-LIMITS.md`.
