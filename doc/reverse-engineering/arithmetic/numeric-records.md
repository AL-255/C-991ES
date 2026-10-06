# Numeric records and exact arithmetic

The public [fx_number](../../../csrc/numeric/fx_numeric.h) is ten bytes.
Stored records put the type/leading mantissa at byte zero, remaining mantissa
pairs at bytes 1..7, exponent at byte eight and sign at byte nine. The native
raw arithmetic workspace reverses that organization: exponent at zero, sign
at one, low-first mantissa pairs at 2..9, with the type nibble in byte nine.
Do not interpret a raw dump using stored-record offsets.

| Canonical type nibble | Meaning |
| --- | --- |
| `0` | Decimal |
| `2` | Packed rational |
| `8` | Compact two-term surd |
| `F` | Error-valued record |

Marker `40` is metadata, but each entry decides whether and when to remove it.
Raw type `10` is not a surd. Masking `40` globally would incorrectly admit
marked inputs at routines that explicitly require unmarked type `00/20`.
Rich reference records can reuse payload bytes; the enclosing caller and bank
context determine whether they are references or scalar arithmetic operands.

A nonzero decimal contains fifteen significant digits and represents
`sign × mantissa × 10^(exponent−14)`. Arithmetic retains native finite workspace
and rounding boundaries. Ordinary subtraction, cancellation-suppressed
subtraction and comparison are separate operations: the cancellation filter
can suppress a residue after thirteen leading cancellation digits. Replacing
these with host floating point, exact rational algebra or an exact comparator
can change results and control flow. Integer cleanup `1CEF0` removes tiny low
mantissa residue; it is not rounding to the nearest integer.

## Rational boundaries

The literal scanner stores at most fifteen significant digits. Recurring
marker A4 fills the remaining finite digit buffer and calls recognizer `11110`;
it does not build an unlimited symbolic recurring-decimal expression. Examples
include recurring .3→1/3 and .1 followed by recurring 23→61/495. Recognition
of eligible short rationals is a distinct operation from exact arithmetic on
an already packed rational record.

`19C76` extracts fields only from raw type `20`; marked `60` fails that gate.
The delimiter scan uses low-nibble A or high-nibble A..F. Whole and numerator
components carry the sign; denominator is positive. Selector zero returns the
whole component, one the numerator and two the denominator. Other selectors
have branch-dependent behavior and must not be generalized as another ordinary
field. The raw primitive has no newly invented R0 success-status abstraction.

The prepared [raw rational dispatcher](../../../csrc/numeric/fx_raw_rational.c)
preserves right-first component products, sign/GCD/quotient order, packing and
marker cleanup. Its API separates host failure from native numeric status and
supports the stated value aliases. Original scratch RAM, odd-pointer marshal,
registers and unbounded/nonreturning raw cases remain separate contracts.

## Surd boundaries

A compact surd represents up to two terms, each `coefficient × sqrt(radicand)
/ denominator`. [Component conversion](../../../csrc/numeric/fx_surd_components.c)
emits six ten-byte components into native pool `8640..867B`, in that order for
each term. Each store occurs before the next source field is read. A source
aliasing the pool can consequently change later components; a zero first
coefficient skips that term's radicand/denominator and emits 0,0,1.

Numeric conversion roots, multiplies and divides each term separately. The
second term is the left operand of the final addition, preserving native
rounding and error selection. The reduction adapter `174A0` reads coefficients
at offsets 0,20,40, whereas copy adapter `17C4A` copies a contiguous thirty-byte
triplet forward byte by byte. They are different layouts and different alias
contracts. The ordinary [numeric implementation](../../../csrc/numeric/fx_numeric.c)
provides exact Math-context rational/surd arithmetic, but a prepared scalar
API does not establish arbitrary malformed-record or rich-bank parity.

Evidence: `analysis/understanding/numeric-high/rational-peer/fields-v2/CORRECTION.md`,
`analysis/understanding/parser/SURD-ADAPTERS.md`,
`csrc/numeric/surd-components.md`, `csrc/numeric/raw_rational/README.md`,
`analysis/understanding/parser-fraction-coordinate/corrected-v4/FLOW.md`.
