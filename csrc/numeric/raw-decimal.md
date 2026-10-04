# Finite decimal boundaries used by rich dispatch

The readable value adapters reproduce the unchecked scalar conversion reached
when matrix token88 wraps its operation index into the natural exponential.
They use finite decimal arrays and integer coefficients. Production code has
no instruction decoder, CPU state, ROM execution or host floating point.

The calculator's external number occupies ten bytes. Arithmetic uses the same
value as packed exponent, raw sign, then eight packed mantissa pairs ordered
from least to most significant. This representation matters when reference
metadata is admitted as marked fraction data: a nibble outside0..9 must retain
the original decimal correction rather than being rejected or coerced early.

The complete prepared scalar flow is:

1. The rich dispatcher allocates a new temporary for matrix88, copies all90
   bank bytes and both dimensions, rewrites only the low reference identity,
   then releases the original temporary. The work imaginary ten bytes survive.
2. Original1BAC4 clears the marked bit while loading the external record.
   Original19F1A enters its805A<11 decimal-output conversion path. The adapter
   snapshots the complete input before writing any aliased result.
3. Fraction construction adjusts the raw length once, shifts the full nine-pair
   field including raw sign padding and scans for the first delimiter. LowA or
   highA..F terminates a field; lowB..F can remain data. Missing or late delimiters
   follow the native field arithmetic rather than a validation-error shortcut.
4. The first field builds the denominator with sign1. A second delimiter, if
   present, separates the middle numerator from the whole component. The whole component starts at byte0x14 (BCD14); only it is
   normalized at this point.
5. A mixed fraction computes normalized whole×raw denominator, then adds the
   unnormalized middle. Both operations use the original finite pair correction
   and order. Division estimates each quotient digit with a cached triple
   divisor and retains the seventeen-digit workspace. Low-four-digit cleanup
   and scalar normalization finish the converted decimal at original1C27C.
6. Ordinary valid decimal values use the existing high-level natural-exp API.
   Unchecked digits multiply by all seventeen stored coefficient digits
   `43429448190325183`, keeping the ninth guard pair. Whole decimal powers and
   the fractional coordinate are extracted in the native finite order.
7. The initial factor subtract-one probe controls the zero case but is discarded.
   The first actual logarithm-coefficient subtraction corrects the raw pairs.
   Its equivalent coordinate is `(corrected difference + coefficient) mod10^18`.
   An independent original A/B execution compared complete factor outputs and
   residual records. The unchanged guarded transcend kernel accepts this
   prepared coordinate without renormalizing it.
8. The result adds the packed whole exponent, applies the native overflow guard,
   and takes an ordinary finite reciprocal for negative arguments. Final
   normalization and external serialization retain the complete error payload.
   Original1BB28 returns its low header nibble as native status, separately from
   the C adapter's host status. The dispatcher then applies its normal scalar
   cleanup and commits the20-byte work result.

The original factor's isolated prefix00 state wraps an internal exponent; it
cannot be represented as an ordinary−100 factor call. In this prepared natural
exponential, the same state comes from an earlier large product. The native
whole-exponent guard determines positiveF3 or negativezero, so the adapter closes
that branch before calling the guarded factor API.

The canonical [native suite](../../tools/test_raw_decimal_c.py) compares direct
component, normalization, cleanup, quotient, product, sum and seventeen-digit
guard checkpoints, then complete conversion/exp results and native status.
Exact and partial aliases are included. Every expected value is reexecuted
from the unchanged original firmware during the test; historical expected
records and the CPU harness are never linked into production.

Raw nondecimal sign/exponent pairs can make the plain-add ordering loop repeat.
The C implementation detects that exact finite state and returnsUNIMPLEMENTED
without writing its output. Tests retain the corresponding original full-register
and entire-RAM repetition evidence instead of dropping those cases. Other
19F1A pair-output contexts, extended precision callers and physical state are
outside this prepared value contract. Full firmware completion remains false.
