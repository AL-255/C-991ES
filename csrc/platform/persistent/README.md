`fx_persistent` exposes result clears, format/selection state, variable/Ans
copies and the calculator's replay store as readable C. Its production code
has no CPU state or instruction-execution interface.

Variable slot0 is M, slot1 is Ans, and slots2..9 hold A..F/X/Y. Address APIs
preserve native forward-copy overlap behavior; supplied-record APIs accept
immutable host values for cases such as a transformed Ans temporary. ModeC4
stores both components, while other modes preserve the existing imaginary
variable slot.

Replay entries contain flags, the format byte, the complex-display byte,
a ten- or twenty-byte result, expression tokens and a colon delimiter. They
live in a mode-dependent250-byte store separate from renderer history9800.
Append evicts complete oldest entries, compacts retained entries and preserves
the original clearing/writing order. Recall restores editor, result, format,
flags and navigation from the admitted index8113.

`fx_replay_append_prepared()` starts after native imaginary classification at
1EA3E. The caller supplies a semantic classification byte, without allocating
CPU locals or copying register snapshots into RAM. Classification1 selects
ten result bytes; every other byte selects twenty. The convenience append
API classifies an immutable record. Its native operand-workspace differences
remain an explicit gap.

The prepared policy requires complete entries within250 bytes and a valid
recall index. Recall expressions fit the99-byte input limit. Native capacity
no-ops are retained; length wrapping, missing continuation delimiters,
unterminated stores and the native251-byte finder overflow are rejected before
replay modification. Caller-supported variable slots are0..9.

`tools/test_persistent_c.py` verifies these interfaces against the original ROM.
Prepared append and recall compare whole RAM and callbacks, excluding only
native CPU stack8D00..8DED. Convenience append additionally excludes numeric
operand scratch8000..80DB. The canonical report distinguishes native
comparisons from explicit C-only malformed-domain checks and pins its input
hashes before compilation.
