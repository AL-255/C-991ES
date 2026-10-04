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
| Platform | Startup/reset, prepared retained-state initialization, power-off and emulator host packets; peripheral registers and key drive |
| Keyboard/editor | Matrix scan, bounded debounce/held sampling, key tables, modifier dispatch, nonblocking host key wait/controller, annunciator row, cursor, structured editing and display-to-input conversion |
| Parser | Shared COMP/CMPLX literals, e/π, parentheses/signs, arithmetic/fractions, square/cube/nth roots, powers, factorial/percent/nPr/nCr, trig/hyperbolic functions, single/two-argument logarithms and exponentials; complex fractions, restricted powers, conjugation/magnitude/argument |
| Numeric | Packed records, decimal and finite rational/surd arithmetic, roots and combinatorics; malformed zero-radicand records remain documented |
| Complex | Prepared arithmetic, classification, native return statuses, conjugation, magnitude, restricted roots/powers, polar coordinates and rounding |
| Statistics | Prepared moments, seven regression models/predictions, cache semantics, normal P/Q/R and standardization; table editing, cursor and STAT input commits |
| Formatting | Decimal, rational/surd, fraction/π recognition, tagged prime output, width budgets and BASE-N integer output |
| Trigonometry | Decimal rotation kernel, angle reduction, forward/inverse sin/cos/tan and forward special-result tables |
| Rendering | Fonts/pixels, recursive construct layout, viewport/result controllers, equation/inequality captions and special error displays |
| Integration | Expression-token probe and differential expression-to-LCD pipeline for supported grammar |

Complete keyboard and mode UIs, event scheduling, menus/history and reset-to-key-sequence behavior still require
implementation and verification. Numerical integration, differentiation, sums,
solving, matrix/vector/table calculations and other advanced functions remain
pending. Passing a subset suite does not complete those requirements.

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

For CMPLX, the JSON `tokens` field contains the composed natural result, as
produced by the display controller. The ordinary COMP probe reports standalone
scalar formatter tokens. Both pipelines compare their resulting PBM pixels
with the original firmware.

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
