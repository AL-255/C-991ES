# Prepared quotient and remainder

`0x1C138` implements the prepared numerical operation used by raw token `5F`.
It differs from `0x1C3FA`: the latter exports remainder first and quotient
second through a finite long-division loop. This wrapper exports quotient
first and remainder second. Its public result contains those two raw records
and the native numeric status. Inputs are copied before any output writes,
including partial aliases. It needs no bank, expression callback or timer.

## Admission and source records

Native `0x17442..0x1749E` converts an `8x` surd in the second source slot, then
an `8x` surd in the first source slot. Ordinary admission runs afterward.
`0x1AB64` checks the second raw header before the first and clears bit `40`
in arithmetic scratch. An original `F*` header causes status `3`: the first
result becomes `F3`, while the second source remains its preprocessed record.
Thus a marked decimal divisor retains its marker on this early exit, and a
surd divisor has already become decimal. The high-level result reproduces
these final source records without mutating either input.

`0x191CC..0x191E6` converts both admitted scratch records. Decimal payloads
pass through unchanged; `2x` fractions use the original unchecked packed-field
conversion, including mixed fractions. Other ordinary kinds become `F3`.
The same conversion runs again after reloading the source copies on fallback.
The separately verified raw fraction helper preserves those finite effects
for `6x` metadata payloads after bit `40` is cleared.

## Finite quotient policy

`0x190F6..0x191CA` admits two nonzero raw leading mantissa fields with raw
sign bytes below `5`, exponent prefixes below the representation of `1e10`,
and a packed-prefix distance below ten. For normalized positive decimals this
means both exponents are below `10` and differ by less than `10`. The C adapter
uses packed-pair correction directly; interpreting malformed nibbles as an
ordinary integer changes the original gate. All `256` values of each raw
exponent/sign byte are tested in either operand, across three value pairs.

The eligible path divides, truncates the quotient toward zero, multiplies the
truncated quotient by the divisor, then subtracts that finite product from
the original dividend. Arithmetic scratch contains eight packed mantissa
pairs, or sixteen positions. The inner quotient construction makes eighteen
digit estimates before exporting its sixteen-position coordinate.

The preceding divide corrects and normalizes the quotient prefix before the
integral truncation. The native oracle records that precondition at every
non-error `0x1B328` call, including malformed incoming prefix bytes. This
permits the private truncation policy to decode that normalized prefix.

Subtraction uses the `0x1BB3A` cancellation policy. Before normalization,
`0x1BD96..0x1BDCE` counts vanished leading nibbles. If at least thirteen have
vanished, it clears the low four mantissa digits and then normalizes. Ordinary
exact long division cannot replace this ordered calculation: the independent
finite-boundary corpus found `83` counterexamples to reusing `0x1C3FA`.
The small input-only regression file retains representative counterexamples.

An internal error-valued quotient passes the late gate immediately. Otherwise
the quotient exponent must remain below `10`. A zero remainder passes; a
nonzero remainder must have exponent below `10` and enough trailing zeros to
reach the packed threshold at `0x191A4`. For normalized positive decimals,
this admits remainders that are exact multiples of `.001`.

For example, `.025` divided by `.012` exports `2` and `.001`; `.0025` divided
by `.0012` fails the late gate and takes ordinary division. Negative operands
and zero dividends also take fallback. The fallback second record is exactly
`70000000000000000000`; its tag is part of the result, not canonical zero.
Two original `70` records both normalize to `F3`, then expose the accepted
internal error-quotient branch: the final records are `F3/F3`, status `3`.
An original `70` against ordinary `3` instead exports `F3/70`, status `3`.

## Status, context and scope

The wrapper returns the low error nibble of its first final record, otherwise
zero. Returned numeric errors are successful host executions with their
native status retained. Null pointers return `INVALID`; a bounded numerical
helper failure or unsupported malformed surd conversion leaves the entire
result untouched. The ordinary prefix-byte cases formerly considered for a
canonical-decoder restriction all return normally in the original and are
implemented; there is no blanket exponent/sign admission restriction.

The live suite retains the deterministic independent corpus and checks eight
output offsets, both-input aliases, untouched inputs and canaries. It executes
the original ROM for every expected record and status. Poisoned and reused
arithmetic, metadata and persistent-bank state is checked across Math policies,
context modes and screens. Native observations show no timer calls or changes
to the covered persistent records or metadata. The report pins every linked
C/header, the test, the native observation helper and input-only regressions.

The parser's raw `5F` decoding, precedence and terminal status `37` remain
separate. That status is a parser completion signal rather than this numerical
wrapper's status. Rich-reference bank fetching, physical interrupts, history,
display and unused scratch/register state remain outside this prepared API.
