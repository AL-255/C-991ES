`fx_error_event_begin` publishes the emulator error text, paints the native
four-line LCD dialog, then starts the existing outer key controller. A tick
performs one wait iteration. AC is accepted directly; left/right are accepted
when the command-input flag is set. Other keys repeat the header/wait boundary.
Host export commands remain nonterminal events; reset is returned to the boot
lifecycle. Accepted tokens and reset requests remain in C state until finish.
The raw `8E01/8E02` key pair is never cleared by this controller.

The native descriptor and error-message table were CPU locals. Their C
counterpart uses a typed host descriptor and immutable data. Error1..12 select
the original host messages, including error5's table ID48; other values use
the unknown-error message. Host formatting is distinct from the LCD table:
the latter defines13 errors and retains byte-wrapped indexing for other bytes.

`fx_error_cursor_restore` takes a host context containing the display address
and calculation mode. It reproduces the error-screen reset, mode exclusions,
backup restoration, cursor positioning and busy-flag policy of `EC72`.
`fx_error_result_cursor` handles the separate cached-natural-result cursor
policy at `ED16`. The shared boot initializer owns the editor reset; the
outer evaluation handler owns result clearing, saved result restoration and
subsequent expression/result painting.

The differential suite checks original host strings, all token admission,
all display-state bytes, mode/screen branches and explicit key events. RAM,
LCD, MMIO and callbacks are compared outside the original CPU frame and
called numeric scratch. Production C has no firmware execution interface.
