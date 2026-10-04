The platform modules implement the calculator data bus, passive peripheral
register operations, boot/editor initialization and the emulator host packets
in readable C. ROM bytes are read only as constants, fonts and startup data.
These modules do not fetch or execute firmware instructions.

Call `fx_boot_reset()` to copy the startup records and initialize the ordinary
calculator screen. Retained state is accepted only after the original signature,
contrast, ten numeric record tags and port-snapshot checks pass; otherwise the
native cold-reset settings are applied. `fx_boot_initialize()` and
`fx_boot_resume()` expose the two prepared native checkpoints separately.

The returned boot status identifies a completed ordinary initialization or a
transfer to the welcome/diagnostic host controller. `fx_boot_prepare_power_off()`
paints the original bitmap and configures the sleep/restart ports, returning
`FX_BOOT_RESTART` at the reset-entry boundary. Physical time, interrupts and the
complete calculator event loop are still being implemented. Mode12's boot
controller is explicitly unsupported.

`fx_host_write_descriptor()` exposes the native ten-buffer descriptor;
`fx_host_write_status()`, `fx_host_write_framebuffer()` and
`fx_host_write_text_packet()` produce the original host packets. The framebuffer
packet includes the 384 visible bytes and excludes LCD row padding. The text
packet includes the status block, optional string header and four hexadecimal
length digits. This verifies the firmware's host protocol without executing
the Windows emulator process.

`tools/test_boot_c.py` compares the original ROM with the public C APIs. It
checks complete host packets, query results, RAM, LCD and MMIO effects across
retained-state invalid bytes, editor actions, reset/workspace contexts and boot
key gates. Native CPU stack bytes are excluded. Editor action2 branches that
format zero additionally exclude native arithmetic workspace8000..80DB; natural
initialization and reset checkpoints retain the stronger whole-RAM comparison.
The C code bounds unterminated strings and oversized BASE-N label locals whose
native behavior would hang or corrupt the CPU stack.
