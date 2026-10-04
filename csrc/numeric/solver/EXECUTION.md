# Prepared EQN numerical flow

The API stops at native `15658`, before display and history events. It keeps
the two numerical work banks, root count, and prepared timer-check count.
`fx_solver_cleanup` separately applies the numerical `8724` cleanup used when
the controller exports each result.

For two simultaneous equations, six coefficients occupy two augmented rows
with stride three. Three simultaneous equations use a row-major three-by-three
matrix followed by three RHS values. Polynomial coefficients descend in
power; the native cubic constant comes from `82F8`, whereas a/b/c come from
`829E`/`82A8`/`82B2`. This physical detail belongs to the oracle adapter, not
to the public coefficient array.

Linear solving prepares the RHS, inverts the coefficient matrix using the
original adjugate operation order, then multiplies that inverse by the RHS.
The implementation reuses the independently verified matrix APIs rather than
changing to a Gaussian-elimination algorithm with different rounding.

Polynomial solving first recognizes eligible decimal fractions and divides
every coefficient by the leading coefficient. A nonzero coefficient that
underflows to zero produces native status3. Math-off converts compact surds
but retains existing rational records. A zero leading coefficient is an error;
the firmware does not downgrade the degree automatically.

The quadratic positive-discriminant branch uses `sqrt(D)+abs(b)` and computes
the smaller root with `2ac/(sqrt(D)+abs(b))`. A repeated root is exported once.
A negative discriminant produces positive-imaginary then negative-imaginary
conjugates, or no nonreal roots in the prepared inequality policy.

The cubic stores `P=3ac-b²`, `Q=27a²d-9abc+2b³`, and the negative classical
discriminant `H=27a²d²-18abcd+4b³d+4ac³-b²c²`. Every multiplication and sum is
an independent native-precision storage boundary. Positive H uses Cardano;
zero H produces one triple root or two distinct roots; negative H uses radian
atan and three cosine evaluations stepped by 2pi. The atan error path substitutes
a signed pi/2. Computed cosine results pass through the native special-result
recognizer when Math permits it.

Rational perfect-square roots remain exact with Math off. Nonperfect rational
square roots use separate numerator and denominator decimal roots; converting
a hypothetical exact surd instead changes the final mantissa digit. Cube-root
rational exactness is likewise governed by its native wrapper, independent of
the display setting.

Verification compares complete work banks and active complex results against
the original-ROM oracle, including cancellation and failure partial state.

`fx_solver_classify_degenerate` reproduces the subsequent `112F6` failure
diagnostic. It uses ordinary decimal products, checks nonzero-product
underflow, and suppresses cancellation after thirteen leading digits. Its
fixed determinant/minor order and early zero tests are deliberate: a zero
first pivot in the only nonzero third column can make the native classifier
report dependent even when mathematical rank analysis says inconsistent.
Error-valued coefficients likewise cannot be rejected by a preliminary scan,
because some native zero shortcuts never inspect them.
