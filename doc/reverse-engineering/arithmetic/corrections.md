# Corrections and proof boundaries

These contracts supersede ambiguous or incorrect earlier labels. They matter
when reading archived traces or implementing a seemingly equivalent formula.

| Topic | Correct interpretation |
| --- | --- |
| Integer gate `1CABE/194EC` | Raw bound `0x14` is packed decimal exponent 14: up to fifteen integer digits, not exponent 20. The narrower `1CAA8/194E4` gate is exponent nine. |
| Fraction precedence | Caller `167A6` stops incoming operator 100 on comparator decision one, not two. |
| Raw token 42 | Editor `=` decodes to value 42/kind 2. Comma is kind 9. |
| Admission masks | Operators 136..255 also belong to the mask-seven branch; an earlier prose list omitted them. |
| Compact surd type | Canonical type is `80`; archived raw `10` labels do not make it a surd. |
| Provider-table address | `17034`'s later provider path uses byte-wrapped doubling/addition before word-table access at `27DA`; do not carry the earlier shift into the add. |
| Status extraction | `1BB28` returns the low F code, so F0 can yield zero. Record class, evaluator condition and host API status are distinct. |
| Scalar preparation | `15C82` can leave headers >4F unchanged. Later ordinary arithmetic `1AB64` clears marker 40; a backed 61 reference can then be interpreted as its raw rational payload, not its first matrix cell. |
| Surd adapters | `174A0` uses coefficient offsets 0,20,40; `17C4A` copies a contiguous triplet forward. Neither warrants a generic overlap-safe copy assumption. |

Fraction/coordinate reduction at `16058..16182` is especially sensitive to
order. It clears numerator then denominator metadata, classifies denominator
first, and normalizes a negative denominator by negating fixed workspace +20
before the numerator. Preferred division's returned status is ignored at its
native point. Mixed fractions copy the retained fraction before popping the
whole component and still perform the final exact addition when whole is zero.
C4 realness checks use the incoming numerator companion and fixed workspace
+30; they are not both derived from arbitrary incoming operand pointers.

Successful Pol/Rec commits X first, then reads the live source for Y. With
prepared overlapping workspace addresses, writing X can alter the Y source.
This is evidence about that prepared alias contract, not a claim that ordinary
parser frames may live at arbitrary addresses. Likewise native chunk transport
rereads live C4 and secondary data after primary stores where specified.

The completed instruction ledger combines reviewed static semantics and scoped
native witnesses. It does not turn a native-only whole-expression trace into
a differential C proof. In particular the corrected literal/completion and
fraction/coordinate reviews include original-only caller observations; raw
field/cube-root preparation checkpoints do not prove an entire root body.
Bounded quantile witnesses do not establish all STAT cache lifecycles, aliased
RAM or post-provider N publication. Preserve those qualifiers when using the
findings outside their original boundary.

The current warm STAT mismatch in `AGENTS.md` is a concrete unresolved
production-state difference despite matching numerical/display results in that
workload. Do not replace missing scratch publication with captured final cache
bytes, or claim full parity from green prepared-API suites. Current source pins
and suite reports must be consulted before making a fresh implementation claim.

Corrected evidence: `analysis/understanding/INTEGER-GATE-ERRATUM.md`,
`analysis/understanding/parser/ADMISSION-REDUCTION-ERRATUM.md`,
`analysis/understanding/parser-fraction-coordinate/corrected-v4/FLOW.md`,
`analysis/understanding/numeric-high/gates.md`,
`analysis/understanding/numeric-high/final-entry-families/REMAINING-ENTRY-PREDICATE-ERRATUM.md`,
`analysis/understanding/final-closure/semantics/FINAL-100-LIMITS.md`.
