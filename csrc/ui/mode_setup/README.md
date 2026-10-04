`fx_mode_set` follows C77C's full persistent policy for every mode/submode byte.
It snapshots the four native reference records into host values, clears result
state, applies mode-specific storage resets, and restores saved INEQ records
when the old and new submode agree. MATRIX/VECTOR transitions preserve an
existing bank in the same mode; EQN and INEQ initialize three3x3 slots; TABLE
constructs its1/5/1 parameter records; DIST retains its input/list policy.
The standalone setter and storage helpers compare complete observable RAM.

The nonblocking MODE and SETUP controllers use the generic menu navigator and
real outer keyboard lifecycle. MODE includes STAT, EQN, INEQ and DIST nested
selectors. MATRIX/VECTOR expose typed D0CC requests before that subordinate
body; `fx_mode_setup_accept_handler` takes its actual returned byte after the
callee has performed its own persistent policy. A request remains retained
until the host completes it. The parent MODE result is the selected mode byte.

SETUP implements all28 dispatch entries, including both math-output variants,
angle units, fractional/complex/recurring/decimal/frequency settings, automatic
power-off and TABLE function-count choices. FIX/SCI/NORM keep the native prompt
and accepted-key range, returningFF for an accepted setting or0 for cancellation.
Contrast reuses the independently verified CCF4 painter/value policy and adds
its real keyboard/export/reset lifecycle. Native SETUP's80FE.bit6 blocker is
preserved. Setup completion is the actual signed byte expected by the main
caller; it is not converted to a Boolean.

The canonical suite has16,150 checks, including all mode bytes, all incoming
mode bytes for special destinations, all submode bytes, saved-record restore,
all settings, all precision token bytes, all contrast values, actual key
sequences, timer acknowledgement, exports, reset and all setup blocker bytes.
MATRIX/VECTOR prepared return fixtures verify only the MODE caller, explicitly
leaving D0CC pending. CPU stack8B00..8DED is excluded.

Zero-result display initialization reuses the existing boot supplied-record
formatter. In207 explicitly labelled checkpoints its numeric operand and
saved-argument scratch8000..80DB differs from the native formatter; the report
records every observed residual address/count. All other RAM/MMIO and display
pixels still match, and this module does not write fake CPU-frame pointers into
that workspace. The remaining15,941 native checkpoints are strict observable
RAM comparisons. Physical timer/STOP scheduling remains host-owned.

TABLE expression transfer admits a terminated expression shorter than100
bytes. An unterminated input returns unsupported status before the editor
reset, following any already-applied setting-byte prefix. Invalid formatter
or mode-specific rendering inputs likewise return an explicit unsupported
status. No CPU execution fallback is present.
