# Prepared DMS and conversion kernels

`fx_number_sexagesimal` corresponds to native `0x16A7E`. The prepared contract
has one to three components in degree/minute/second order. Earlier components
occupy `0x8078+10*i`, pending transformed DMS operators73 occupy `0x8060+i`,
and `R10=R11=count-1`. `ER12` points at the latest component. The verified
prepared COMP caller uses `R6=0`, with ordinary evaluation mode80FC1.

The reducer initializes an accumulator to zero. With three components it
divides seconds by3600 and copies that result into the accumulator, then pops
the minutes. With at least two components it divides minutes by60, adds that
result to the accumulator, copies the result and pops the degrees. It finally
adds degrees to the accumulator and performs native integer cleanup. The
implementation preserves every record boundary and the original order.
It does not replace the sequence with an exact weighted sum.

Each component passes through the ignored-condition `0x15C82` preparation:
plain radical headers80 are made decimal; eligible headers at most4F have
marker40 cleared and rational values converted to decimal. Unmasked larger
headers remain unchanged. The exact arithmetic wrappers subsequently collect
marker40 and operate on their scalar payloads. An F operand fails admission
as native F3, independently of the original F code. These prepared entry
behaviors are distinct from the outer parser's earlier operand admission.

Successful results receive marker40 if their magnitude is below10^7. Native
uses raw exponent/sign bytes: byte9 equal0/5 admits negative exponents, and
otherwise byte8 below7 admits the result. A carry to10^7 prevents the marker.
The marker selects DMS formatting through the existing formatter; this module
does not produce display tokens. Components are independently signed. An
outer expression's unary minus is applied by its parser, after composition.

`fx_number_unit_convert` corresponds to the decoded branch of `0x161A6`.
Selectors0..39 form20 forward/reverse pairs. Even selectors multiply by the
original factor at2814+(selector/2)*10; odd selectors divide by it. Celsius to
Fahrenheit selector36 multiplies by1.8 and then adds32. Fahrenheit to Celsius
selector37 subtracts32 and then divides by1.8. Final integer cleanup runs in
all cases. Ordinary `0x1BFxx` arithmetic, rather than exact rational arithmetic,
is used here. Its loader clears bit40 for non-F headers before operating.

The factors retain the firmware's finite stored values. For example the last
pair38/39 uses4.1858. They are not updated to present-day reference values.
`0x161F2` is a separate three-digit selector grammar with capability checking
and pair remapping; it remains parser work rather than a numeric API.

`fx_number_scientific_constant` copies one original ten-byte record from the
40-entry table264A..27DA. Native `0x17034` calculates index*10+264A and performs
the same record insertion. It adds no numeric cleanup or output formatting.
The native test calls its surrounding prepared entry `0x16FF6` with `R7=0`.

The source-pinned differential suite checks every selector and constant,
decimal exponent/sign boundaries, rational/surd/marked records, every F tag,
random scaled components, exact aliases, input immutability, native error
statuses and consumed pending DMS stacks. Original ROM and CPU execute only
inside the independent oracle. The production C reads immutable constant
data and never executes firmware instructions. Prepared scalar equality does
not establish parser, complex-mode, backing-bank or physical I/O equivalence.
