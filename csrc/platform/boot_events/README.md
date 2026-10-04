# Welcome and diagnostic events

`fx_boot_events` completes the WELCOME and DIAGNOSTIC boundaries returned by
`fx_boot_reset` or `fx_boot_resume`. Call `fx_boot_events_begin`, then schedule
`fx_boot_events_tick` until READY. A standalone full diagnostic starts with
`fx_boot_diagnostic_sequence_begin`. Its local counters, text, raw pairs,
cursor images and contrast value are ordinary host C values.

Welcome uses physical matrix samples, optionally supplied by `fx_key_input`.
Its initial remembered pair is columns 80/row 01. It waits for release, then
polls, scans and debounces. A stable 04/04 requests the full diagnostic; AC
04/10 ends the welcome. Other pairs become the remembered release target.
The initial count 094D is 2381 peripheral iterations, with no assumed time
unit. The release branch checks the old count; the polling branch checks the
decremented count. Both native boundary behaviors are retained.

Diagnostic waits use the emulator's 8E00 handshake. Flag 2 is the distinct
diagnostic control poll; nonzero service returns the raw 04/10 pair at 80F2/3.
Flag 1 requests an ordinary raw host key pair at 8E01/02. The host must clear
a consumed pair after the complete tick, since firmware does not clear it.
The five display patterns accept ALPHA only. The 49-key test compares encoded
physical pairs with ROM 2D5A; wrong keys retain/redraw the current counter.
The final reset prompt accepts any pair, then captures the current contrast
and preserves it across cold reset and default-screen initialization.

The diagnostic displays ROM version metadata and computes the negative
unsigned 16-bit sum over ROM 0..FFFF and 1:0000..FFFB. The original image sums
to E803 while its stored checksum is E407, so its native caption is SUM NG.
Its port caption preserves the native OR 30 byte behavior. Architecture
test 7334 checks the original CPU/PSW implementation; the C program has no
CPU model. The display-only API accepts that result explicitly, with A5
selecting Read OK. The standard lifecycle supplies the native verified A5
success code. The architecture-test instruction span is excluded from the
understanding ledger.

The canonical suite compares every persistent RAM/MMIO byte and callback,
excluding only the native CPU stack 8D00..8DED. It covers host responses,
all port bytes and read-test results, ROM metadata/checksum branches, all
mode-byte boot tails, welcome decision/timeout boundaries and complete 7044
chains. The complete-chain fixture uses ordinary 80FB=0 with the delegated
1DB34 header enabled. All classifier workspaces are included in these complete
RAM comparisons. No scratch bytes are excluded or copied during those chains. CPU register/pointer manipulation exists only in the original-ROM
test oracle.
