# Browser calculator simulator

Use the [hosted calculator](https://al-255.github.io/casio-explore/). Its arithmetic, exact-result formatting and LCD rendering run in the high-level C engine compiled to WebAssembly. No local server is required. Calculator memory lasts for the open page; reloading creates a fresh session.

The [device preview](https://al-255.github.io/casio-explore/device/) retains the full C device state and displays its actual LCD through boot and raw-key steps. Press a key, advance one step, then release it. Acknowledge a requested timer explicitly. The preview exposes pending controllers so that unfinished screens remain visible. Its controls are intended for inspecting device execution; the expression calculator above provides ordinary calculations.

Run from the repository root:

```sh
python3 simulator/serve.py
```

Open [http://127.0.0.1:9910](http://127.0.0.1:9910). The launcher builds the C library and command-line calculator before starting the local server. It requires Python 3, CMake, and GCC or Clang with unsigned 128-bit integer support. No Python packages are needed to run it. Compiler temporary files stay in the build directory.

The browser provides an expression field, scientific keys, a pixel LCD, COMP/CMPLX/BASE-N settings, DEG/RAD/GRAD, natural or linear output, session history, and reset. Each local browser cookie session keeps its own variables, Ans, PreAns, and random seed. Local calculator state expires after one hour of inactivity or when the server stops. The local server holds up to 64 sessions and evicts the oldest when another session is needed. History recall returns the expression and its settings; evaluating it again uses the current calculator memory.

Try these expressions:

| Expression | Setting | Result |
| --- | --- | --- |
| `(sqrt(998)-sqrt(997))/99` | COMP, natural | Exact two-radical fraction |
| `sin(30)` | DEG, natural | `1/2` |
| `sin(45)` | DEG, natural | `sqrt(2)/2` |
| `asin(0.5)` | RAD, natural | `pi/6` |
| `6/2(1+2)` | COMP | `1`, preserving calculator implicit-product precedence |
| `1+2i` | CMPLX | Complex result |
| `10+3` | HEX | `13` |
| `5->A`, then `A+2` | COMP | Store a variable, then obtain `7` |

The ASCII encoder supports named functions, parentheses, implicit products, powers, scientific exponents, factorial, variables and terminal stores. `PreAns` is admitted in COMP; `Ans` is available in the shared grammar. HEX letters A–F are digits in that mode. The interface reports unsupported input explicitly. Invalid ASCII structure is rejected by the encoder; native arithmetic errors use the C evaluator's error status and error screen.

The C engine performs evaluation, numeric record arithmetic, exact-result formatting and LCD rendering. Locally, Python carries HTTP requests to an opaque C session. On GitHub Pages, the same C interface runs through WebAssembly. JavaScript edits text, carries requests and draws the 384 framebuffer bytes returned by C. The simulator links immutable ROM data and handwritten C modules, with original CPU execution confined to differential tests.

This interface uses the prepared expression/result pipeline. Complete physical keyboard timing, boot interaction and advanced EQN/STAT/MATRIX/VECTOR/TABLE/SOLVE screens remain outside the browser interface. The [implementation scope](../csrc/scope.json) remains incomplete. The 100% documented-understanding metric is separate from simulator features and full firmware parity.

For an existing build:

```sh
python3 simulator/serve.py --no-build --port 9910
```

The native command-line interface uses the same C engine:

```sh
analysis/build/simulator/fx991sim '(sqrt(998)-sqrt(997))/99'
analysis/build/simulator/fx991sim --angle rad 'asin(0.5)'
analysis/build/simulator/fx991sim --interactive
```

Interactive mode accepts one expression per line, `:reset`, and `:quit`. Each calculation produces JSON containing the native status, exact real/imaginary records, display tokens, and the row-major 96×32 framebuffer. Native calculation errors are valid protocol replies with `status: "error"`.

The independent tests cover ASCII translation, original-firmware results and pixels, C memory boundaries and session isolation, HTTP/CLI integration, and browser controls. Test scripts are under `tools/test_simulator_*`; their individual reports state the compared behavior and source/artifact fingerprints.

To build the static site, use Python 3.9 or newer. Install the pinned official Emscripten SDK once, then build and preview:

```sh
git clone --branch 6.0.11 --depth 1 https://github.com/emscripten-core/emsdk.git analysis/build/emsdk
analysis/build/emsdk/emsdk install 6.0.11
analysis/build/emsdk/emsdk activate 6.0.11
python3 simulator/build_web.py --sdk analysis/build/emsdk
python3 -m http.server 9911 --directory simulator/dist
```

Open [http://127.0.0.1:9911](http://127.0.0.1:9911). For an SDK installed elsewhere, supply `--sdk /path/to/emsdk`; loading another SDK's environment does not change the builder's default path. It compiles the C firmware library sources and simulator adapter and copies the browser interface into `simulator/dist`. Generated files and the compiler installation stay outside Git. The [Pages workflow](../.github/workflows/pages.yml) pins the SDK and official deployment actions, rebuilds from committed source, and publishes the static artifact after pushes to `main`.
