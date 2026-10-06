# LCD hardware segments and the browser

The observation is **384 raw bytes**: 32 rows of 12 bytes copied from F800 + row*16.
The wire format removes each hardware row's four unused bytes.
[fx_device_session.c](../../../csrc/app/fx_device_session.c) preserves actual RAM,
including row 0.

**Row 0 is hardware segment controls**, not the first line of matrix pixels. The
original host decodes 18 named indicators and draws matrix rows 1–31. Drawing all
rows as pixels produces stray dots instead of status symbols.

[fx_annunciator.c](../../../csrc/ui/fx_annunciator.c) composes 87D0..87DB and
publishes F800..F80B, corresponding to original routine 003D62. The browser's
[lcd-indicators.js](../../../simulator/device/lcd-indicators.js) decodes the
verified masks. Each marker is hidden when its actual C flag is absent; key
presses and arithmetic results do not infer its state.

| Symbol | Byte | Mask | Original strip left / width |
| --- | ---: | ---: | ---: |
| S | 0 | 10 | 0 / 8 |
| A | 0 | 04 | 8 / 11 |
| M | 1 | 10 | 19 / 11 |
| STO | 1 | 02 | 30 / 19 |
| RCL | 2 | 40 | 49 / 18 |
| STAT | 3 | 40 | 67 / 24 |
| CMPLX | 4 | 80 | 91 / 31 |
| MAT | 5 | 40 | 122 / 19 |
| VCT | 5 | 02 | 141 / 18 |
| D | 7 | 20 | 159 / 11 |
| R | 7 | 02 | 170 / 9 |
| G | 8 | 10 | 179 / 10 |
| FIX | 8 | 01 | 189 / 17 |
| SCI | 9 | 20 | 206 / 15 |
| Math | 10 | 40 | 221 / 26 |
| ▼ | 10 | 08 | 247 / 11 |
| ▲ | 11 | 80 | 258 / 9 |
| Disp | 11 | 10 | 267 / 21 |

Masks are hexadecimal; byte indices start at zero. Coordinates use the original
288-pixel status width. Encoded bit positions are **not** text positions. The
original host pin table is at 484C0C and scale-three endpoint table at 484C80.
Status geometry is (58,132,288,12); matrix geometry is (58,144,288,93) on the
405 × 816 face.

Byte 0 mask 40 and byte 11 mask 02 remain raw but have no verified glyph in that
host's 18-entry compositor. They must not be named LEFT/RIGHT or assigned
invented positions. [fx_viewport.c](../../../csrc/render/fx_viewport.c) separately
draws actual horizontal scroll glyphs 159/158/191 in the matrix.

## Browser input and scheduling

The [device app](../../../simulator/device/app.js) uses 49 normal-ROM physical
packets. ON is outside the matrix and calls the existing reset pipeline.
Alternate SHIFT/ALPHA legends still submit physical keys; firmware decoding
selects the alternate operation.

An automatic press submits a pair, advances the held phase, releases in a finally
path, advances the released phase and drains the callback. A phase has a 40-step
bound and at most eight acknowledged timers. Timers are accelerated on animation
frames; this is semantic scheduling, not physical timing.

Distinct taps are serialized without dropping rapid input. Repeated computer
keydown events are ignored. Editable/debug controls retain normal keyboard
behavior. Pointer cancel/leave, keyup, blur and visibility changes clean up
pressed state; losing focus also releases a manually held packet. Every C call
publishes its actual result and complete snapshot in the operation trace.

The canvas clears to RGBA (192,203,179,255) and draws rows 1–31 with foreground
(33,54,44,255), MSB first, at 96 pixels per row. Its raw 96 × 32 observation stays
intact; CSS places the visible matrix below the separate strip. Casing, labels
and keycaps are authored graphics, without bundled original raster assets.

Local evidence:

- analysis/build/ui-indicators-20261005/reference/ANNUNCIATOR-MAP.json
- analysis/build/ui-indicators-20261005/runtime-source-review/REVIEW.json
- analysis/verification/lcd-indicators.json
- analysis/browser-lcd-indicators/public/public-results.json

The latest local and public UI checks each compared 159 DOM states, 1,217 actual
C-operation snapshots, 473,184 matrix pixels and 2,862 marker checks against the
committed 130-unit host-C engine. Real keys activated 14 of 18 markers; STAT, MAT,
VCT and Disp had renderer-unit coverage only in that corpus. Host-C/browser
agreement is separate from original-firmware differential evidence.
