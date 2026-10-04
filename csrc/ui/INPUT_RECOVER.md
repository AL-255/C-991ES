`fx_input_recover_after_error` composes the existing editor, result-state and
rendering APIs at the `E67C` error-recovery boundary. It initializes the editor,
then restores a saved real result or selects the native fresh-input path.
Mode12 resets its own screen; mode88 restores `81B8` when an item is active,
otherwise clears `85AA` or `81B8` according to the solve settings. Ordinary
recovery clears the twenty-byte result and selects input screen1/state1.

`fx_input_reset_context` implements `E71E`: initialize the editor, reset layout
and result flags, choose screen21 or screen24 for mode75, conditionally reset
mode12 and clear the action/history/host-return fields.

The context is a host C object with display/result bus addresses and named
mode, saved-result and return fields. It has no CPU register or frame fields.
The saved result renderer consumes the real ten-byte component, matching the
native `37BC` call. Recovery returns the native0/1 retry decision; negative
status propagates a bounded malformed or unsupported shared API.

The canonical suite passes16,476 comparisons over all mode bytes, prepared
saved records, mode12 flags and solve-buffer policies. It compares native
return values, the host return field and all persistent RAM/LCD/MMIO outside
native numeric and CPU-frame scratch. The host return field is projected into
one test-only oracle context byte for the complete memory comparison.

The saved nonerror mode89 renderer remains an inherited gap:255 original
fixtures return normally while C reports unsupported. Their native RAM, LCD
and framebuffer hashes are stored in the report. These are excluded from the
passing-case count; the module does not claim full handler completion.
