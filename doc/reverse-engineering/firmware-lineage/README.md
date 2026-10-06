# Firmware lineage and original emulator host

The supplied ePS calculator images use demonstrably different numerical implementations from the fx-991ES PLUS C Ver.4 ROM. A separate implementation is the best-supported working explanation; direct Casio derivation and complete independent authorship are both unproven. Possible asset reuse, a rewritten shared ancestor or an unexamined reused subsystem remain open.

[Implementation comparisons](comparisons.md) preserves numerical, binary, function-contract and parser findings. [Original Windows host scheduling](host-scheduling.md) documents the version-pinned emulator's STOP, queue, cancellation and timer contract. [Provenance](PROVENANCE.md) records inputs, methods and retained local evidence.

The emulator software's authorship is separate from the firmware it executes. Different CPUs or raw machine-code mismatch are not proof of independent authorship. Likewise, ordinary matching answers, decimal arithmetic and a96×32 display are weak ancestry evidence.

Original ePS ROMs, emulator code and all raw analysis are retained as **local-only references**. These documents do not restore those assets to repository history. No new Windows execution, firmware analysis, or parity test occurred during this documentation curation.
