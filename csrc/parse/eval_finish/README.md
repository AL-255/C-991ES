# Physical terminal cleanup

`fx_eval_finish_cleanup` implements the prepared `1415A` reference cleanup with
the physical segment-zero storage view. It accepts all sixteen masked slot
identities and reads each cell from live RAM. It does not import a nine-slot bank
snapshot, allocate a temporary, copy a slot, or release a reference.

The leaf reads its dimension word once, then visits active cells in row-major
order. The native cell index is `(3 * row + column) & 255`. Earlier cell changes
remain committed when a later cell returns an error. The reference then receives
the cell's error code; type and empty-dimension failures produce F3 and F9.
Cells outside the visited footprint remain intact; no allocation-mask update is
performed. The address API preserves record/dimension/payload aliases and the
original ascending word stores at an odd reference address.

The leaf's numerical status is separate from the enclosing evaluator's terminal
status. Native `17274` saves and restores R2 around `1415A`, so a changed reference
or nonzero cleanup status must not replace the enclosing status. The enclosing
memory evaluator must also refresh its named variable and rich-bank views after
the physical writes.

The safe boundary includes the physical payload at `829E..883D`. A later cell
outside that range, or a malformed decimal outside the scalar cleanup contract,
returns `UNIMPLEMENTED` before that cell's write and retains prior commits. The
physical reference API rejects wrapping records and numeric/CPU workspace
overlap. These explicit host limits do not fabricate a calculator error.

The permanent live verifier has 2,600 unfiltered original leaf observations:
2,518 supported native completions and 82 explicit host limits. It also checks
20 API guards and twelve original `17274` caller frames. All supported cases
compare persistent RAM, all sixteen dimension words, every active and inactive
payload byte, the full reference and separate leaf status. Only the scalar
leaf's `8000..80DB` workspace and measured CPU stack are excluded; the high-slot
aliases at `8640..87D0` are compared. The 82 limits retain their original sixteen
status0, thirty-four status3, and thirty-two CPU101 outcomes and are not counted
as parity.

Run `python3 -B tools/test_eval_finish_c.py`. The report is
`analysis/c-verification/eval_finish.json`. The original-only collector, complete
seeds, unfiltered observations and boundary annotations are in
`analysis/native-fixtures/eval-finish`.
