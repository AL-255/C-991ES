# Ordered SURD components

`fx_surd_components.c` implements the prepared compact-radical conversion at
native `178BA` and `17576`. It writes six ten-byte numerical components into
physical RAM `8640..867B`, then evaluates the two terms with the existing
prepared decimal arithmetic. It executes no firmware or CPU instructions.

The component order is coefficient, radicand, denominator for the first term,
then coefficient, radicand, denominator for the second. Each component commit
precedes the next source-field read. A source overlapping the component pool
therefore changes subsequent fields. If the first coefficient byte is zero,
the first triple becomes zero, zero, one; its radicand and denominator fields
are skipped. The second triple always reads its fields. The copy entry takes
a ten-byte source snapshot first, matching TABLE's private work record.

After emission, `17576` performs no further component-pool writes before its
destination commit. A completed six-component snapshot is consequently safe
for numerical evaluation. The evaluation retains the native order: each root
is multiplied by its coefficient and divided by its denominator, then the
second term is the left operand of the addition. This order also preserves
which numerical error survives. Aligned source aliases can produce raw sign2
coefficients; the prepared raw arithmetic handles those coordinates directly.

The additive `fx_numeric_component_sqrt` facade exposes the existing component
root policy without changing its algorithm. An active positive-tagged zero
radicand follows that policy's short unnormalized exponent-prefix path. The
ordinary scalar square-root API has a different zero admission policy.

`emit_live` and `convert_live` require a 64 KiB RAM view and bounded ten-byte
source/destination regions. Invalid pointers or addresses return
`FX_NUMERIC_INVALID` before any commit. `convert_copy` snapshots the source;
its output may alias the source or a completed component. `decimal` performs
all numerical reads before its output commit, so its output may overlap any
of the six completed components. Numerical F* records are successful host
results. A host arithmetic gap prevents the final numerical output commit.
`decimal` leaves its output untouched. Both conversion entries retain prior
component emission, including emitted bytes overlapping their output or
destination. The final numerical output commit follows all component reads.

The proved active radicand domain is positive-tagged packed integers 0..999.
Canonical aligned aliases and the observed raw sign2 coefficients are covered.
Arbitrary malformed roots, wider raw radicands, generic unnormalized quotient
states beyond the prepared denominator contract and CPU-buffer overlap remain
outside this proof. This helper performs no allocation, reference rewriting,
polling or caller cleanup. The existing rich unary leaf remains unchanged.

Run the portable differential proof with:

```sh
python tools/test_numeric_surd_components_c.py
```

The default compiles actual production code at O2 and O3. At each level it
reruns 545 immutable ABS/ROUND alias inputs, ten whole TABLE inputs, ten direct
copied loader inputs and 1,023 prepared component-root inputs through the
unchanged original ROM. Input-only fixtures store exact initial 64 KiB RAM;
expected results are never loaded from an archive. The original component
checkpoints additionally test ordered emission and all six output-overlap
positions. Portable controls cover nulls, bounded addresses and noncommit on
unsupported roots. Full persistent RAM comparisons retain all 1,440 physical
payload bytes and timer state; exclusions are limited to numeric workspace
`8000..80DB` and individually witnessed native CPU stack writes. Direct root
rawR0 is recorded independently of host status.

The tool records compiled ABIs, fresh original observations and pre/post input
hashes under `analysis/build/numeric-surd-components`. A passing default run
publishes `analysis/c-verification/numeric_surd_components.json` through the
shared report writer with all transitive C/H and local oracle/tool inputs.
Every fault, native non-return or host failure remains in the run evidence and
prevents publication of a passing canonical report.
