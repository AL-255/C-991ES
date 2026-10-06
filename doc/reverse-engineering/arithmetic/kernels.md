# Major numerical kernels

The implementation links below identify readable C counterparts. Their public
API and source-pinned verification reports define the supported boundaries;
an entry address alone is not a claim of full machine-state equivalence.

| Native boundary | Algorithm / C counterpart |
| --- | --- |
| `1BFxx`, `1C6xx` | Finite decimal and exact arithmetic: [numeric](../../../csrc/numeric/fx_numeric.c), [raw decimal](../../../csrc/numeric/fx_raw_decimal_multiply_add.c), [raw rational](../../../csrc/numeric/fx_raw_rational.c) |
| `18F56`, `19006`; wrappers `1C430`, `1C48C` | Finite decimal exponential/log factorization: [transcendentals](../../../csrc/numeric/fx_transcend.c), [raw exponential](../../../csrc/numeric/fx_raw_decimal_exp.c) |
| `190CE`, public `1C082` | Arbitrary-base logarithm: [fx_logbase.c](../../../csrc/numeric/fx_logbase.c) evaluates log(base) first, then log(argument), then divides after the guard-word boundary |
| `1C1A2`, `1C0AA`, `1C096`, `16182` | Factorial, permutation, combination and percent: [combinatorics](../../../csrc/numeric/fx_combinatorics.c), with descending finite products and original division order |
| `042AE`, `043A2` | Inclusive ascending product/sum: [finite calculus](../../../csrc/numeric/fx_calculus.c), integral bounds of magnitude below 10^10, per-step cleanup and cancellation before each callback |
| `04544`, `046EE` | Embedded Gauss/Kronrod 7/15 rule and adaptive integration: [integral](../../../csrc/numeric/fx_integral.c) |
| `04A62`, `04AEE`, `04DCC` | Central difference, Richardson driver and initial step selection: [derivative](../../../csrc/numeric/fx_derivative.c) |
| `15658`, failure classifier `112F6` | Prepared linear/quadratic/cubic EQN: [solver](../../../csrc/numeric/fx_solver.c), [degeneracy classifier](../../../csrc/numeric/fx_solver_classifier.c) |
| `16A7E`, `161A6`, `17034` | DMS composition, decoded unit conversion and scientific-constant insertion: [sexagesimal](../../../csrc/numeric/fx_sexagesimal.c) |

## Transcendentals and trigonometry

The prepared small kernel `18F56` returns a fractional exponential factor and
separate stripped whole/sign metadata; it is not the complete public exp
wrapper. `19006` preserves cancellation in log10(1+x), with separate positive,
negative and below−0.9 paths. Its finite extreme-small negative behavior must
not be silently replaced by a mathematically improved log1p implementation.

[Trigonometry](../../../csrc/trig/README.md) reduces angles in the resolved
unit, rotates bounded decimal integer coordinates using stored coefficients,
and reconstructs the result in native operation order. A separate special-result
stage compares an already computed value against small fraction/surd tables.
Sine/cosine have five positive magnitudes and tangent four; thresholds are
5e−13, or 5e−12 for tangent's two larger magnitudes. Exact-output permission
selects the stored exact record rather than its stored decimal. Thus familiar
special-angle results have an explicit table-recognition stage, not a general
symbolic trigonometric engine. See [forward core](../../../csrc/trig/fx_trig_math.c)
and [replacement stage](../../../csrc/trig/fx_trig.c).

## Continuous callbacks and refinement

Integral and derivative scan the body with R6=255, evaluate arguments with
R6=2 and invoke body callbacks with R6=1. The outer parser saves/restores X;
standalone APIs pass a local X. The [callback contract](../../../csrc/numeric/fx_calculus.h)
separates host failure, evaluator condition and returned value. A successful
F-valued variable can reach arithmetic before failing; legacy zero plus an F
record retains callback-error semantics. Polls observe the last actual sample
X. Continuous drivers differ from sum/product, which publish the next integer
X before their cancellation poll.

Integration evaluates endpoints before polling, then midpoint and seven
symmetric pairs. A rule has fifteen callbacks and seven polls; the initial
rule additionally has two endpoint callbacks. It uses stored nodes/weights
`2B08..2BC6`, default tolerance 1e−5, a minimum error scale 1e−10, dyadic
left-to-right depth-first refinement, depth limit 47 and rule budget 324.
Equal bounds still evaluate upper then lower before returning zero.

Differentiation validates/probes the starting step before cancellation polls,
samples point+step before point−step and preserves every Richardson storage
boundary. Default tolerance 1e−10 allows eleven levels and saves estimates
only at error-decade gates starting at 1e−7. Explicit tolerance allows sixteen
levels and no default saved-best fallback. Exhaustion returns a saved default
estimate when available, otherwise FB; cancellation returns F1.

## Other order-sensitive kernels

EQN linear solving uses matrix inversion and multiplication in native order,
not replacement Gaussian elimination. Quadratic reconstruction avoids the
small-root cancellation path; cubic branches preserve finite discriminant and
Cardano/trigonometric storage boundaries. A zero polynomial leading coefficient is an
error rather than an automatic degree downgrade.

DMS computes seconds/3600, then adds minutes/60, then degrees, applying cleanup
and marker 40 only below magnitude 10^7. Unit selectors 0..39 use twenty stored
forward/reverse factors at `2814`; temperature selectors 36/37 apply offset 32
in different multiply/divide orders. Constants are copied from forty original
ten-byte records at `264A..27DA`, without updated reference values.

Evidence: `analysis/understanding/numeric-high/scaled-kernels.md`,
`csrc/numeric/integral/EXECUTION.md`, `csrc/numeric/derivative/EXECUTION.md`,
`csrc/numeric/solver/EXECUTION.md`, `csrc/numeric/sexagesimal/EXECUTION.md`.
