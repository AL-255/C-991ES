# High-level C firmware reimplementation

This is an ongoing reimplementation of the fx-991ES PLUS C Ver.4 firmware.
Every implemented subsystem is handwritten, readable C. The executable does
not run the original firmware or link the CPU emulator. Fonts, spelling tables,
and numeric constants remain immutable data from the extracted image.

The project is **incomplete**. [scope.json](scope.json) tracks the whole requested
firmware scope. Each subsystem's `manifest.json` identifies implemented original
routine addresses, the semantic API being compared, and remaining gaps.

| Subsystem | Current implementation |
| --- | --- |
| Platform | Startup/reset, retained and persistent state, replay history, power/host packets, nonblocking welcome/diagnostic events and contrast UI; handwritten runtime scheduler composes boot, main, whole INPUT and MODE/SETUP with key-wait and explicit pending body requests |
| Keyboard/editor | Matrix scan, bounded debounce/held sampling, key tables, modifier dispatch, nonblocking host key wait/controller, annunciator row, cursor, structured editing and display-to-input conversion, input preparation, error dialogs/key acceptance and cursor recovery and input error/reset recovery; ordinary typing/command and input/evaluate/commit/presentation controllers; generic menu navigation, MODE/SETUP and MATRIX/VECTOR mode menu controllers |
| Parser | Shared COMP/CMPLX literals, e/π, parentheses/signs, arithmetic/fractions, square/cube/nth roots, powers, factorial/percent/nPr/nCr, trig/hyperbolic functions, single/two-argument logarithms and exponentials; complex fractions, restricted powers, conjugation/magnitude/argument, scalar variables/terminal stores/M+/M-, COMP absolute/conjugate/argument, finite sums/products, adaptive integrals and Richardson derivatives; BASE-N radix/prefix literals, logic and native arithmetic policies; scientific constants, DMS and unit-conversion postfixes; Ran#/RanInt with eager shared seed writes and numerical preflight |
| Numeric | Packed records, decimal and finite rational/surd arithmetic, roots/combinatorics and native zero-radicand/reciprocal behavior; finite sum/product, adaptive Gauss–Kronrod integration and Richardson derivative kernels; BASE-N conversions, arithmetic/logic, literals and scalar preparation; DMS composition, unit conversions and stored scientific constants; two/three-equation linear and quadratic/cubic solvers, native failure diagnostics; generic SOLVE callback iteration, finite raw decimal adapters and the distinct prepared quotient/remainder wrapper |
| Complex | Prepared arithmetic, classification, native return statuses, conjugation, magnitude, restricted roots/powers, polar coordinates and rounding |
| Matrix/vector | Prepared arithmetic, transpose, determinant/inverse, dot/cross/magnitude, powers, numeric preparation, REF/RREF, typed slot storage, prepared rich operand dispatch/allocation and grid/caption/cursor display |
| TABLE | Prepared one/two-function generation, dedicated mode88 parser, row limits, live X/Step records, timer/cancellation and callback error policies; prepared expression/UI composition; whole mode and runtime body remain pending |
| Statistics | Prepared moments, seven regression models/predictions, cache semantics, normal P/Q/R and standardization; table editing, cursor and STAT input commits |
| Formatting | Decimal, rational/surd, fraction/π recognition, tagged prime output, width budgets and BASE-N integer output |
| Trigonometry | Decimal rotation kernel, angle reduction, forward/inverse sin/cos/tan and forward special-result tables |
| Rendering | Fonts/pixels, recursive construct layout, viewport/result controllers, equation/inequality captions and special error displays |
| Integration | Expression-token probe and differential expression-to-LCD pipeline for supported grammar |

Complete keyboard/mode controller composition, event scheduling, history and reset-to-key-sequence behavior still require
implementation and verification. Prepared two/three-equation linear coefficient entry, solve, result recall and replay are implemented; uninterrupted solver poll publication, singular/polynomial/error orchestration and complete EQN mode remain pending. Bounded MATRIX/VECTOR bank screens compose whole INPUT and result presentation; complete mode grammar and object editing, whole TABLE runtime composition, SOLVE expression/history/display and other advanced functions remain pending. Passing a subset suite does not complete those requirements.

