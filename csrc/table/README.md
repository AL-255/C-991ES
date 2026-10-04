# Prepared TABLE row generation

`fx_table_generate` implements the TABLE88 row controller entered at original
004F26. It accepts the complete65536-byte RAM view, a RAM word containing the
expression source address, and named evaluator/device callbacks. The evaluator
receives actual mode88 and continuation1. Its success channel is unsigned255;
negative host statuses remain implementation gaps. Math3 publishes F3 and
continues; other native errors stop before committing the failed row.

The controller validates Start<=End and Step>0, calculates a cleaned decimal
quotient then floors it, and enforces30 rows for one function or20 for two.
Start and End reject exact-form tags. Step accepts an unmarked rational or a
marked decimal; a marked rational is rejected during initial admission but is
accepted by X-increment arithmetic if a callback later installs it. Each row
rereads the live column policy and row capacity; each increment rereads live
Step. A second pass preserves X/F while writing G. Cancellation retains every
already committed row. Final source-word writes retain their physical aliases.

The implementation contains no firmware execution. The differential verifier
executes original004F26, records its actual171EA and5550 boundaries, and supplies
those observations to the C callback seams. It compares all persistent RAM,
including all16 physical rich payload slots. Only the measured original CPU
frames and8000..80DB arithmetic-register arena are outside this named API.
The complete original initial/final RAM and callback/poll mutations are kept.
ROM source-pointer words and wraparoundFFFF are three explicit host gaps.
This verifies the row kernel; the actual TABLE expression parser is a separate
integration task and is not replaced by ordinary COMP contextC1.

Run fresh production-path comparisons and canonical publication with:

```sh
python tools/test_table_c.py --optimization O2
python tools/test_table_c.py --optimization O3
```

O3 publication also pins the preceding passing `table-O2.json` canonical
report for the same C/H,
numeric dependencies, test source and bundled predecessor archive. `--no-report`
keeps diagnostic results without canonical publication. `--predecessor` accepts
a different original archive; its hash is captured before compilation and
rechecked after execution. Reports and complete fresh observation archives are
under `analysis/build/table`; canonical metadata is
`analysis/c-verification/table.json`.
