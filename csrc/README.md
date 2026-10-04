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
| Platform | Startup data copy and peripheral register controls, including key drive |
| Keyboard/editor | Matrix scan, bounded debounce/held sampling, key tables, modifier dispatch, editor policies, cursor glyph/position, structured insertion, atom wrapping, deletion and field navigation |
| Parser | COMP decimal literals, scientific input, e/π, parentheses, signs, arithmetic precedence, compact fractions, square roots, forward/inverse trigonometry and logarithms |
| Numeric | Packed records, integer decimal arithmetic, rational/surd codecs and developing exact arithmetic |
| Formatting | Decimal, exact rational/surd, approximate fraction/π recognition and developing alternate selections |
| Trigonometry | Decimal rotation kernel, angle reduction, forward/inverse sin/cos/tan and forward special-result tables |
| Rendering | Fonts, pixel operations, recursive construct layout and developing viewport/result controller |
| Integration | Expression-token probe and differential expression-to-LCD pipeline for supported grammar |

Full keyboard integration, event scheduling, all numeric functions and calculation
modes, complex results, error screens, history, and reset-to-key-sequence behavior
still require implementation and verification. Passing a subset suite does not
complete those requirements.

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
