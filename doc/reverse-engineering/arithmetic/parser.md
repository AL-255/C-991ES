# Parser, stacks and operators

Input decoding at `159D0` reads packed twelve-bit entries from ROM `245A`:
eight bits of decoded value and four bits of syntactic kind. These input tokens
are distinct from the recursive tokens later produced for display. The handler
table at `25DA` covers kinds 0..10; larger kinds fail admission.

The ordinary evaluator `171F4` allocates a sixty-byte workspace: primary record
at +0, companion at +10, extra values at +20..39 and literal digits at +40..54.
`ER14` is the input cursor, `ER8` the result pointer, `R7` the previous syntactic
kind, `R10/R11` the operator/value depths and `R6` the callback owner. Callback
entry `171EA` reuses the existing frame and stacks rather than allocating a new
ordinary evaluation frame. The typed C implementation is
[fx_eval.c](../../../csrc/parse/fx_eval.c), with
[token decoding](../../../csrc/parse/fx_tokens.c) and
[completion](../../../csrc/parse/fx_eval_finish.c) separated.

## Stack transport

| Native routine | Contract |
| --- | --- |
| `1669A`, value push | Ten-byte slots at `8078`; reject depth >=10 before mutation; add one ordinary slot or two in live C4 mode |
| `166C8`, value pop | Reject depth zero; subtract one or two according to live C4, then read that slot |
| `166FC`, operator push | One-byte slots at `8060`; reject depth >=24 before mutation |
| `166EC`, operator peek | Read `805F+depth`, including depth zero; caller checks emptiness |

The native depths are wrapping bytes, not checked pair indices: C4 push at
nine reaches eleven, and C4 pop at one reaches 255. Ordinary startup physically
pushes `FF` then resets the logical operator depth. Finalization restores depth
one before consulting the retained byte. Physical scalar/pair transfers have
ordered chunk reads and writes; odd pointers and overlapping sources must not
be silently replaced with a generic ten/twenty-byte `memmove`.

## Priority and reduction

`1660E` calls operators >=38 reducible except 101/102 and 120..135. `16714`
assigns priority classes: 38..40→1, 41→2, 42→3, 43/44→4, 45/46→5, 47→6,
48..50→7, 51..94→9, 95..99→10, 100→11 and 101..119→12. Structural values
<=37 or >=120 have class zero. Aliases are 116→46, 118→55 and 119→105;
strong implicit multiplication 117 has class eight and executes multiply 45.

The comparator `16772` returns three decisions. Equal incoming/pending values
return one when reducible, otherwise zero. A structural pending value returns
two only for incoming 42. Ordinary values return zero when pending priority is
lower, otherwise two. Crucially, the incoming reduction caller `167A6` stops
fraction operator 100 on **decision one**, not two. It decrements the pending
depth before invoking `16336`; a numeric failure does not roll that pop back.
The raw editor `=` decodes to value 42/kind 2; raw comma is kind 9.

Forced drains at `16622/16626/1662A` have different structural stop policies.
They are not equivalent to repeatedly applying ordinary precedence. In
particular pending 115 is Syntax 2, pending 0..2 or 124 stops, and policy two
stops at 32..37 in this firmware because variant byte `11872` is zero.

## Admission and completion

`16336` checks the current/right operand first, then stages selected binary
operators and checks the popped left operand. `16A14` maps every F-valued
record to Math 3 regardless of its stored error code. Its masks separately
admit rich types, forbid classes 6/9 or require a zero imaginary companion in
live C4. Power 101 uses mask three on the right and mask one on the left;
a left class-six reference additionally yields Syntax 2. Callback selector
`R6=FF` can replace Math 3/Argument 8 with the zero template during scan-only
preflight; that is not an actual body result.

`17222` interprets the result byte as zero=continue, 1..127=error and
128..255=completion. Ordinary error rewind consults the actual byte at
cursor−1; callback error completion does not perform that rewind. Native
result status is byte `R0`, not a guarantee that the high half of `ER0` is zero.
A successful variable load can carry an F record without an evaluator failure.

Rich completion at `17258` permits headers 60..7F or >=90 only when `80FC`
is exactly one, invokes `1415A` integer cleanup, and preserves the original
completion condition even if that cleanup changes the record. Callback
completion skips ordinary output/cursor publication. The extra scalar copy
at `172E4` writes workspace +20 to output +10 and can overwrite an earlier
companion copy. Storage order and these status channels are therefore part of
the contract, not presentation details.

Evidence: `analysis/understanding/parser/EVALUATOR-STACKS.md`,
`analysis/understanding/parser/REDUCTION-LOOPS.md`,
`analysis/understanding/parser/ADMISSION-REDUCTION-ERRATUM.md`,
`analysis/understanding/parser/LEXER-TRANSFERS.md`,
`analysis/understanding/parser-literals/corrected/FLOW.md`.
