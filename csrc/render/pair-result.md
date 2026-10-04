# Paired result display

`fx_display_pair_result` implements the prepared B070 path selected by
RAM80FF bit4. It receives the address of two consecutive ten-byte scalar
records, preserves those caller records, and formats both components even
when either or both are zero. It reuses readable numeric conversion,
decimal-budget, DMS, glyph, viewport and history semantics; the production
implementation never executes the original image. ROM access is font and
immutable spelling data only.

Status values are **decimal**, not hexadecimal:

| RAM80FF | First label | Second label |
| --- | --- | --- |
| 17 (11 hex), Rec | `X=` | `Y=` |
| 18 (12 hex), Pol | `r=` in legacy output; radius glyph9D in natural output | theta glyphC4 followed by `=` |
| 19 (13 hex), SOLVE | ROM1056 indexed by the complete83FC byte, followed by `=` | `L-R=` |
| 20 (14 hex), Qrem | empty | `R=` |
| every other byte with bit4 | `F=` | empty |

All128 bit4 status bytes are admitted. Other status bytes are outside this
API. The equation and inequality result controllers dispatched earlier by
B070, mode137 serialization, and native stack-backed natural output in
modes without persistent result scratch remain separate subsystems.

Status19, or absence of both natural-input and natural-result permission,
sets the entire8100 byte to10 and clears8130 before formatting. Other
paired statuses preserve the current selection. A permitted cached result
then bypasses numeric source access, including invalid source addresses.
Status19 invalidates that cache and reads the new root/residual records.

C060 first admits F* errors: all emit `ERROR` except FD, which emits an
empty value; the returned kind is0. Successful DMS formatting is tried
before the paired decimal path and returns kind1 without committing the
current/previous-kind byte. Failed DMS and previous-kind restoration retain
the exact3644 cache and selection mutations. Remaining values use3500's
fixed budget12, independent of Fix/Sci settings8102/8103. Status20 alone
extends the low normal-display threshold from exponent−2 to−3. This path
does not enter ordinary AB8E fraction/surd recognition or its LCD sleep
side effects. The initial selection, rather than its later value, decides
whether the final combined result kind is committed.

Legacy rows are right-aligned at baselines12 and22. Label/value composition
appends all16 ROM spaces before inserting an earlier NUL and appending the
numeric text. Dormant padding bytes after the final NUL are retained in
persistent output scratch. History includes both fields separated by CR.
Natural output joins both fields with the ROM comma when8104 is nonzero,
or semicolon otherwise; it then runs the same two-pass viewport and history
policy as ordinary output. Optional CMPLX196 polar preference still converts
the copied numerical pair before formatting: the paired status itself does
not suppress382E's earlier conversion decision.

The complete canonical command is `python3 tools/test_render_pair_c.py`.
It passes63,555 complete B070-plus-flush cases,141 portable API admission
checks and606,585 memory/pixel comparisons against the unchanged original
firmware. The127,587 original calls comprise64,032 B070 calls and63,555
flush calls. The477 additional
B070 calls are **architectural nonreturn boundaries**, not pixel passes:
when result space is required and the byte-valued total height is at least63,
3922 wraps its retained-byte count and overwrites native return-frame
memory. Their actual native PC/SP, RAM digest and write count are recorded;
the portable implementation returns−1 after preceding formatting writes.
Byte wrap and width-fit cases that avoid this corruption remain supported.

The source-pinned report is
`analysis/c-verification/render_pair.json`. Coverage includes all status and
selection bytes, all256 SOLVE variable-label indices, full error headers,
DMS success/fallback, both display styles, fonts6/7/10, persistent cache,
fixed precision independence, all256 DMS precision bytes in both Fix/Sci
settings, angle-unit/polar behavior, all byte-valued width/height states,
5,000 random valid records, poisoned dormant output,
history9800..98FF, state80F0..813F,384 framebuffer bytes, all512 LCD bytes
before/after flush, and MMIOF031.

This is a prepared semantic API, not whole-RAM or CPU-ABI parity. The
caller must keep source records disjoint from persistent controller state,
output, history and frame buffers. Numeric workspaces, inactive metric
slots, temporary stack addresses, CPU flags/registers, and reset-to-keypress
timing are not exposed by this interface. Full firmware completion remains
false.
