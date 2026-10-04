`fx_stats_normal_probability` implements the original P, Q and R functions with
integer decimal records. P integrates from minus infinity to the input; R is
the upper tail; Q integrates from zero to the absolute input. The common kernel
uses `t = 1 / (1 + 0.2316419 * abs(x))`, evaluates the original five-coefficient
polynomial in Horner order, and multiplies by `exp(-x*x/2)/sqrt(2*pi)`. Every
intermediate operation keeps the original fifteen stored decimal digits.

The literal coefficient `b1` is `0.319381503`, exactly as stored in this ROM.
The original pi literal is `3.14159265358980`. The implementation stores these
constants as typed data and executes no firmware instructions.

The native wrappers call rounding entry `1cc90` with parameter six. That entry
counts a leading workspace guard digit, so P/Q/R retain five significant
digits. For example, P(1) produces stored decimal `0.84134`. Error records at
the public input return unchanged, including the original status nibble.
Marked decimals are accepted; marked rationals and stored surds produce Math
error through the real-conversion path. Q returns the same result for opposite
input signs, and negative approximation residue is clamped to zero.

`fx_stats_standardize` implements the original t conversion using x mean and
population deviation from a prepared table. Its final subtraction uses the
ordinary real subtraction entry, unlike the cancellation-suppressing
subtraction in the centered statistics accumulators.

`tools/test_stats_normal_c.py` compares native return statuses and every output
byte, source preservation, output aliasing, prepared table boundaries and
full-size datasets. The port leaves mode lifecycle, live interrupts and CPU
scratch RAM to the controller integration.