Build from the repository root with CMake and GCC or Clang. Formatting currently
uses the compiler's unsigned 128-bit integer extension for exact recognition
intervals; arithmetic uses integer and decimal-digit algorithms rather than
host floating point.

```sh
cmake -S csrc -B analysis/build/c-port -DCMAKE_BUILD_TYPE=Release
cmake --build analysis/build/c-port -j4
analysis/build/c-port/fx991c --eval 364f3228312b3229
```

The example evaluates calculator input tokens for `6÷2(1+2)`, which the original
firmware evaluates as `1` because implicit multiplication binds more tightly
than division. Input to `--eval` is hex-encoded calculator input tokens, not
an ASCII expression. The CLI reports numeric records and display tokens; it is
a subsystem probe while the full key UI is being written.

`--display` accepts the natural editor's structured tokens. It checks field
boundaries, converts the expression to evaluator tokens and maps evaluation
errors back to the display cursor. For example, the display-token fraction
`1/2` has numerator and denominator field markers:

```sh
analysis/build/c-port/fx991c --display aebbb831b9b832b9bc
```

Add `--complex` to evaluate in prepared CMPLX mode. The same parser keeps both
numeric records and the result controller composes rectangular output, including
coefficient-one elision. For example, `1+2i` uses raw token `80` for `i`:

```sh
analysis/build/c-port/fx991c --eval 312b3280 --complex --pbm /tmp/complex.pbm
```

Add `--base bin`, `--base oct`, `--base dec` or `--base hex` for prepared
BASE-N evaluation. For example, hexadecimal `10+3` displays `13`:

```sh
analysis/build/c-port/fx991c --eval 31302b33 --base hex --pbm /tmp/base.pbm
```

The parser keeps the original real-function and fraction admissions in BASE-N;
ordinary arithmetic applies the native range/truncation rules. The explicit
`fx_evaluate_base_n` API also retains the caller-supplied second output record.
Scientific constants, direct unit conversions and DMS degree/minute/second
postfixes use the shared parser. DMS components after the first operand are
literal fields. Unit conversions bind below unary negation; DMS binds above
fractions, whose constructor clears the sexagesimal marker from its operands.

For CMPLX, the JSON `tokens` field contains the composed natural result, as
produced by the display controller. The ordinary COMP probe reports standalone
scalar formatter tokens. Both pipelines compare their resulting PBM pixels
with the original firmware.

Scalar variable APIs use a separate typed bank for M, Ans, A–F, X and Y.
Terminal stores commit after syntax and admission succeed; M+/M− preserve the
expression result while updating M. Finite sum/product, integral and derivative
bodies use the same grammar with a local X, native bound/tolerance checks,
cancellation polls and X restoration. Integral and derivative tests compare every
sampled X and every cancellation-poll X against the original evaluator.
`fx_evaluate_with_state` adds a separate optional matrix/vector bank for native
callback reference cleanup while preserving the ordinary variable-bank ABI.
Pol/Rec, polar expressions and quotient/remainder now share the parser and
paired result renderer. Prepared evaluator globals control exact-result
permission separately from the Math setting. Equation screens export the
admitted left and right records for the SOLVE callback bridge.
`fx_evaluate_prepared_with_storage` adds physical temporary-bank copies and
the shared allocation/equation mask; the ordinary typed APIs retain their
separate-bank contract. Physical terminal cleanup commits cells in native
order and preserves partial changes on errors. The physical parser dispatches supported matrix/vector arithmetic, unary operations and REF/RREF after storage allocation, retaining partial writes, native admission masks and error cursors. A whole-parser corpus compares status, both result records and observable RAM against the original. Complete matrix/vector mode grammar and UI remain pending. Raw8A loads the stored Y mean through the physical statistics table; its dynamic-constant errors retain the native preflight policy.

