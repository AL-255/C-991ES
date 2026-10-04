The address classifier preserves the persistent effects of `1CCF6`. It saves
its source and companion at `805C/805E`, snapshots the ten-byte external record,
and stores the reversed finite representation at `8000`. Native field loading
advances its eight-byte tail to an even address after the initial two bytes;
this is observable for odd source aliases.

Direct classification returns 1 for zero, 2 for negative, 4 for positive, or
F0 for an inadmissible tag. Compact surds choose a coefficient sign without
conversion when possible. A nonzero second sign and wrapping sign sum 7
select decimal component evaluation. That branch deliberately bypasses the
ordinary zero predicate: exact compact cancellation still returns class 4.

The mixed-sign branch expands six decimal records at `8640..867B`. It evaluates
each term in square-root, coefficient multiplication and denominator division
order. The C implementation uses decimal operations and integer mantissa
windows to preserve final numeric fields at `8000..805F`, including root and
product windows, division guards, the first term, and the smaller aligned
operand. Alignment shifts its sign byte with the mantissa; discarded digits
can replace that byte's sign nibbles. Zero radicands, coefficients and
denominators retain the original raw-record quirks.

The result's `continuation` is a semantic output: unchanged companion on direct
branches, or the final mantissa low word after decimal conversion. Annunciator
rendering carries it between its 8226 and mode-C4 8408 calls. All classifier
workspaces are now included in annunciator, outer key-controller and full
boot diagnostic RAM comparisons. These APIs retain no CPU register frame.

Only canonical BCD components and prepared source addresses are admitted for
mixed-sign conversion. Direct branches admit arbitrary records and argument
or operand aliases. CPU-stack source aliases are rejected before mutation.
Unsupported conversions preserve the known argument/load prefix before
returning an explicit status. The differential suite compares every final
RAM/MMIO byte outside native CPU stack `8D00..8DED`, classification,
continuation, callback state and source immutability. It does not equate
mathematical reconstruction with an identical sequence of intermediate CPU
stores, and it does not claim complete firmware behavior.
