# High-level numeric result formatting

`fx_format.c` generates result tokens from numeric records using readable C
algorithms. It contains no ROM execution, instruction decoder, runtime CPU or
host floating point. It shares the independently implemented numeric codecs
and decimal arithmetic from `../numeric`.

The interface accepts a ten-byte `fx_number`, explicit options and an output
buffer. It leaves the input unchanged and reports the native result kind,
required output length and recognition category. Every nonempty output buffer
is NUL-terminated; insufficient capacity returns `FX_FORMAT_BUFFER_TOO_SMALL`.
Known unsupported paths return `FX_FORMAT_UNIMPLEMENTED`.
`options.selection` stores the full firmware8100 byte: current selection in the
low nibble and previous selection in the high nibble. Values0..15 encode a
previous selection of zero and remain valid.

```c
fx_number number;
fx_decimal_parse(&number, "0.523598775598299");
fx_format_options options = fx_format_default_options();
uint8_t tokens[100];
fx_format_result result;
fx_format_status status = fx_format_number(&number, &options,
                                           tokens, sizeof tokens, &result);
/* status=OK; kind13; recognized2; tokens describe a stacked1/6 then pi. */
```

Implemented output algorithms include Norm1/Norm2, Fix and Sci decimal
rounding; Math, mixed and linear fractions; integral-component tagged surds;
bounded ordinary-fraction recognition; the firmware's pi/25200 recognition
test; recurring-decimal long division; degrees/minutes/seconds; engineering
exponent placement for Norm, Fix and Sci; and prime
factorization on canonical ordinary, marked, rational and surd records. The
ordinary decimal marker is ignored locally on the prime path, preserving the
original input. Tagged records follow the original raw packed-decimal trial
division rather than numerical rational/surd conversion. Separator nibbles
and noncanonical quotient digits retain the native decimal byte carry rules.
The normalizer's byte15 lookahead can leave a leading zero on a nonzero
quotient, and the prime loop terminates by checking that stored leading byte.
Prime factorization deliberately
tries only the168 primes through997 and encloses a remaining factor in
parentheses. The extra `format_context` parameter controls compact scientific
precision and surd parentheses; it is not an engineering-mode switch.
Contexts1..3 reduce Sci10 to nine-digit scientific precision outside
exponent-9..9. Sci10 first rounds to ten digits and then rounds that copy to
nine. Norm and large-value Fix delegate to nine-digit Sci only when the tenth
digit of their rounded coefficient is nonzero, restarting from the original
record and retaining all nine digits. Already short coefficients keep their
ordinary trailing-zero trimming.
Contexts4..6 retain grouping
around exact coefficients but restore the ordinary decimal width when exact
output falls back to a numeric result, as the original C060 does atC154.
Its trial division retains the original finite15-digit quotient behavior,
including for magnitudes beyond the display's ten digits.
Forced numeric output of rational and surd records uses the original decimal
arithmetic order through `fx_number_to_decimal`.
Exact surd output also checks the converted fractional part first: whole-valued
records take the numeric fallback, including their preceding DMS/ENG selection.
Mathematically whole sums that convert to a stored near-integer retain exact
surd output; this test applies no approximate integer recognition.
The common-denominator serializer preserves the first displayed slot when its
coefficient is zero and skips common GCD reduction around zero coefficients.
If both radicands are1, the first stored term comes first and the second term
retains its explicit square-root construct. These rules follow the native
serialization rather than simplifying the expression algebraically.
Error records bypass selection and produce kind0 with the `ERROR` token
string; error code13 produces an empty string. Error-screen layout and UI
actions belong to the display/controller subsystem.

`fx_format_base.c` exposes `fx_format_base` for the original BASE-N formatter.
It accepts the full80FA byte:1 binary,7 octal,9 decimal orF hexadecimal.
Binary output is16 digits; octal is11 and hexadecimal8, including leading
zeros. Decimal output has no padding. Hexadecimal letters use glyph tokens
B8..BD. Negative nondecimal output uses two's complement. The original
absolute-value plus10^10 extraction and modulo32-bit accumulation are kept,
including their behavior for direct fractional/oversized decimal records.
Out-of-range binary magnitudes and tagged/marked records produce empty output,
as158B8 does. Other base settings return an explicit unsupported status.

`fx_format_budget.c` exposes the separate3500 formatter used by table cells
and inequality answers. Its firmware callers supply widths6 and12. Width6
uses small digit glyphs; width12 uses ordinary result tokens. Both first round
to ten significant digits (native precision byte11), then truncate the digits
to fit the sign, punctuation and exponent budget. The routine ignores
Norm/Fix/Sci, honors the punctuation setting, selects a small exponent font
when8127 is1, and extends the normal-output low threshold from-2 to-3 when
80FF is20. Ordinary rational and surd records use the original decimal conversion;
marked rational headers6x follow the native header rejection and produce `ERROR`.
error records produce the appropriate `ERROR` glyphs and a null input produces
an empty output. Input records remain unchanged.

Several details follow the original output rather than idealized arithmetic:
Norm2 limits the number of fractional positions; Fix0 includes a decimal
separator; the result stream uses0x60 for a leading negative sign and0x2d for
subtraction; and a near-unit DMS input can produce0 degrees60 minutes0 seconds
because the original minute cleanup does not independently carry into degrees.

The supported scopes and remaining gaps are recorded in `manifest.json`.
This is one subsystem of the ongoing firmware reimplementation; neither this
subsystem nor finite passing tests establishes whole-firmware equivalence.

Run `python tools/test_format_c.py` from the repository root. The test prepares
identical records and settings for C060 in the extracted original ROM and for
the new C formatter, compares every output token and result kind, checks input
immutability, and tests output-buffer boundaries with canaries. Its report is
`analysis/c-verification/format.json` and pins the tested source, fixtures and
oracle inputs by SHA256. These are routine-boundary tests with passive
peripherals, not boot/keyboard/LCD timing comparisons.

Run `python tools/test_format_base_c.py` for the separate BASE-N token suite.
Its source-pinned report is `analysis/c-verification/format_base.json`.

Run `python tools/test_format_budget_c.py` for the separate table/inequality
width suite. Its source-pinned report is `analysis/c-verification/format_budget.json`.
