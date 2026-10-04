# Decimal trigonometry and special-result recognition

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

`fx_trig_special_result` accepts an already computed decimal function result
and the resolved exact-output permission. Sine and cosine share five positive
magnitudes and tangent has four. It compares absolute numeric values through
the original15-digit subtraction: a difference below5e-13 matches, while
tangent's two larger magnitudes use5e-12. A match selects a fraction/surd
record when exact output is permitted, or the stored decimal otherwise, then
restores the sign. These are numeric records consumed by ordinary arithmetic
and formatting; the table does not contain preformatted display strings.

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

The APIs resolve configuration through explicit arguments. They do not
reproduce scratchRAM writes or global UI effects. Hyperbolic functions,
noncanonical BCD inputs and complete reset-to-keypress I/O remain outside this
subsystem's verified scope; `manifest.json` records those gaps. Instruction
coverage and these prepared routine tests do not establish full firmware
completeness.
