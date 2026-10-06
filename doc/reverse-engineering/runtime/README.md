# Runtime, input and LCD

These notes preserve the firmware control-flow knowledge needed to maintain the
readable C implementation. They describe named C controllers, their observable
memory effects and original entry boundaries. Production does not execute
firmware instructions or retain an emulated CPU stack.

- [Input and controllers](input-and-controllers.md): boot, MAIN, whole INPUT and subordinate evaluation.
- [Device protocol](device-protocol.md): raw keys, semantic steps, timers and observations.
- [LCD and browser](lcd-and-browser.md): hardware segments, bitmap rows and browser scheduling.
- [Parity and evidence](parity-and-evidence.md): implementation epochs and unresolved RAM behavior.

The browser release verified on 2026-10-05 uses **130 firmware C units**, plus five
application adapters. The local working implementation has **144 firmware units**;
its broader audit is paused and incomplete. A source link identifies a behavior's
owner, not proof that the behavior exists in every historical build. Check the
build's source manifest before applying a receipt to another engine.

A clean clone builds the engine and browser from the retained csrc, firmware and
tools trees. Original differential fixtures, original execution artifacts and
the removed eps-emu host are local-only after cleanup. Plain analysis paths below
identify retained research, not distributed dependencies or new comparisons.

Primary source entry points are [runtime](../../../csrc/platform/fx_runtime.c),
[whole INPUT](../../../csrc/ui/fx_ui_controller.c),
[subordinate INPUT](../../../csrc/ui/fx_input_controller.c) and the
[device session](../../../csrc/app/fx_device_session.c).
