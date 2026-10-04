# Real differentiation

The readable standalone API `fx_number_derivative` corresponds to native
entry0x04AEE, reached by raw token0x6B through evaluator dispatcher0x16BB0.
All calculations use the original fifteen-digit integer-decimal records.
The independent native oracle executes every original instruction; the
production C neither executes the ROM nor substitutes host floating math.

## Point, precision and local X

The native entry requires R6=0, scans the body with R6=255, evaluates the
point and optional tolerance with R6=2, then repeats body callbacks with
R6=1. The point and tolerance pass through0x15C82 to decimalize exact
records and clear decimal metadata. An explicit tolerance must be strictly
positive; zero or negative producesF8. Omitted tolerance is1e-10, and this
also enables a different refinement limit and the saved-best-estimate path.

The standalone callback receives the localX record. Native full-expression
evaluation saves and restores globalX through its outer dispatcher. Native
sampling/arithmetic errors produceF3; cancellation producesF1. Negative
host callback statuses form a separate API failure channel and preserve
out. Output may alias the point or tolerance record.

## Initial step (`0x04DCC`)

Validate f(point) once before choosing a step. For point0, use0.01. Other
points are multiplied by1e-3, then0x1CC80 with R2=1 chooses the next signed
decimal power. This routine includes a workspace guard in its precision
argument: it retains zero significant digits and ceilings magnitude away
from zero. The smallest starting magnitude is1e-93.

Evaluate f(point) again, then probe f(point+step) up to seven times. A zero
base or probe value accepts the step. Otherwise require a nonnegative ratio
f(point+step)/f(point) and test abs(ratio)-0.9 between0 and0.2, preserving
ordinary subtraction and0x1CD60 comparison. Failed ratios and ratio overflow
reduce step/10. A probe-domain F3 is also retried while the changed point
remains distinct under0x1CD94; other native error codes fail. After seven
failures the reduced step is still used for central sampling. There are no
cancellation polls during validation or these initial probes.

## Central differences (`0x04A62`)

Make step positive, compute2*step, evaluate point+step first and point-step
second, then divide their cancellation-suppressed difference by2*step.
Normalize and apply native integer cleanup. A callback error or failed
central difference returnsF3.

The driver evaluates the first central pair before polling cancellation.
Every subsequent pair has one poll immediately before halving the step and
sampling. For example, d/dx(X) atX=1 normally uses seven callbacks:
validation at1, initial selection at1 and1.01, the first pair at1.01 and0.99,
and the next pair at1.005 and0.995. There is one cancellation poll.

## Richardson triangle and exhaustion (`0x04AEE`)

Store successively finer central differences in a triangle. With each halved
step, update from the newest row towards the leading estimate, using
new+(new-old)/(4^order-1). The C deliberately preserves the native operation
order: (old-new)/negativeFactor, then addition of new. The factors are-3,
-15,-63,..., formed by multiplication by4 followed by subtraction of3.

Compare abs((previous-leading)/leading) against tolerance using0x1CD94's
thirteen-digit cancellation gate. A zero leading estimate returns zero.
Relative-error overflow asks for another row. When a nonconverged estimate
has magnitude below1e-10, native returns zero; already converged small
estimates are preserved.

Default precision initializes a best-error threshold1e-7. Only when current
relative error is no larger than this threshold does native save the leading
estimate. It then lowers the threshold by decimal decades through1e-8 and
1e-9, clearing the threshold after the last accepted decade. This records
best estimates at decade gates, not at every numerical improvement.

An explicit tolerance uses sixteen central-difference levels and never
records a default best estimate. Default precision uses eleven levels.
At exhaustion, return the saved default best estimate when one exists;
otherwise returnFB. Original seven-bit signed immediates in this routine
are sign-extended by the CPU (for example76E6 is-10), although the static
listing prints the immediate's unsigned seven-bit value.

## Verification boundary

The shared callback header offers positive native evaluator success/error
statuses for integral/derivative adapters. A successful evaluation can carry
an F-valued variable; legacy zero plus an F record still indicates callback
failure. Negative returns are host failures and preserve the caller's output.
The initial derivative probes deliberately ignore the evaluator condition
where native does, inspect the actual record, and retry F3 at most seven
times. A successful F3-valued constant therefore reaches central sampling and
fails after eleven callbacks and no polls. A zero-dimension rich reference
is F9 after the evaluator's cleanup and fails on the first changed-point
probe, after three callbacks.

`0x15C82` leaves unmasked headers above `0x4F` unchanged when its condition is
ignored. The later ordinary arithmetic path `0x1BFxx` calls `0x1AB64`, which
clears bit40 on non-F headers before dispatch. A backed `0x61` reference can
therefore be treated as the rational payload in its raw ten-byte record.
It is not a matrix-cell projection: a reference containing the bytes for
one-third has ratio one against itself and a zero central difference,
independent of the stored cell's value. The differential fixtures exercise
this distinction and the rejected `0x91` vector class with actual bank data.

The differential suite compares complete ten-byte scalar results and native
twenty-byte real/imaginary records, every callbackX record in order, every
cancel poll, nativeX restoration, output aliases and negative host callback
failure preservation. Inputs include rational, surd and marked records,
scaled points, explicit and default tolerances, initial-domain retries,
absolute values, reciprocal poles and native error/exhaustion outcomes.

The oracle adapter supplies timer no-cancel or selected-cancel events at
0x5564, preserving every original instruction. Prepared real COMP functions
are the verified scope. Token grammar/cursor integration, complex callbacks,
malformed BCD, reset and physical keyscan remain outside this module.
