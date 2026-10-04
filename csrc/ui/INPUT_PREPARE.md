The input-preparation APIs reproduce the firmware boundary before evaluation.
`fx_input_needs_export` chooses direct display input or a mode-specific exported
workspace. Direct input uses `8154`; exported input uses `8398`, or `8546` for
mode `88` and the low-bit calculation modes carrying bit6. Disabled modes have
workspace address zero, with the native copy-to-zero behavior retained.

`fx_input_prepare_exported` restores `81B8` in screen6/item4, otherwise adds a
single-variable recall suffix and equation-mode `=0` when needed. It retains
the display backup, then validates natural fields and exports their evaluator
syntax. A continuation uses the native low-byte pointer subtraction when
adjusting `812C`; natural export instead updates the tracked root while walking
display constructs. The historically named `fx_input_prepare_saved_solve`
restores the saved TABLE expression at `85AA` first. The public name is retained
for compatibility; this entry is not the numerical SOLVE kernel.
The variable-suffix predicate also retains the native low-byte length test:
an oversized257/513-character source beginning with a variable is treated like
a one-character source by that predicate.

The source output is a host C local. Production code does not create a CPU
stack frame in calculator RAM. Return1 means ready,0 is a field-boundary error,
and-1 bounds malformed unterminated input. The evaluator, result/Ans commits,
replay and error lifecycle remain separate responsibilities.

`tools/test_input_prepare_c.py` compares28,908 original routine cases: all256
mode policies and input tokens, prepared routing branches, natural constructs,
equation normalization and continuation byte wrap. It compares every RAM,
LCD and MMIO byte except the original CPU call-stack region `8D00..8DED`.
