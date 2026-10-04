The complex record is twenty bytes: a ten-byte real record followed by a
ten-byte imaginary record. Each component can be decimal, rational, compact
surd, or an error. `fx_complex.c` expresses the native component formulas in
high-level C and retains their scalar operation order. Sources remain immutable;
the destination can alias either source.

The numeric APIs return a host status for malformed or unsupported arguments.
Handled domain errors remain numeric records, as elsewhere in this C port.
`fx_scalar_numeric_classify` implements the native scalar classification used
for complex admission: 1 means zero, 2 negative, 4 positive and F0 domain error.
`fx_complex_error_status` reads the first scalar error code, checking the real
component before the imaginary component; coordinate conversions can
place an F3 error in each component, while arithmetic places F3 in the real
component and zero in the imaginary component. Conjugation, negation, cleanup
and magnitude each preserve their own native early-error behavior.
`fx_complex_firmware_status` recovers the prepared native R0 return separately
from the record error and host API status. It takes the original input and the
computed result; callers using an output alias must retain the original input.
For example an F0 imaginary error has return code zero, so negation and cleanup
continue to the next component, whereas F1 through FF stop or normalize errors.
The conjugation oracle prepares ER4 as zero. Its native real-error branch
does not initialize ER4 before clearing a memory-selected imaginary record;
the evaluator sets ER4 to the routine address 0x86F4, preserving the input
record's imaginary bytes while clearing unrelated RAM. This memory side effect
is outside the pure value API.

`fx_complex_angle.c` implements argument and rectangular/polar conversion in all
three angle units. Polar records use the real slot for radius and the imaginary
slot for angle. Argument first stores `y/x`. When the ratio exceeds one, inverse
tangent stores its reciprocal; substituting `x/y` directly changes the last
digits because it removes an intermediate decimal truncation.

For example, with `x = 18.2295798319327` and `y = 27.4777813817710`, the stored
ratio is `1.50731841518575`. Its reciprocal is stored as
`0.663429830038113`; direct division would store `0.663429830038110`. The ordered
path matches the original argument result byte for byte.

Magnitude squares ordinary components only when both stored decimal exponents
fall in the safe interval from −49 through 48. Outside it, the smaller component
is divided by the larger before squaring. The result is square-rooted and then
multiplied by the larger component. This retains the firmware's range and
precision behavior for extremely large or tiny values.

Magnitude and square root classify scalar records before removing bit40.
Consequently, a marked rational with header6x is rejected by these entries.
On a zero axis, magnitude can produce an F3 radius while returning native
success; rectangular-to-polar conversion then keeps the successful angle.
For example `(0, marked 1/3)` produces an F3 radius and a 90-degree angle.
Argument checks its real preparation status before entering its coordinate
kernel, so its admission behavior differs from direct polar conversion.

The complex square-root entry accepts the native zero classification for its
imaginary input. A compact surd such as `sqrt(2)-sqrt(2)` remains a positive
classification after decimal conversion, so this unreduced imaginary record
is rejected. Negative real
values move the positive root into the imaginary component. An existing real
surd is converted to decimal before rooting. Nonzero imaginary input produces
the original domain error and preserves that imaginary record.

`fx_complex_round.c` implements scalar and complex display-precision rounding.
Norm uses ten significant digits; Sci uses its configured precision (zero
means ten). Fix preserves an already integral input, and otherwise multiplies
by its decimal scale, rounds to an integer, then divides by the same scale.
The complex wrapper handles imaginary before real. Its `firmware_status`
output distinguishes native rejection from the host API status and from a
numeric error header.

The independent oracle is the extracted firmware running in `tools/nxu8`.
`test_complex_angles_c.py` compares all twenty output bytes across named values,
random decimal values, rational/surd components, error records, both Math output
permissions and every angle unit. The canonical core suite passes 78,167 checks,
including direct scalar classification, metadata admission, compact cancellation,
all sixteen error headers and native return statuses. Coordinate coverage passes
13,091 checks, including special polar angles. Display rounding passes 21,232
checks. All passing reports pin implementation, test and oracle hashes. The
emulator and firmware are never executed by the C implementation. Full firmware
and expression/UI integration remain incomplete.

`fx_complex_dispatch.c` connects prepared numeric values to CMPLX input-token
operations without parsing expressions. The context contains native calculation,
angle and display settings plus the already resolved exact-output permission.
It supports imaginary-unit token 0x80, unary numeric functions, conjugate token 0x88,
argument token 0xC3, absolute token 0x63, negation, postfix powers and binary arithmetic/power.
Real-only binary functions include degree-first nth roots, permutations,
combinations and base-first logarithms; native admission checks the right
operand before the left, then runs the scalar leaf. The raw factorial input is 0x57. Token 0x97 is rejected
by the original parser and is unsupported by this value dispatcher.
The five public calls return the complete pair and a separate native status;
all source/output aliases are supported. The parser's preceding tagged-record
rewriting, variable commits and numeric workspaces remain outside this API.

The binary wrappers choose scalar arithmetic when both imaginary records have
native zero class 1. This matters for power: real-only values retain the general
real exponent algorithm, while complex exponents admit only reciprocal,
square and cube. Multiplication by exactly `i` rotates the component records,
clears the new imaginary marker, and preserves the forced native leaf success.
General real power's format guard can return native status 0x30 while writing an
F3 record; status is therefore not inferred solely from the output header.

The unary admission check precedes numeric functions. It uses the raw imaginary
exponent/sign word for ordinary real-only inputs, rather than converting the
imaginary component to test numeric equality. Rejected operands remain intact.
After successful leaves, native context cleanup skips a compact real surd;
a marked real decimal cleans only its real component; other CMPLX pairs clean
both components. A nonzero native leaf status bypasses all cleanup. This keeps
compact cancellation and display markers available to the result formatter.

`test_complex_dispatch_c.py` tests these prepared native admission, leaf and
cleanup stages independently, including all sixteen error headers, aliases,
large/tiny decimal components and display contexts. It uses no parser or ROM
interpreter in the production implementation. The canonical report records 53,908 passing comparisons and pins the current
implementation, headers, test and oracle inputs. Original evaluator regressions
verify raw-token normalization and real-only rejection status/cursor positions.