The random frontend shares one packed seed across Ran#, RanInt and calculus
callbacks. Physical evaluation publishes each draw at 821C..8225 immediately,
including draws made before a later error. The additive random API accepts an
explicit seed; legacy value APIs begin with a local zero seed for each call.
Prepared BASE word APIs keep selected-byte, global-mode and operation-mode
policies separate from the typed BASE-N UI APIs.

Physical real differentiation stages the point before explicit tolerance parsing, then reads and writes its Richardson workspace in RAM. Callback and cancellation changes to that workspace remain visible. Stored surds converted to decimal publish the six components in native order. `fx_evaluate_prepared_physical` accepts explicit input, cursor-word and output addresses for live RAM evaluation. Its real integral path stages bounds and tolerance in native order, preserves delimiter decisions across input/workspace aliases, and publishes sampled X before callback evaluation. The addressed C4 integral now preserves native ordered twenty-byte transfers, paired sample/X publication, cancellation, equal-bound results and returned errors. Native04696 copies twenty bytes into a ten-byte CPU local; the C implementation preserves the preceding effects and leaves that corrupted-frame continuation unsupported. C4 derivative and series remain separate pending domains.
The physical Pol/Rec path now composes ordered root/product workspace writes. Stored SURD coordinate argument conversion and live source aliases require further verification. Ordinary INPUT uses `fx_evaluate_prepared_source`, with explicit physical input/output addresses and a separate host-owned returned source; it does not invent a RAM cursor word. Matrix/vector reference results and coefficient editing have distinct bank commit paths, while prepared linear EQN workflows retain coefficient, root replay and display state. Full mode and main-loop composition remains incomplete.

The raw rational value API preserves unchecked packed fraction fields through admission, ordered component products, Euclidean reduction, quotient/remainder packing and marker restoration. Its result and native error status are separate from host unsupported status. REF/RREF reuses this API for scalar fraction arithmetic and fraction-preferred division; copied malformed pivot operands retain ordered conversion. Numerical scratch/MMIO and original odd-pointer marshaling remain outside this value API.

CALC dependency scanning and the prepared CALC/SOLVE outer controller now
compose coefficient prompts, guess input, result commits, replay and error
continuations. Their tested scalar workflow retains the separate owner of each
wait and cancellation boundary. Physical key acquisition and arbitrary rich
outer workflows still require integration.

Raw powers include an implicit opening parenthesis after the caret. Thus
`2^3+1)` means `2^(3+1)` and `2^3)+1` means `(2^3)+1`. The natural editor
conversion emits the closing marker for the exponent field.

The original two-root example can also be rendered to a standalone 96×32 PBM
image by the C result controller:

```sh
analysis/build/c-port/fx991c --eval 2898393938292d9839393729294f3939 --pbm /tmp/two-roots.pbm
```

This uses a prepared ordinary Math-result context. Reset/keyboard event handling
and other result-controller modes remain outside this CLI's current scope.

Run the implemented differential suites, sanitizer checks, and provenance audit:

```sh
python3 tools/test_c_reimplementation.py
python3 tools/test_c_reimplementation.py --audit-only
```

The oracle is the original extracted ROM executed by the independently supplied
SimU8 CPU under `tools/nxu8`. Reports in `analysis/c-verification/` pin hashes of
the tested implementation, fixtures, and oracle. The aggregate audit rejects
stale or missing reports. CPU scratch registers and call-stack bytes are outside
the C semantic APIs; individual reports disclose compared memory and returns.
Peripherals are passive in native routine tests. Callback row sampling checks
exercise the C host interface separately from original hardware timing.

`tools/test_safety_c.py` builds with AddressSanitizer and UndefinedBehaviorSanitizer
and checks fixed-buffer API boundaries. LeakSanitizer is disabled because the
execution host uses ptrace; tested APIs allocate no heap memory.
