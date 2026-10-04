# Complex and polar result display

`fx_display_complex_result` translates the ordinary complex branches of B070
into readable C. It accepts an explicit renderer memory image and the address
of two consecutive ten-byte numbers. The first is real and the second is
imaginary. The implementation copies the records before coordinate conversion
and leaves the caller's twenty bytes unchanged.

The entry checks the native mode/display predicates first. Cached natural
output uses the existing text buffer without reading the numeric address.
Otherwise the scalar classifier determines whether either component is zero,
positive, negative or an error. These classes govern component inclusion even
when formatting produces empty text, as it does for FD.

Mode196 follows the rectangular/polar preference and its explicit override.
Polar output converts the copied record through `fx_complex_to_polar`, except
for the native both-zero and positive-real-axis DMS bypasses. A zero angle
uses the real-only rectangular branch. Other admitted modes remain rectangular.

The real component uses context0, or context6 for a polar radius. Imaginary
coefficients use context1 after a real component, context3 for a negative
imaginary-only result, and context4 otherwise. Polar angles use context2 or5.
Each formatter call updates the current selection/cache state while preserving
the previous-selection nibble until the final result-kind commit.

Rectangular composition replaces a coefficient exactly equal to1 with the
imaginary-unit glyph80. A negative coefficient retains the unary negative
token when it is the only component; after a real component its sign becomes
the binary subtraction glyph. Positive coefficients receive a plus sign.
Polar composition uses angle separator88, or AF in natural output.

The controller then writes persistent tokens, history metadata and text, and
either invokes the natural viewport or paints the two legacy baselines.
Natural history flattening follows AFE2's do-while behavior: even empty output
copies its first NUL before checking the next source byte. The original pointer
and temporary exponent-glyph setting are restored after viewport rendering.

`tools/test_render_complex_c.py` compares28,301 original B070 calls against
this C path: tokens, selection/cache globals, active viewport/cache entries,
all256 history bytes,384 framebuffer bytes,512 LCD bytes before/after flush,
and F031. All pass. The oracle allows20 million instructions per call because
some prime-factor inputs exceed its default one-million-instruction budget.
None of the tested calls is omitted as a fault.

This is a subsystem boundary, not whole-device equivalence. Numeric operand
scratch within8000..80DB, inactive metric slots and CPU scratch/stack state are
outside the API. Status-bit4 labels, equation-specific polar policy, mode137
and native stack-only natural text buffers remain untranslated. Exact scopes
and the source-pinned report are recorded in `complex_manifest.json`.
