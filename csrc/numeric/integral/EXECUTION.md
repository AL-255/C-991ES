# Real adaptive integration

The standalone readable C API is `fx_number_integral` in `fx_integral.c`.
Its numerical driver corresponds to native entry `0x046EE`; the parser maps
raw token `0x6A` to this entry through the category-zero dispatcher at `0x16BB0`.
The implementation uses fifteen-digit integer-decimal records throughout.
The original ROM is executed only by the independent test oracle.

## Native expression and callback contract

`0x046EE` requires evaluator mode R6=0. It scans the body using `0x171EA`
with R6=255, then evaluates lower and upper bounds with R6=2. The saved body
cursor is re-used for each R6=1 callback. Bounds and an optional tolerance
pass through `0x15C82`, which converts exact rational/surd records to decimals
and clears decimal metadata. A negative tolerance returns F8; omitted
tolerance uses1e-5. The outer evaluator dispatcher saves/restores global X;
the standalone API instead owns a local X record passed to its callback.

The native comparison at `0x1CD94` uses the thirteen-digit cancellation gate
at `0x1BBD8`. Consequently1 and1.00000000000001 are treated as equal bounds.
Equal bounds still evaluate the upper endpoint, then the lower endpoint,
before returning zero. Other bounds evaluate lower then upper. Endpoint
errors produce F3, and endpoints have no cancellation polls.

The callback must return a valid scalar record or a native error record with
host status `FX_NUMERIC_OK`. Native callback/arithmetic errors yield F3.
Negative host callback statuses are a separate API failure channel and leave
out unchanged. The standalone module permits out to alias any bound or
precision record and never alters the input records or global variables.

## Embedded7/15-point rule (`0x04544`)

Compute halfwidth=(right-left)/2 and midpoint=(right+left)/2 using the original
finite-decimal subtraction, addition and division wrappers. A zero or invalid
halfwidth fails with F3. Evaluate the midpoint, initialize separate Gauss and
Kronrod weighted sums, then visit three common node pairs and four extra
Kronrod pairs. The original ten-byte records at ROM0x2B08..0x2BC6 remain
constant data; the last Kronrod weight is0.204432940075299.

Each pair first polls cancellation, multiplies node*halfwidth, computes
leftX=-(offset-midpoint), evaluates left, computes rightX=offset+midpoint,
and evaluates right. Add the two values and apply native integer cleanup.
Accumulate the Kronrod weighted pair before the Gauss weighted pair. Rational
callback records are converted by the ordinary scalar operand loader;
quadrature does not use exact rational arithmetic. Surd callback results are
decimalized because calculus evaluation disables natural surd production.

After the seven pairs, clean and normalize each weighted sum, multiply each
by halfwidth, and estimate error=abs(Gauss-Kronrod), with native cleanup.
The Kronrod sum is the block result. Each block therefore has fifteen body
callbacks and seven cancel polls. Before the first block there are the two
endpoint callbacks.

## Tolerance and refinement (`0x04696`, `0x046EE`)

Compare error with max(abs(tolerance*blockResult),1e-10), preserving original
finite-decimal operations and `0x1CD94` cancellation behavior. An overflow
while computing the tolerance scale selects acceptance. The initial block
returns immediately only on strict acceptance; a failed or equal initial
comparison causes the initial interval to be evaluated a second time.
Subsequent comparisons accept equality as well as a larger threshold.

The driver walks the dyadic subdivision tree in depth-first, left-to-right
order. It stores a dyadic index, denominator, accumulated accepted result,
refinement depth47 and total rule budget324. New endpoints preserve the
native finite-decimal sequence
(index+1-denominator)/denominator*originalSpan+originalLower. Backtracking
uses the corresponding index-denominator form, without replacing the
sequence with host floating arithmetic or a mathematically equivalent
expression that rounds differently.

At depth exhaustion, `0x1CD60` compares total+blockResult with total using
ordinary subtraction; a contribution that cannot change the total may be
accepted, otherwise return FB. Exhausting the rule budget also returns FB.
Cancellation returns F1. Final results receive native integer cleanup.

## Verification boundary

Integral and derivative adapters can distinguish an evaluator's native
success/failure condition from its value record using the positive
`FX_CALCULUS_EVALUATION_OK` and `FX_CALCULUS_EVALUATION_ERROR` statuses.
Legacy zero plus an F record still means callback failure. Negative returns
remain host failures and leave the output untouched. Sum/product retain the
legacy contract.

A successful bare-variable callback may carry an F record after the
evaluator's `0x1415A` cleanup. The integral ignores its two endpoint values;
it also does not check the midpoint weight multiplications at `0x045C6` and
`0x045DA`. The first checked symmetric-pair addition then detects F3, after
five callbacks and one poll. This order is preserved by checked and unchecked
arithmetic helpers, without adding or suppressing callbacks.

The two scalar preparation paths differ. `0x15C82` rejects an unmasked
header above `0x4F`, leaving that value unchanged. Ordinary `0x1BFxx`
arithmetic first calls `0x1AB64`, which clears bit40 on every non-F header.
Thus a surviving backed `0x61` matrix reference is interpreted as its raw
rational payload by ordinary arithmetic; the matrix cells are not projected
into a scalar. A zero-dimension reference instead becomes F9 during callback
cleanup. These behaviors are tested against complete native expressions with
explicit bank dimensions and cell contents.

`tools/test_numeric_integral_c.py` executes complete original native
expressions and compares all ten scalar output bytes, the native twenty-byte
real/imaginary record, every callback X record in order, every cancel poll,
X restoration, output aliases and host callback failure behavior. The test
adapter supplies the timer's no-cancel or selected-cancel response at0x5564;
every original instruction still executes. It does not patch the ROM or
substitute arithmetic callbacks in the native path.

This module covers prepared real scalar integration. Token grammar, cursor
consumption and global variable transactions belong to the evaluator module.
Complex callbacks, malformed BCD, reset and physical keyscan paths remain
outside this verification scope. Understanding percentages count inspected
instruction addresses, not complete-firmware equivalence.
