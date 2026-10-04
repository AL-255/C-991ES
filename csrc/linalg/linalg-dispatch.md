# Typed matrix/vector dispatch

`fx_linalg_dispatch_unary` and `fx_linalg_dispatch_binary` connect already parsed
20-byte operands to the original fixed-bank numerical operations. They do not
parse tokens or execute firmware. The context contains calculation mode6/7 and
the existing numerical context; bank state is explicit and mutable. Ordinary
scalar-only inputs return `FX_NUMERIC_UNIMPLEMENTED` for the shared evaluator's
scalar path. Unsupported raw tokens leave output and bank untouched.

The original entry16336 starts with the current right work record for a binary
operator. It checks that argument where required, copies its real record to
work+20, and pops the previous left real record from the10-byte value stack.
Those transfers preserve the current right work record's imaginary/scratch
bytes. The typed binary result preserves the right imaginary record accordingly.
Complete entry171F4 in contexts6/7 copies only the final real record to its caller:
the caller's secondten bytes remain unchanged. The parser adapter must preserve
this distinction between work-record state and final result copying.

Ordinary +,−,×,÷ skip16A14 admission before rich rewriting. Dot9E validates
right then left with flags0. Real-only nthroot/nPr/nCr/logbase validate both with
flags7. General power validates the right with flags3, then rejects a matrix
left with Syntax2, or a vector left with Math3. Rejections retain the current
work real record and return status separately; the final evaluator owns error
record construction. Raw68 decodes unary log10 selector32 initially; after its
explicit second argument, the actual logbase16336 selector is35.

Named slots0..3 usually copy all90 bytes and both dimension bytes to first-free
slot4..8, then rewrite only the reference's low nibble. Existing temporaries are
reused. Matrix determinant and vector magnitude release a temporary input
before their scalar-producing leaf and allocate no new bank. Dot releases both
temporary operands. Ordinary binary operations allocate/reuse the left bank,
then release a rich right before their leaf. Errors and cancellation keep the
resulting bitmap, copied inactive cells and native partial bank mutations.
Scalar-left multiplication swaps the real operands and follows the same policy;
other scalar-left/rich-right ordinary operators reject before allocation.

Square/cube always allocate a new temporary, preserve the old bank reference,
then release the old temporary before multiplication. If an unmarked old
temporary is itself selected as the destination, the native second cube multiply
reads the newly squared bank in both positions. This produces a fourth power;
the readable implementation preserves this observable prepared-state alias.

High-F error records also reach rich rewriting for ordinary arithmetic. Error
IDs0..3 perform the persistent-bank copy; IDs4..15 bypass copying. Releasing a
right error ID uses the native count modulo8, which can clear low bitmap bits.
The numerical leaf rejects kind15 before reading a cell address, so a dummy
backing safely represents error IDs9..15. Actual6x/9x references beyond slot8
remain outside the safe bank API.

Vector magnitude cannot enable compact-surds recognition solely by setting8106
in contexts6/7:18212 requires calculation-context bit6, which these contexts lack.
The dispatch layer resolves that permission before calling the frozen magnitude
kernel. Post-leaf16562 cleanup applies only to successful real headers below60;
it does not infer status from anF record when the leaf explicitly returnedzero.

The differential suite invokes unchanged original entry16336 with its real
value stack prepared, supplying timer responses at5564. It compares full20-byte
work output,18 dimension bytes,810 bank bytes, bitmap, nativeR2 and poll count.
Fixtures include every temporary bitmap, slots0..8, dimensions0..3, full error
headers, decimal/rational/surd/marked cells, cancellation and record aliases.
Raw mappings are additionally audited through original171F4 expressions.

The native operation index also exposes scalar operations for some rich tokens.
The implementation retains these observable selections:

