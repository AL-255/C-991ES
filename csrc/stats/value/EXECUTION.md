# Stored Y-mean dynamic constant

Raw evaluator token `8A` has kind6/value57. The dynamic-constant table lookup
at `17012..17022` selects the original `13448` wrapper via table word `27FA`.
The wrapper chooses Y, calls `12D8E`, then applies the shared `13472` tail:
`1CEF0` numeric cleanup followed by copying the ten-byte result. The direct
prepared status is the result record's error nibble, or zero for a finite value.
No calculator instructions or ROM are executed by the C implementation.

`fx_stats_mean_y_prepared` takes a complete segment-zero RAM view and a separate
output record. It reads the row count at `80DE`, model/selection at `80FA`, and
frequency enable byte at `8109`. The native field and stride policies differ:

| Physical policy | Native behavior |
| --- | --- |
| Y field | Always physical field1, including one-variable model1 |
| Frequency field | field1 when `80FA=1`; field2 otherwise |
| Row width in context12 | Two records |
| Row width in context88 | Three if `810E!=0` and `8138.bit7=0`; two otherwise |
| Other row widths | One variable if `80FA=1`, two otherwise, plus frequency |

Consequently a one-variable unweighted Y query reads the next physical X
record, and the final query reads the following RAM record. With frequency
on in model1, Y and frequency refer to the same physical field. The adapter
constructs this field view as a two-variable typed table and uses the existing
high-level statistics arithmetic, preserving native count/sum/division order.
The typed table is a host value view; it does not rewrite calculator RAM.

The native direct wrapper uses numeric-register and CPU-call-frame workspace.
The independent verifier observes its actual minimum SP and compares every
other byte from `80DC` through `FFFF`, including the poisoned moment cache
`829E..82ED`, flag `812A`, table data and physical high bank aliases. The native
oracle executes the original firmware; expected results are not fixtures.

The canonical input-only corpus covers 4,200 direct original calls across
seven contexts, five model bytes, four frequency bytes, three context88 column
controls, both suppression states and row counts0/1/2/3/20. Actual production
C is compiled separately with GCC `-O2` and `-O3`; both implementations are
compared to the same fresh native call. Host null/size guards retain output
and RAM.

Whole-expression investigation is separate. The raw8A parser seam must leave
the cursor on the token after a dynamic-constant error, advance on success,
and treat a failed constant as fatal during calculus preflight. It bypasses
the arithmetic dispatcher's numerical-error-to-zero policy. There is no
raw8A-specific screen-bit6 guard. Successful complex constant evaluation has
zero imaginary part; ordinary evaluation preserves its caller secondary.

This does not claim arbitrary unchecked metadata or CPU-frame/table/output
alias completeness. The unfiltered whole-expression prototype retains48
oversized row-count/data-overlap host gaps, as well as preexisting invalid
BASE selector, exact-sqrt workspace and SCREENFF result-storage gaps. These
cases remain recorded as gaps; a negative host result does not fabricate a
native Math error. Parser integration is owned separately.
