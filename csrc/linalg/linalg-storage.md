# Matrix and vector numerical storage

`fx_linalg_store.c/.h` implements the prepared storage stage in readable C. It contains no firmware execution or host floating-point arithmetic. The native test oracle remains separate.

The calculator has one shared bank of nine objects. Each object stores a row byte, a column byte and nine ten-byte numerical cells. Its physical row stride is three. Small matrices and vectors still own all nine cells; copying an object includes inactive cells.

| Name | Raw token | Reference header | Shared slot |
|---|---|---|---|
| MatA / VctA | C8 / CC | 60 / 90 | 0 |
| MatB / VctB | C9 / CD | 61 / 91 | 1 |
| MatC / VctC | CA / CE | 62 / 92 | 2 |
| MatAns / VctAns | CB / CF | 63 / 93 | 3 |

The calculation context owns the bank's lifetime. MATRIX context is6; VECTOR context is7. In COMP contextC1, rawC8 is instead `PreAns`. The prepared native parser can load either reference kind in MATRIX or VECTOR mode, although that does not establish which names the keyboard UI offers.

Slots4–8 hold temporary results. `fx_linalg_bank_begin_evaluation` sets mask18 for MATRIX, reserving slots7/8; other prepared contexts start with mask00. First-free allocation searches bits80/40/20/10/08 in order. Marking and releasing preserve other bitmap bits. `fx_linalg_bank_temporary` copies a named object into a free temporary, rewrites only the low reference nibble, and preserves its other nine bytes. Already temporary references bypass allocation; exhaustion reports native status7 and retains the bank. The typed evaluator chooses when to request this stage.

`fx_linalg_bank_define` writes dimensions and clears all nine cells. `fx_linalg_bank_ensure_dimensions` preserves the complete payload when both dimensions already match. `fx_linalg_bank_reset` clears dimensions and cells, preserving the independently managed temporary mask. The native reset also calls a UI cursor initializer; that UI state is outside this numerical bank. Ans copying transfers the complete referenced object into slot3 without rewriting the supplied reference.

Reference admission checks whether the complete dimension word is zero. Zero returns status9 and preserves the output record. A nonzero partial dimension word constructs the reference successfully; a consuming numerical leaf subsequently rejects its missing row or column. This matters for native status parity: final evaluator cleanup can write an F9 record while preserving an earlier success status0.

Cell read/write helpers model native1D3C4/1D362. They accept slots0–5 and positive one-based coordinates within the stored dimensions, with a fixed maximum of3. Rejection returns native status2 and retains the record and bank. Both helpers transfer five two-byte words at offsets8,6,4,2,0. Their raw-byte access preserves native propagation when record pointers partly overlap a cell. Native zero-index or unchecked raw-address behavior is outside this safe prepared API.

The `value` and `store_value` adapters connect this bank to the numerical `fx_linalg_value` API. Committing a prepared leaf takes an explicit original slot ID, because its result reference may have become an error or scalar while its backing dimensions and cells contain native partial changes.

`tools/test_linalg_store_c.py` compares complete bank state, statuses, reference metadata and partial aliases against unchanged original-ROM helpers. The canonical report records14,859 checks across4,627 native calls; the same corpus passes GCC O2 and O3. Complete typed parser dispatch, keyboard/editor mode ownership and controller-level answer persistence remain separate subsystems.
