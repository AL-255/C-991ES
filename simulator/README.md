# Virtual calculator

The [webpage](https://al-255.github.io/casio-explore/) uses the original fx-991ES PLUS C layout: LCD, Replay pad, scientific keys, SHIFT/ALPHA legends, and numeric keypad. The casing and keycaps use simple flat SVG/HTML/CSS graphics. Original photos and emulator bitmaps are not bundled. The `/device/` route presents the same calculator.

Clicks submit actual original column/row packets to the persistent high-level C runtime. SHIFT, ALPHA, MODE, editing, menus, evaluation and display formatting run in C. The 384-byte C LCD snapshot contains 12 bytes of status-segment controls followed by 31 bitmap rows. JavaScript renders the 18 verified indicators as labels and symbols, and draws rows 1–31 on the canvas. S/A and D/R/G have machine-style boxes; memory, mode, format, Math and history markers occupy their original slots. The C engine decides which segments are active. The raw snapshot and operation trace stay intact. ON invokes the existing virtual-device reset and is outside the 49-key matrix. Rapid taps are queued in order. Engineering controls remain in a closed drawer below the calculator.

| Computer key | Calculator key |
| --- | --- |
| Digits, decimal point, parentheses, `+ - * /` | Corresponding physical key |
| Enter or `=` | `=` |
| Arrows | Replay arrows |
| Backspace or Delete | DEL |
| Escape | AC |
| F1 / F2 / F3 / F4 | SHIFT / ALPHA / MODE / CALC |
| Home | ON / reset |

Shortcuts leave editing controls and Ctrl/Alt/Meta shortcuts alone. The default page uses the calculator keypad and LCD; the previous ASCII expression field is replaced.

## Build and preview

Install and activate the pinned official Emscripten SDK once:

```sh
git clone --branch 6.0.11 --depth 1 https://github.com/emscripten-core/emsdk.git analysis/build/emsdk
analysis/build/emsdk/emsdk install 6.0.11
analysis/build/emsdk/emsdk activate 6.0.11
```

Then build and preview:

```sh
python3 simulator/build_web.py --sdk analysis/build/emsdk
python3 -m http.server 9911 --directory simulator/dist
```

Open `http://127.0.0.1:9911/`. Build outputs and the compiler remain outside Git. The builder checks source and selected asset hashes before and after compilation. The [Pages workflow](../.github/workflows/pages.yml) rebuilds committed source with the pinned SDK and official deployment actions.

For the native expression API and CLI, `python3 simulator/serve.py` builds the native library and serves the already-built static virtual calculator at `http://127.0.0.1:9910/`. Build `simulator/dist` first. `/api/evaluate` and `/api/reset` retain the opaque native expression service separately from the raw-key UI.

```sh
analysis/build/simulator/fx991sim '(sqrt(998)-sqrt(997))/99'
analysis/build/simulator/fx991sim --angle rad 'asin(0.5)'
analysis/build/simulator/fx991sim --interactive
```

## Verification and limits

The [indicator UI record](../analysis/verification/lcd-indicators.json) binds actual browser events, indicator masks, hit testing, matrix pixels, source hashes and screenshots. Its fresh 17-recipe corpus activates 14 of the 18 indicators on the committed engine. All 18 masks and original display slots also have separate renderer-unit coverage; STAT, MAT, VCT and Disp activation was not reached in the real-key corpus. Two unassigned status bits remain in the raw snapshot without invented labels. These tests compare full C-operation traces and every matrix pixel against independently collected matching host-C transcripts.

The [previous redraw record](../analysis/verification/original-ui-redraw.json) retains its earlier scientific, advanced-mode and menu proofs, including `(sqrt(998)-sqrt(997))/99`, sin(30), cos(45), and S⇔D. Original CPU execution remains in separate test oracles and does not run inside the webpage.

The UI release uses the previously committed 130-module C engine. The pending 144-module working-tree engine and its broader local tests remain part of the paused firmware audit. Deployment checks use fresh references collected from the matching committed engine; those scopes are recorded separately.

The [firmware scope](../csrc/scope.json) remains incomplete. Timers are accelerated through bounded controller phases; physical hardware timing is not reproduced. The retained working-engine warm STAT cache discrepancy at 829E..82BB remains unresolved despite matching values and LCD, and some original-observer harnesses need adaptation to owned C bodies. The [session handoff](../agents.md) records its current-source reproduction and remaining work. An uncovered branch remains a typed pending request. The 100% documented instruction-understanding metric is separate from full implementation and behavioral parity.
