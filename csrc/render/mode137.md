# VERIFY mode result display

The mode is137 (0x89). The implementation is readable C; it does not execute
firmware. Original instructions are executed only by the independent test
oracle. Documented instruction understanding is100%; complete firmware C
implementation is stillfalse.

C060 handles F* error records before its mode switch. Other mode137 records
call8000, whose class1 branch selects the live word at8DF2 (startup FALSE),
while every other class selects8DF4 (startup TRUE). These are configurable
ROM/RAM string pointers. Bytes are copied verbatim and null pointers produce
empty strings. Recognition, decimal conversion, scientific suffix conversion
and ordinary selection/cache/MMIO events do not run on this branch.

The helper models the precise Boolean projection of1CCF6. Firstbyte0 is class1
regardless of the remaining bytes. A noncompact tag below50 is class1 when
bytes8/9 are bothzero. Compact80 records never take class1, even when opposite
terms cancel mathematically. Other noncompact tags50..E0 are TRUE. Direct8000
also treats F* as TRUE; C060 error precedence emits ERROR (FD emits empty).

The addressed wrappers prepare each scalar through a two-byte head followed
by an even-aligned eight-byte tail. OrdinaryB070 prepares the companion first,
then the real record. This differs from a contiguous ten-byte read at odd
source addresses. The named-record helper accepts already-prepared records.

37BC paints the current fixed row (22 for font10,25 otherwise), clears RAM
framebuffer rows, aligns with byte-valued length*6 and uses the existing glyph
renderer. Its kind0 commit clears8100's high nibble and leaves8130 and entry
8127 unchanged. B070's E844 route uses this branch when80FC bit4 is set and
80FE is0,3 or5. This route precedes ordinary paired-status handling and skips
ordinary token/history/cache updates. The semantic return1 means successful
rendering; native R0 is the consumed/draw return and is not asserted equal1.

OrdinaryB070 mode137 retains real/imaginary composition, initial-selection
kind commits, natural permission and cached unread-source bypass. Its first
component is written directly to persistent8398. Selection10 single-real
output then clears only the first persistent byte, preserving the dormant
FALSE/TRUE tail. Natural/cached viewport output saves normal history first,
then the mode137-only B468..B48E block saves raw result tokens again. Its
emptiness test uses the low byte of string length, so length256 produces an
empty second history entry. Dormant bytes from the first save are preserved.
Ordinary completion clears8127 and restores812C.

The new helper checks capacities/terminators and rejects a NULL ROM with a
nonzero size. NULL ROM with size0 can provide RAM labels. Source/output must
not overlap. Nonterminated full-map labels return UNIMPLEMENTED. The special
native local string field is26 bytes: nonerror length25 is admitted and
compared with the original; length>=26 is a CPU-frame alias boundary, returned
as-1 before renderer state changes. A host guard checks this boundary without
claiming a complete native overflowing-frame comparison.

## Evidence

Run `python3 tools/test_render_mode137_c.py` for the guarded canonical workload.
The input-only fixture contains7048 recipes: all256 header bytes at8000/C060,
all256 special-selection bytes, signs/tags/compact cancellation, both Math
settings, ordinary real/complex/cache flows, live/default/null/raw-token labels,
odd addresses, three fonts/two maps, E844 phase/flag admission, finite25-byte
labels, cached256-byte strings, structured-history labels, and ordinary mode
regressions. Each recipe runs against the original and both O2/O3 C builds.
The report is `analysis/c-verification/render_mode137.json`.

The genuine final workload passes129134 checks:14096 primary original calls
plus9936 framebuffer-flush calls. It compares Boolean tokens, exposed settings,
retained token/record bytes, history,384 RAM pixels and all512 LCD bytes before
and after flush. Ninety source/oracle/input pins and built library hashes are
guarded before/after execution. Compiled ABI probes and output canaries are
included. Custom/reduced publication attempts and Python-O are rejected;
`analysis/verification/render-mode137-publication-guards.json` records the five
actual rejection controls and unchanged preexisting report digest.

Native numeric workspace8000..80DB is excluded except active viewport fields;
inactive8640..877F numeric/metric scratch is excluded. Arbitrary source/label
aliasing with numeric workspaces, output/history/framebuffer, CPU temporary
stack/register/flag equivalence and nonreturning copies are not claimed.
Ordinary80FF bit4 paired/status composition and equation69 remain separate
pending paths. This closes the nonerror mode137 serialization/display branch
inside the existing prepared record APIs, not a whole boot-to-key UI.

Three genuinely rerun ordinary regression reports retain their full workloads:
render2,832,258 cases; complex28,301 cases; linalg79,552 checks/13,125 calls.
Their exact source pins and results remain in their respective canonical
reports. The original failed pilot/full/supplement runs remain private under
analysis/build/render-mode137; they were not relabeled or retagged.
