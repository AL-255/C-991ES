# Statistics numeric subsystem

`fx_stats.c` implements the original statistics calculations as readable C.
All arithmetic uses the shared15-digit decimal records and integer arithmetic;
the implementation does not execute firmware instructions or use host floating
point. The original CPU and ROM appear only in the differential tests.

The typed table contains row-major `x[, y][, frequency]` records. Native rows
start at RAM82ee, the unsigned byte at80de gives their count, mode80fa=1
selects one variable, and nonzero8109 enables the frequency column. Each kernel
retains row order, intermediate rounding, zero frequencies, original error
records/statuses, and both inputs unchanged. Prepared negative frequencies are
tested as native arithmetic behavior, even though they are not useful data.

| Native entry | C operation |
| --- | --- |
|13150|Count, or sum of frequencies|
|12ef4|Minimum/maximum, with reciprocal or logarithmic transformation|
|12fe2|Weighted sum and sum of squares, optionally transformed/centered|
|12de6|Weighted cross product, optionally transformed/centered|
|12afc|Weighted cubic and fourth moments|
|12a22|Weighted x²y moment|
|12d8e|Mean|
|12c2c|Population/sample deviation|
|118b2/118c4|Persistent80-byte moment cache|

`fx_stats_regression` supports all seven model selectors:2 linear,
3 quadratic,4 logarithmic,5 exponential `A·exp(Bx)`,6 exponential `A·B^x`,
7 power, and8 inverse. `fx_stats_predict` calculates either direction and both
quadratic inverse roots. Coefficients A/B/C and correlation are ordinary
native decimal records, including original Math-error records.

Regression first transforms the dataset for the selected model, finds the
transformed minima, and accumulates centered moments. Linearized slope uses
`(n·Σxy−Σx·Σy)/(n·Σx²−(Σx)²)`. The intercept first uses centered coordinates,
then restores both minima. Quadratic fitting uses the original centered normal
equations and separately rounds every stored product, subtraction and division.
The native1bf90 subtraction suppresses tiny cancellation residues; the shared
`fx_decimal_subtract_cancel` API preserves that distinction. Final coefficient
and public-result cleanup matches1cef0.

Prediction retains the original arithmetic order. For example, inverse
exponential prediction computes separate `ln(y)` and `ln(A)` values before
subtracting; replacing those with `ln(y/A)` changes low stored digits.
Correlation follows the original denominator/square-root order and clamps
numeric results to−1..1 before public cleanup.

`tools/test_stats_c.py` compares every output record and numeric status against
the original entries, including forward/inverse predictions, rank failures,
empty tables, repeated points, zero weights, exponent boundaries and seeded
random data. `tools/nxu8/stats_host_events.c` executes every native instruction
and injects a prepared no-cancel host response at the original5550 polling
checkpoint; the passive oracle otherwise interprets an unanswered host request
as an interruption. It does not patch the ROM or skip instructions.

`tools/test_stats_cache_c.py` compares full RAM outside CPU stack scratch,
including overlapping cache aliases. Copies are ten independently snapshotted
8-byte chunks, which preserves native alias behavior that a whole-region
`memmove` would change. Store sets812a=1 before its first copy.

The calculator's statistics table editor, mode lifecycle, interrupt scheduling,
full numeric scratch RAM, and connection of cached moments to controller
queries remain outside this numeric subsystem's completed scope.
