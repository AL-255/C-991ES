# CALC variable discovery

`fx_calc_scan_variables` implements the non-SOLVE branch of original172F6 in readable C. It scans the prepared input at8398 and writes the physical FF-terminated variable list at83FE. It does not evaluate the expression or check its complete syntax.

The scanner recognizes an assignment only when its variable is the first token of a colon-separated statement. It omits that assignment target from the current prompt list, and commits the target to its assigned-variable mask only when the statement ends. Thus `A=3:A+X` prompts for X, while `A=A+X:A` still discovers A on the first statement's right side. Variables discovered earlier stay in their original order; a later assignment does not remove an existing list entry.

Ans and token variable10 do not prompt. C1's C8 token override remains the shared token decoder's responsibility. Variable-mask shifts follow the original eight-bit mapping, including M's id0 mapping. The scanner checks screen80FC.bit6: SOLVE screens are declined before any mutation and continue to use the separate SOLVE scanner.

The independent differential suite `tools/test_calc_scan_c.py` executes 7412 original calls: every input byte in four calculation contexts, assignment/dependency statements in all256 contexts, 2000 seeded raw streams, every non-SOLVE screen byte in COMP/CMPLX, and overlong source streams that intersect the physical output list. Every case starts with poisoned RAM. It compares status and all65536 RAM bytes except each call's CPU frame, whose minimum SP is observed during actual original execution. The measured floors are8DDC/8DDE; the variable list, source stream, variable banks, peripherals and display memory are compared. Seven additional checks cover invalid-host and SOLVE admission guards.

The enclosing CALC prompts, typed coefficient acceptance, automatic evaluation and error continuation remain separate integration work. The scanner has a bounded-host limit of65536 token reads; this limit is not claimed as a native return value.
