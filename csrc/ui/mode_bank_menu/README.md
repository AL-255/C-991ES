`fx_mode_bank_menu` implements the D0CC controller requested by MODE's MATRIX
and VECTOR branches. Begin with page44/45 and a nonzero transition flag, then
use tick and timer acknowledgement until the actual native result is retained.
Pass that byte to the frozen MODE caller's `fx_mode_setup_accept_handler`.
The ordinary D074/D0A0 wrappers choose their parameter page from mode, screen
and slot, returning0 immediately when the mode does not match.

Host state retains the current page, action, previous/return pages, selected
slot, initial family screen and optional caption. The original caller clears
the caption after every generic-menu return. Back selectionFF/FC restores the
previous page with a matrix/vector caption; FD/FA restores the return page with
no caption. A token result writes80F5 and returns1 without editor cleanup.
Structural results choose an action, named slot or dimensions. Unknown prepared
structural selections follow the native editor fallthrough instead of adding
a new validity rule. Actual ROM menu descriptors constrain reachable choices.

Named-slot selection performs a requested mode transition before testing data
dimensions. Data opens immediately only when both dimension bytes are nonzero;
the native gate admits bytes such as255. A transition from another mode can
clear those dimensions first. The initial family screen remains retained even
for a literal cross-family prepared selection. Editor completion writes the
screen/slot, resets layout/result flags and returnsFF. Cancellation performs
the origin-family mode policy when requested, clears80F5 and returns0.

The dimension adapter calls the frozen `fx_linalg_bank_ensure_dimensions` with
immutable host dimension fields. It serializes only the selected slot back to
persistent RAM. Equal shapes preserve every one of the90 cell bytes; a change
clears all nine cells. Other slots and the evaluator temporary mask are retained.
No CPU local, operand pointer or instruction-execution fallback is created.

The canonical original-ROM suite has20,993 checks:20,990 native observable
checkpoints and3 argument bounds. It covers every menu result byte, every
selection byte for the important result classes, literal unexpected choices,
all ordinary mode gates, every dimension byte and all nine bank slots,
shape retention/clearing, data admission, actual raw-key/back/cancel sequences,
64 idle iterations, host exports and reset. It also keeps a genuine native
continuation from MODE through matrix definition and the final MODE return.
All RAM/MMIO, F000 observer and actual return bytes are exact, excluding only
native CPU stack8B00..8DED. There are no numeric workspace or ready-flag exclusions.
Physical STOP/IRQ scheduling remains external to the host controller.

An independent read-only audit also exercised2,912 original-ROM fixtures and
6,122 caller segments, confirming mode-before-data ordering, caption reset,
family-screen retention and literal editor fallthrough. Its numerical storage
dependency was already owned by the linalg subsystem.
