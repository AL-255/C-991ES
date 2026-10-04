The platform main scheduler follows the original D7AE..D9EA caller. Its host
state retains the remembered menu result, whether the next cycle waits for a
key, the real outer key-controller state, and a typed pending handler request.
It does not retain a native program counter or allocate CPU-frame bytes in
calculator RAM.

Call `fx_main_loop_begin` after an actual `fx_boot_reset` or boot resume reports
`FX_BOOT_READY`. The first tick processes the existing boot token through the
UI handler. It does not start the first key wait until that handler actually
returns the native context byte. For ordinary input, complete the real D9EE
controller and pass its context-return byte to `fx_main_loop_accept_handler`.
The input controller's subordinate action byte is a different value.

When a cycle requires a key, tick begins or resumes `fx_key_controller` with
ordinary annunciator classification enabled. Idle ticks, modifiers, numeric,
framebuffer and status exports, and reset requests retain the original host
pair and callback contract. The host supplies logical tick timing. This API
does not invent a physical CPU interrupt schedule.

Mode, setup, parameter and specialized-screen calls remain typed requests
until their actual controllers finish. Repeated ticks retain the request
without persistent writes. Prepared return checkpoints verify only the main
caller's policy: wait selection, menu memory, formatting/reset exceptions,
command flags and display flush. They do not implement the requested body.
The screen18 admission request has a separate subsequent screen18 request
when admission returns zero.

FC/FD selection follows the native mode and result-state gates. When exiting
a high-bit screen, the prepared API admits a terminated exported expression
shorter than100 bytes. An unterminated expression returns explicit unsupported
status after the native token-admission prefix; no overflow behavior is claimed.

`tools/test_main_loop_c.py` executes only original instructions in its oracle.
The canonical report has14,521 native cases and3,812 independent C bounds and
request-retention checks. It compares complete RAM/MMIO and callbacks, excluding
only CPU stack8D00..8DED, plus the two named native caller fields at appropriate
main boundaries. Tests include every token, screen, menu byte and handler
return byte; FC/FD mode gates; bounded transfer lengths; setup exceptions;
ordinary keys and SHIFT→SETUP;64 consecutive native idle loops; all original
export/reset pairs; and genuine reset6F82 through initial D9EE entry for cold
and retained COMP/CMPLX modes.

`tools/test_boot_main_ui_c.py` additionally keeps the native continuation live
from reset6F82 through the actual initial D9EE boot handler, first key wait,
and physical matrix packets for1,+,2,EXE. Its234 checks include198 complete
observable-RAM/MMIO/F000-observer checkpoints and9 literal result-record checks.
The27 evaluation checkpoints compare every other observable while recording
all numeric workspace8000..80DB residuals:14 bytes differ at UI return and10
after the next header/key wait. This integration evidence does not claim full
numeric scratch serialization. The entire ordinary flow uses real linked
controllers and never replaces boot completion with a ready flag.

The F000-write observer shared by the C platform and independent test harness
is distinct from the original Windows SimU8 host callback. That callback is
synchronously invoked when the emulated core stops after the F008 unlock and
F009 request; it services8E00 and injects F014 interrupt bits. The passive
firmware oracle used here does not emulate that CPU interrupt schedule.
