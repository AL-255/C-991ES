# Decimal trigonometry, hyperbolic functions and special-result recognition

`fx_trig_math.c` calculates sine, cosine and tangent in readable C using the
firmware's decimal arithmetic. It uses integer coordinates and decimal digit
rotations, with ten stored arctangent coefficients as data. It uses no host
floating point, CPU interpreter or firmware calls. `fx_trig_decimal` accepts an
angle record and a resolved degree/radian/grad unit; `fx_trig_evaluate` then
applies the special-result replacement stage. `fx_angle_convert` implements
the nine explicit angle-unit conversions.

`fx_trig_inverse.c` calculates inverse sine, cosine and tangent in the resolved
output unit. `fx_trig_inverse_decimal` uses the same three function identifiers
as inverse selectors. Its independent `fx_atan_quarter_fraction` boundary
returns atan of an unsigned decimal argument in[0,1] as a quarter-turn
fraction. Raw input tokensB0/B1/B2 dispatch to the original inverse entries;
the ordinary forward tokens areA0/A1/A2.
`fx_atan_quarter_fraction_guarded` also accepts a prepared seventeen-digit
integer mantissa and exponent, retaining both guard digits at the kernel
boundary. The ordinary record entry preserves its native metadata bias
before entering that shared kernel. Complex atan2 must still retain the
original y/x followed by reciprocal operation order; extra precision does
not replace that sequence.

`fx_trig_hyperbolic.c` implements sinh/cosh/tanh and their inverses through
`fx_hyperbolic_decimal`, using the same three function identifiers and an
inverse flag. These functions are independent of angular units. The raw
tokens are70/71/72 for sinh/cosh/tanh and90/91/92 for asinh/acosh/atanh.

The forward calculation preserves the original operation order. It makes
rational/surd inputs decimal, removes decimal metadata marker40, takes the
unsigned angle, multiplies by its quarter-turn reciprocal, cleans small
decimal residue and rounds to the nearest quarter-turn count. It subtracts
that count times90degrees, storedpi/2 radians or100grads. The reverse-subtract
operation discards tiny cancellation residue through its own filter. The
remaining angle becomes an unsigned fraction of a quarter turn.

The angular kernel stores eighteen-digit decimal coordinates, including two
guard digits, in bounded `uint64_t` integers. Its first phase subtracts scaled
arctangent coefficients and saves rotation counts at seventeen decimal
positions. Its second phase reconstructs the coordinate pair by repeated
`x += y` and `y -= old_x * 10^(-2k)` operations. Decimal shifts, workspace
overflow, normalization, guard rounding and truncation follow the original
routine. `fx_trig_decimal_pair` exposes this independent kernel boundary.
The caller selects coordinates by quadrant and function, reconstructs sine
or cosine through the original divide/square/add/reciprocal/sqrt sequence,
or obtains tangent by division, then restores the sign. Range failures and
tangent poles return the original error record, including its sign field.

Inverse sine and cosine preserve the original domain-reconstruction order:
they calculate `sqrt((1+x)*(1-x))`, then select the smaller/larger coordinate
quotient. Inverse tangent uses coordinate1. The inverse kernel rotates
`x -= y` and `y += old_x * 10^(-2k)` while saving count digits, then reconstructs
the angle by adding stored arctangent coefficients. It preserves the original
index adjustment, guard fields, normalization and final rounding. The caller
multiplies by the selected quarter-turn angle, cleans decimal residue and
restores signs/complements in the original operation order. The same rational
preconversion cleanup must run first; the verified -717/3946 regression checks
that precision boundary explicitly.

Hyperbolic sine/tangent and their inverses use the original fourth-order
corrections below magnitude.013, avoiding cancellation in exponentials and
logarithms. General forward functions combine exp(x) and its reciprocal.
Inverse sine/cosine use reciprocal-based root reconstruction for large
arguments; inverse tangent calculates sqrt((1+x)/(1-x)) then ln. Each operation
retains the original15-digit storage boundary. This preserves sign-dependent
last digits and range behavior, including tangent saturation after exp
overflow. The exp/ln kernels come from the high-level numeric subsystem.

`fx_trig_special_result` accepts an already computed decimal function result
and the resolved exact-output permission. Sine and cosine share five positive
magnitudes and tangent has four. It compares absolute numeric values through
the original15-digit subtraction: a difference below5e-13 matches, while
tangent's two larger magnitudes use5e-12. A match selects a fraction/surd
record when exact output is permitted, or the stored decimal otherwise, then
restores the sign. These are numeric records consumed by ordinary arithmetic
and formatting; the table does not contain preformatted display strings.

`fx_math_context.c` resolves the original18212 exact-output permission from
the application memory image. It rejects state80F5==ED, bit6 of80FC, disabled
Math output8106, complex format810C==1, a clear bit6 in mode80F9, or bit0 of8124.
The capability byte1FFE1 is fixed zero in this firmware variant. The trig
APIs continue to accept the already resolved permission so callers can use
either explicit configuration or the memory-context resolver.

Run `python tools/test_trig_c.py` for the independent replacement-stage suite.
Run `python tools/test_trig_math_c.py` for native coordinate pairs, all explicit
angle conversions, complete numeric cores and complete wrapper comparisons.
The latter covers ordinary, rational, signed two-term surd and marked decimal
inputs; every function and unit; tiny/large angles, quadrant/pole/cancellation
boundaries, range/error controls, source immutability and aliases. Their
source-pinned reports are `analysis/c-verification/trig.json` and
`analysis/c-verification/trig_math.json`.

Run `python tools/test_trig_inverse_c.py` for the independent inverse kernel
and complete inverse numeric core comparisons. It checks all output units,
ordinary and marked decimals, rational/two-term surd inputs, domain endpoints
and failures, tiny/huge arguments, aliases and source immutability. Its pinned
report is `analysis/c-verification/trig_inverse.json`.
The suite separately varies the prepared guard byte through all100 values
at five exponent boundaries and compares random guarded mantissas directly
with the native kernel.

Run `python tools/test_trig_hyperbolic_c.py` for all six real hyperbolic
wrappers, including threshold/domain/exp-range boundaries, tiny/huge inputs,
marked decimals, rational/surd conversion, errors, aliases and immutability.
Its pinned report is `analysis/c-verification/trig_hyperbolic.json`.

Run `python tools/test_math_context_c.py` for native exact-output eligibility
across each complete byte-valued state domain and combined restrictions.
Its report is `analysis/c-verification/math_context.json`.

The APIs resolve configuration through explicit arguments. They do not
reproduce scratchRAM writes or global UI effects. Noncanonical BCD inputs
and complete reset-to-keypress I/O remain outside this
subsystem's verified scope; `manifest.json` records those gaps. Instruction
coverage and these prepared routine tests do not establish full firmware
completeness.
