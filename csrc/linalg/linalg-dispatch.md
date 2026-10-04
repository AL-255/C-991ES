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

Vector-tag REF/RREF and rich conjugate/argument have unusual native index
adjustments into unrelated scalar/base entries. This module reports those
untranslated prepared paths as `UNIMPLEMENTED`. Physical timing, editor input,
and parent-owned parser/workspace mutations are outside this value API.
