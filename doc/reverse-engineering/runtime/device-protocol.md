# Device protocol and observations

[fx_device_session](../../../csrc/app/fx_device_session.h) owns a 64 KiB RAM/MMIO
image, platform and named runtime controllers. Creation does not boot a session.
A caller may supply exactly 65,536 retained bytes; otherwise creation uses a cold
image with passive input F040=FF. The raw variant is stored at F050. Reset then
invokes the retained boot policy.

| Operation | Meaning |
| --- | --- |
| submit_pair(columns, rows) | Publish the raw host pair at 8E01/8E02; no ASCII expression or alternate-token injection. |
| release() | Publish the zero pair; packets otherwise remain held. |
| step(input, timer_elapsed) | Advance one existing semantic controller phase. |
| ack_timer() | Advance only an actually pending timer; otherwise return INVALID without changing state. |
| take_callback() | Consume the existing F000 publication observer. |
| snapshot() / JSON | Copy actual controller state and framebuffer without advancing or draining a callback. |

A callback observation is not a simulated processor interrupt. The session
infers no wall clock, CPU tick count or automatic execution loop.

The snapshot includes phase/event, request kind and operation, context/action,
timer state, key pair, memory status and packed framebuffer bytes.
[JSON serialization](../../../csrc/app/fx_device_protocol.c) is observational.
[Browser exports](../../../csrc/app/fx_device_browser.c) expose actual controls
and allocated observations. The caller frees each exported observation; it is
not a retained pointer into mutable state.

## Typed requests preserve incomplete behavior

[fx_runtime_request](../../../csrc/platform/fx_runtime.h) records kind, operation,
argument, status, prepared/current source and relevant addresses. A gap stays
visible. Public session/browser transport has no body-reply operation that can
manufacture a missing result.

The development-level fx_runtime_accept_body accepts only a genuinely delegated
MAIN_BODY or INPUT_BODY while the runtime is actually in BODY. Gap kinds and
owned START/controller phases reject external completion. Pending 144-unit
STAT/distribution/linalg routing clears its request and advances to its own START
phase before executing the body on a later step. ADVANCED at that prefix does
not establish the body's final numerical result.

Observers stopping at an admission prefix therefore need different expectations
from observers running the complete body. A successor must preserve its original
input corpus, genuine stop boundary and memory checks.

Local evidence:

- analysis/build/distribution-list-admission-owned-prefix-successor-02/PUBLISH.json
- analysis/build/root144-canonical-twelve-suite-runs/actual-01/TERMINAL.json
- analysis/build/root-session-handoff-20261005/INVENTORY.json
