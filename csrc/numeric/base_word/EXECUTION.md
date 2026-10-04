# Prepared BASE word operations

`fx_base_word.h` exposes three distinct native policies as named fields. All
256 incoming selected bytes are accepted by these prepared value routines.
The original literal and UI-mask APIs continue admitting selectors1/7/9/15.

| Stage | Condition for the narrower policy | Other inputs |
| --- | --- | --- |
| Digit-to-word conversion15A94 | selected byte equals1 | unsigned word accumulation modulo2^32 |
| Word serialization15B00 | global calculation context equals2 and selected byte equals1 | signed32 serialization |
| Arithmetic result range15E82 | prior status equals0 and operation context equals2 | preserve prior status and result |
| Successful division15F58 | operation context equals2 | preserve exact/decimal scalar result |

Conversion adds10^10 and extracts ten mantissa digits without consulting the
exponent. A selected-BIN magnitude rejection leaves a negative input's word
positive. Logical operations ignore its carry, then apply the separate global
serialization policy. Consequently NOT(-32769) with selected1/global6 returns
-32770; selected0/global6 returns32768. Division7.5/2 with global6 returns3 for
operation context2, and3.75 for operation context6.

The implementation uses packed-decimal numeric APIs and unsigned32 integer
operations. It performs no original-ROM/CPU execution. Input/output aliases are
supported. Existing wrapper error ordering and literal mask admission remain
unchanged.

`tools/test_base_word_c.py` runs live original prepared routines on every selected
byte in calculation/operation contexts2/6/7/C1, signed boundaries, tagged scalar
records, crossed contexts, prior statuses and aliases. Native range-checker
output+40 is its documented comparison workspace and is outside immutable guard
checks; these value APIs export records and native statuses, rather than a RAM
image. The independent physical expression/controller owners retain that memory
integration responsibility.

Four explicit selected-BIN/global2 nonreturns remain in the canonical controls:
NOT(32768), plus OR/XOR/XNOR ofsqrt2/2 with32768. The original serializer searches
a zero residual pair repeatedly; the host keeps its output/status unchanged and
returns unsupported. These controls are retained separately from returning
native parity. Malformed records and caller/CPU-frame aliases remain explicit
value-API limits.

Before publishing the new report, rerun the existing BASE suite with
`python3 tools/test_numeric_base_c.py --random-cases 8000 --exhaustive-bin`.
The new verifier pins that fresh legacy report and checks that it tested the
current implementation/header hashes. Its legacy count is supporting evidence,
not added a second time to the prepared suite's comparison count.
