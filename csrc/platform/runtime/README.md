# Runtime controller composition

`fx_runtime_reset` initializes the available boot controller and retains its cancellation policy. `fx_runtime_step` advances one named semantic phase through main, whole INPUT/UI, MODE/SETUP, parameter menus and nested MATRIX/VECTOR bank menus. The runtime stores C controller objects; it never stores CPU registers, firmware PCs or simulated stack frames.

Supply key packets through `fx_runtime_submit_pair`, then explicitly release them by submitting `{0, 0}`. The scheduler preserves the packet until the host changes it. `physical_input` is used by boot events; the ordinary controllers consume platform packets. `FX_RUNTIME_TIMER` retains the pending controller and leaves RAM unchanged until the host supplies a nonzero `timer_elapsed`. `FX_RUNTIME_EXPORT` exposes `export_mask`; the independent platform callback remains available through `fx_take_callback`.

`FX_RUNTIME_REQUEST` carries a typed body or an explicit dependency gap. A MAIN body retains its operation and argument. An INPUT body retains its request, context return, action, expression/result addresses and prepared/current source addresses. `fx_runtime_accept_body` accepts an actual implemented body's action and context return independently. It rejects gap kinds. INPUT `SPECIAL_CONTEXT` represents the remaining whole INPUT continuation at capture; a rich/TABLE provider must perform its actual token admission before entering F12A.

Run `python3 tools/test_runtime_c.py` for fresh O2 and O3 native differential observations. The oracle enters original startup at 0x6f82 once per sequence and preserves the running native stack/register continuation thereafter. Sixteen input-only RAM/key recipes produce 346 checkpoints and 1,057 checks per optimization. All RAM/MMIO outside individually witnessed original frame writes is compared. The verifier permits numerical arena differences only at 34 specifically witnessed checkpoints, retains every differing byte in the reports and archived RAM, and rejects differences elsewhere. Six body controls are retained: rich back/AC and empty TABLE readiness controls complete their actual delegated bodies and return through the main cycle; four retain pending body requests.

The parameter-menu wrapper now owns the admitted generic, CMPLX, BASE-N and
MATRIX/VECTOR child controllers. Its real child return passes through the
ordinary main-loop completion policy, including signed FF results. STAT,
distribution, recall, store and clear children remain typed
`FX_RUNTIME_PARAMETER_GAP` requests with their actual child kind, argument and
page; `fx_runtime_accept_body` cannot complete those gaps. Owned menu timers and
export/reset requests use the same explicit host stepping as MODE/SETUP.

The opaque [device session](../../app/fx_device_session.h) owns persistent RAM
and this runtime together. Its input-only recipes extend the historical runtime
corpus with cold boot, Ans/PreAns, editing, replay, error recovery, exports and
raw host reset. The older runtime counts above describe their original frozen
source version; subsequent device and parameter-menu reports identify their
own tested source closures. Dedicated screens, missing child bodies and broader
diagnostic behavior remain incomplete. Numerical scratch discrepancies and body
gaps prevent a full firmware parity claim. Adding this composition does not
credit any new assembly instruction ranges.

Custom fixtures and single-optimization runs require `--no-report` or `--private-report`. A private candidate root requires `--private-report`; private reports cannot replace canonical verification reports. Fresh compiled libraries and complete compressed observations have unique artifact directories and are pinned alongside the source/fixture inputs.
