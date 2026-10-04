# Rich numerical dispatch after storage

`fx_eval_rich_dispatch` starts at the semantic boundary of native `16538`,
after `fx_eval_storage_stage` has allocated/copied operands, selected a leaf,
released the right reference and published the temporary bitmap. It never
stages those operands again. The caller owns the expression grammar and
terminal storage policy.

The working values contain ten-byte real and imaginary records. A `6x`
matrix or `9x` vector reference uses its low nibble as one of sixteen physical
identities. Dimensions are at `80E0 + 2*id`; the ninety-byte payload is at
`829E + 90*id`. Each cell address uses `10*((3*row+column)&255)`, matching the
native byte-sized coordinate. High identities can alias global state, so the
actual calculation context is captured before the leaf and retained for
cleanup even when a dimension write changes `80F9`.

The independently observed table selects add/subtract at indices 9/10,
scale/divide at 11/12, dot at 13, cross at 14 and matrix multiplication at 15.
Cross and matrix multiplication write their new dimensions before arithmetic
can fail. Elementwise operations commit each result immediately; scalar
factors are reread through their live working address. Dot accumulates in the
current record. Cross commits its three components after all minors succeed.
Matrix multiplication computes into a zeroed ninety-byte temporary and commits
it after success. Its adjacent tenth numerical record can alias output index
9; output index 10 enters native pointer/loop descriptors and is an explicit
unsupported architectural domain.

Surd arithmetic needs observable intermediate storage. Its thirty-two records
at `8640..877F` overlap rich slots 11–14. The mathematical seam saves current
to record 30, then rereads and saves other to 31; it expands terms, performs
ordered coefficient/radicand/denominator operations and a stable bubble
reduction while computing the result. Later cells are read after these writes.
Fallback converts only surds and preserves saved rational/plain/error records.
An initial error can be overwritten through a physical pool alias before
final numerical admission; the returned header and native status are checked
independently.

Unary dispatch includes magnitude, absolute, rounding, determinant, transpose,
negation, inverse and retained-reference square/cube. Determinant/inverse use
the original one-, two- and three-dimensional formula order and immediate
cofactor/division commits. Magnitude reads later components from live storage
after preceding root-workspace effects. Negation preserves the native adjacent
constant copy into the other imaginary record in CMPLX. Wrapped selectors
162/163/164 invoke the separately verified acosh/atanh/exponential leaves;
they are table indices, rather than guessed raw-token meanings.
ABS and ROUND use ordered live SURD component emission when the source
overlaps the physical component pool. ABS rereads the source after conversion;
ROUND retains the native adjacent cell+20 save and restore.

Every cancellation poll follows the native `5550..557C` order: set `8E00=2`,
start the `129A` timer, invoke the callback at the `5564` seam, publish
cancellation flags if requested and consume `8E00`. Callbacks can observe prior
physical commits and modify live operands. The evaluator adapter must refresh
its variable/bank views before calling its external cancellation control.
No timer polls are fabricated after an operation has completed.

Selectors 16/17 perform REF/RREF with live pivot searches, ordered row
products and subtraction, and delayed ninety-byte copies where the native
leaf retains them. Pivot magnitude classification copies the candidate once
to a private record before classification and absolute value. Callbacks see
all committed physical records and pending-copy behavior at each actual
poll. Wrapped vector selectors 21/22 follow their separately observed
rounding and bitwise-NOT policies. Reduction returns through the public
dispatcher, which applies shared post-leaf cleanup exactly once. Positive
shapes fit the nine-record native scratch buffer when
`3*(rows-1)+columns-1 <9`; this includes 1×4..9 and 2×4..6,
with the native stride of three and overlapping row coordinates preserved.

Post-leaf cleanup follows the captured context. A nonzero native status skips
cleanup. CMPLX skips a compact real surd, cleans only a marked ordinary real
record, and otherwise cleans both components. Scalar contexts skip tagged
headers. Thus a callback can leave an error-valued current record with native
status zero; this stage preserves that distinction.

Run `python3 tools/test_eval_rich_c.py` and its `--optimization O3` variant.
The complete default runs each execute 8,844 native calls and compare 73,004
observables, including 380 callback controls and 1,840 full-RAM callback
snapshots. The additional unary suite replays all 9,206 archived cases plus 545 ordered
alias inputs and checks 280,868 observables, including 480 wide-norm controls.
It handles 9,487 calls and retains 86 finite host gaps and 178 native execution
boundaries; exactly 41 former alias gaps are now handled. The separate
public-dispatch reduction suite runs at both O2 and O3; each run executes
6,642 original calls and checks 152,539 observables, preserving the original
5,427 inputs and adding 1,215 distinct wide inputs plus 29 compiled ABI checks.
It handles 6,556 calls and retains 86 named prepared boundaries. For 72 arithmetic/classifier
boundaries it checks exact RAM at the reached native kernel entry and every
preceding callback; the remaining 14 preserve output noncommit. All unsupported
finite outcomes and native execution boundaries remain individually declared
and freshly replayed. No original output is generated by the C implementation.

RAM comparison excludes the separate `8000..80DB` value-kernel arena and only
actual native CPU-frame writes witnessed for that call. All pool/bank bytes
and MMIO remain visible. The 172 direct scalar controls separately compare the
ten-byte result and all 1,440 payload bytes. Explicit limitations and exact
source pins are recorded in the manifest and canonical reports. These suites
do not establish complete firmware or whole-expression equivalence.
