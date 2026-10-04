`fx_diagnostic_contrast` implements the retained semantic state and display
effects of CCF4 in readable C. `begin()` paints the contrast menu and returns
before a key wait. The host passes a completed ordinary key token to `step()`;
WAIT requests another event, DONE lets the parent diagnostic continue.

Normal entry uses limits4..29. Expanded diagnostic entry uses0..31 and paints
the value caption at LCD row8. Initial values are retained without clamping.
Left/E3 and right/E2 update within the limits and preserve native busy-flag
behavior. Every other token except AC/E6 reapplies the retained value to
8112/F032 and repeats the caption when expanded. The retained host value wins
over changes to8112 made while an event is pending. AC completes without
changing calculator RAM.

The menu reads its four strings from ROM11CE, uses font7, clears all512 LCD
bytes and follows the original8121 selection/display-port protocol. The value
caption uses three immutable host characters, without an artificial text
local in calculator RAM. Native conversion quirks outside0..31 are retained:
the high position receives no A..F correction; the low position retains all
original byte bits, ORs30 and uses a signed comparison before adding7.

`tools/test_diagnostic_contrast_c.py` compares the module with the original ROM
at CCF4/CD1E/CD24/739E boundaries. It covers all256 value bytes, all256 semantic
tokens, all256 busy bytes, normal/expanded limits, retained-value event
sequences and40 complete native key-controller events. Whole RAM, MMIO and
callbacks are compared with only the native CPU stack excluded. Complete
controller events provide their nativeCD24 RAM snapshot before the prepared
contrast step; no numeric/annunciator workspace is excluded from that step.

The ordinary key controller and physical scheduling stay with the caller.
Production code has no native registers, instruction addresses, emulator
execution or calculator RAM frame model.
