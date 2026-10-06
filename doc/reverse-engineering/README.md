# Reverse-engineered firmware knowledge

These guides preserve useful findings from the original firmware investigation.
They describe original routines and tested behavior, while identifying incomplete
implementation and evidence limits.

- [Natural display](natural-display/README.md): exact radical evaluation,
  rational/π recognition, special trigonometric replacements and rendering.
- [Arithmetic](arithmetic/README.md): parser stacks, numeric records, kernels
  and corrected interpretations.
- [Runtime](runtime/README.md): boot/input/controllers, host requests, LCD
  hardware indicators and remaining parity gaps.
- [Firmware lineage](firmware-lineage/README.md): related images and the
  original host's timer/key scheduling.

Routine addresses refer to the pinned fx-991ES PLUS C Ver.4 image unless stated
otherwise. Source links point into tracked high-level C. Paths beginning with
`analysis/` or `eps-emu/` identify retained local evidence; those directories
are ignored and absent from fresh clones. Large traces, generated reports,
screenshots and full disassembly are intentionally outside tracked documentation.

The 46,094-address instruction-understanding ledger is distinct from C
implementation completion and behavioral parity. The firmware audit remains
incomplete; [AGENTS.md](../../AGENTS.md) records the current stopping state.
The public browser uses the committed engine, while additional C/harness changes
remain pending locally.
