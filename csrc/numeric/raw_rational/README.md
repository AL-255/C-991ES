# Prepared raw rational arithmetic

`fx_raw_rational_binary` is handwritten C for ordinary packed decimals and unchecked ordinary/marked fractions. It preserves admission, right-first component multiplication, sign adjustment, GCD, quotient/remainder, field packing, cleanup and marker ordering. Both input values are captured before the terminal result/status commit, so complete and partial value aliases are supported.

Run `python3 tools/test_raw_rational_c.py` for the input-only corpus and fresh original-ROM comparisons. The production proof passed 14,815 original calls and 1,320,642 checks across strict O2/O3 builds: 14,781 exact handled results per build, 20 separately declared compact-surd/header controls and 14 fixed-budget native boundaries. Boundaries return host UNIMPLEMENTED without committing result/status; they are not fabricated numerical errors.

The API covers values and independent native status. Original numerical scratch, MMIO, register/stack writes and odd-pointer marshaling are outside it. REF/RREF caller integration additionally compares persistent RAM and callback states.

The preferred-divide review (local evidence: `analysis/raw-rational-wrapper-audit/REVIEW.md`) documents the 29 newly inventoried semantic instructions. This is an understanding claim, separate from C implementation completion. The global project remains incomplete.