| Raw token | Matrix reference | Vector reference |
| --- | --- | --- |
| `61` | Forced new temporary, copy, release old temporary, then marked-fraction conversion and inverse cosh | Ordinary copy/reuse, then scalar conversion rejects kind9 with fullF3/status3 |
| `62` | Same staging, then marked-fraction conversion and inverse tanh | Same ordinary copy/reuse and scalar kind9 rejection |
| `5A` | REF | Normal-R scalar leaf rejects kind9 with fullF3/status3 |
| `5B` | RREF | Scalar bias addition rejects kind9; unchecked ten-digit extraction reads zero, then NOT serializes−1/status0 |
| `C3` | Vector magnitude rejects kind6 with fullF3/status3 | Vector magnitude returns a scalar but keeps its temporary allocated |
| `88` | Forced new temporary, copy, release original temporary, then marked-fraction conversion and natural exponential | Ordinary temporary staging, then exponential conversion rejects kind9 with fullF3/status3 |

Vector `5A`, `5B`, `88` and rich `C3` use the ordinary copy/reuse policy before
their scalar leaf. They retain that temporary allocation after returning.
Vector `63` remains a different path: it releases a temporary before magnitude.
The complete20-byte work result and the reference bank state are compared
independently; a numerical error does not roll back an earlier copy or release.

Raw `61`/`62` decode selectors7/8, become162/163 in rich selection, then the
eight-bit doubled table index wraps to entries1C4EA/1C4D8. Their function mode11
selects inverse hyperbolic cosh/tanh; mode9 belongs to separate inverse circular
entries. The wrapped functions are independent of the angle setting. Matrix
selection reserves a new slot, saves the old reference at work+20, rewrites
only the current low nibble, copies the complete bank, and releases the old
temporary before committing the bitmap and calling the scalar leaf. Vector
selection copies persistent slots and reuses existing temporaries. An exhausted
bitmap returns status7 before numerical work.

Ordinary zero metadata has a zero denominator and reaches fullF3/status3.
Canonical marked scalar variables also reach this path: for example the
marked1/2 record `61a20000000000000301` references bank1. Staging into slot4
rewrites its header to64, so unchecked scalar conversion sees4/2=2 and raw61
returns acosh(2). The implementation preserves the native finite fraction
conversion and invokes the existing high-level inverse hyperbolic helper.
Live tests compare prepared20-byte leaf payload/status and full171F4 named,
nested and marked-variable results separately, including near-one guards.

Malformed fraction fields can convert to nondecimal finite digits. If that
record is outside the ordinary hyperbolic helper's verified contract, rich61/62
return `FX_NUMERIC_UNIMPLEMENTED` with the earlier allocation/copy/release
retained and the result uncommitted. This boundary includes native executions
that do return a finite value: malformed record `6141d755588230e80fb0`, staged
into slot4, gives a native finite atanh result while the typed helper declines
it. This is distinct from the proven non-return boundary below and must not be
reported as an invented Math error.

Matrix `88` clears the marked header as the original scalar load does and then
interprets the reference's remaining bytes as unchecked fraction fields. Valid
reference metadata therefore can produce an ordinary exponential result, a full
error record or a zero result. The separate finite packed-decimal adapters retain
malformed nibble correction, sign padding, delimiter rules, operation order and
the seventeen-digit log10(e) coefficient guard. They call the existing readable
guarded factor kernel after the first actual coefficient subtraction supplies
an equivalent canonical coordinate; no approximate recognition or host floating
point enters this path. See [raw decimal execution flow](../numeric/raw-decimal.md).

Some arbitrary raw scalar additions never return in the original machine.
The numerical adapter detects their repeated ordering state and leaves its
output untouched. The native differential suite records repetition of every
architectural register and every RAM byte at1BC6C. If such a boundary is reached
after rich temporary allocation, those earlier bank mutations are retained and
the typed result remains uncommitted. This is an explicit execution boundary,
not a fabricated numerical result. No such non-return was observed in the
canonical rich-reference conversion corpus.

Physical timing, editor input and parent-owned parser/workspace mutations are
outside this value API.
