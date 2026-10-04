# Prepared generic SOLVE

The generic numerical solver is **010000 through10960**, called at1F2D0
with80FC=C0 and80FD=4. It differs from the prepared EQN polynomial routines.
004F26 scans TABLE start/end/step samples; C674 only tests TABLE mode88/FC1.
Neither is a numerical root solver.

The handwritten API accepts an initial selected-variable record and a callback
that returns both equation sides plus a separate evaluator status. It returns
the root, L−R residual, final selected-variable record, native status, callback
count, cancellation count and alternate-start count. It uses the verified
finite-decimal foundation and no firmware interpreter or host floating point.

## Native state and callback boundary

83FC selects the variable at8226+10*id. Native51CA reads it;522A writes it.
SOLVE disables natural surd readout: the saved restoration record for a stored
surd is its decimal conversion. Ordinary rational, marked decimal and F input
records retain their saved bytes. CEC0 clears a4x decimal marker, then C902
converts an unmarked rational or rejects other initial formats to F3.

1074C publishes an integer-cleaned copy of a trial point, retaining the
uncleaned point for subsequent arithmetic. It resets the expression cursor to
its saved start and calls171F4. A nonzero evaluator code replaces both sides
with CDE4(code); codes outside1..15 create F3. A successful callback may itself
return an F-valued record, so value and evaluator status cannot be conflated.

The callback API replaces the expression frontend only. The native test oracle
has two explicitly separate modes: ordinary cases execute the original
expression parser and arithmetic; contract fixtures supply a pair/status at
the evaluator callback boundary while executing every SOLVE/arithmetic
instruction unchanged. The315-callback fixture proves that a damping count
persists across alternate starts. Another fixture proves that a failed damping
sample shares its retry count with midpoint recovery.

## Finite iteration order

There is no supplied tolerance. The derivative step is1e−7 at zero,1e−93
when0<|x|<1e−93, and|x|*1e−7 otherwise. The minimum comparison precedes
multiplication: at|x|=1e−93, the chosen step underflows to zero and division
returns F3. Successful two-sided probes use
`(Lplus−Rplus−(Lminus−Rminus))/(h+h)`. A failed minus probe uses only
`(Lplus−Rplus)/h`; a failed plus probe uses `−(Lminus−Rminus)/h`. These
asymmetric recoveries deliberately omit the base residual.

Newton's correction divides the saved ordinary residual by that derivative.
The native progress check accepts a relative point change below1e−13, using
1e−15 as the scale at a zero base point. Improving Newton iterations stop at40.
A non-improving step probes another derivative, rejects a sign flip, then damps
toward the preceding point by the exact stored .666666666666666 multiplier.
The damping count stops at50 and persists across alternate starts.

Recovery computes a midpoint through ordered subtract/divide/absolute/add
operations, tries a three-significant-digit midpoint, and retains at most13
successful midpoint recoveries per starting point. Midpoint attempts stop
before attempt15; damping attempts stop before attempt30. The final exhaustion
poll still occurs. A failed damping callback enters midpoint retry with its
existing attempt count instead of passing through midpoint entry/reset.

Alternate starts are0,+1e−5,−1e−5,+1e−50,−1e−50,+1e7,−1e7, after the
initial variable value. Their order comes from the exponent/sign pairs at2AFC.
The eighth exhausted restart returns status10, Can't Solve.

## Acceptance and output

An improving damping branch tests zero below1e−50. Final convergence tests
zero below1e−12, then five and ten significant digits. Native CC90 counts its
leading guard digit: arguments6/11 retain5/10 digits, and argument4 retains3.
Each rounding probe rounds the original point. CD60 comparison rejects either
raw first byte>=0x0A before conversion, so marked/rational/surd callback sides
do not satisfy the rounding equality gate simply because their values agree.
ABS clears bit40 and replaces an invalid classification with F3.

Status0 commits the root and uses cancellation-suppressed final subtraction.
Status36 retains a finite estimate and uses ordinary final subtraction. Both
perform a final evaluation and commit the root to the selected variable.
Numerical failure restores the saved variable, exports an F code and a zero
residual. Native status1/10 decrements the expression cursor's **low byte
only**; the future frontend must preserve that exact behavior. Negative host
failures stop callbacks and leave the complete API output unchanged.

## Verification limits

The source-pinned suite compares all result records, native status, selected
variable, every cleaned callback point and normalized callback side pair,
polls and restart count. It covers canonical decimal/rational/surd/marked/F
initial records, tiny and huge exponents, two-sided equations, both signs,
domain failure, cancellation, aliases and host-failure canaries.

Noncanonical all-zero mantissas carrying a nonzero sign/exponent field are a
tracked gap: four independent fixtures finish with matching records but have
different intermediate callback points because the raw native decimal
subtraction borrows in an unnormalized workspace. Malformed scalar payloads,
rich references and unused native register/scratch state are outside this
normalized prepared API. The expression/controller/display user flow remains
separate from this numerical kernel.
