The real derivative adapter stores its Richardson algorithm state in physical RAM. It executes no CPU instructions and reads no ROM code. The existing scalar derivative remains unchanged.

The caller first parses/finishes the point, then calls `fx_derivative_storage_point`. That applies the native 15C82 scalar normalization and stores the point at 85F0 before explicit tolerance evaluation. Next it calls `fx_derivative_storage_tolerance` with the parsed tolerance or NULL. Explicit tolerance stores 85E6 and writes only FF at 85FA; default preparation stores 1e-10 at 85E6, 1e-7 at 85FA, and writes only FF at 8604. Invalid tolerance returns native8 without completing these writes.

`fx_number_derivative_storage` uses RAM as the authoritative state. It validates the callback at the point, selects the initial power-of-ten step and up to seven ratio probes, samples plus then minus, and updates the descending Richardson triangle in native order. It reloads point, step, tolerance, factors and table records after callbacks/polls. Default exhaustion is ten refinements; explicit exhaustion is fifteen. The default error gates save estimates at 1e-7 through1e-9; clearing the gate writes only its first byte. Saved-best fallback copies 8604 into85B4. A tiny-derivative zero result preserves the physical leading record.

The semantic record map is:

| Address | Quantity |
| --- | --- |
| 8578 | Probe value/error |
| 8582 | Base function value |
| 858C | Probe point |
| 8596 | Ratio lower limit0.9 |
| 85A0 | Ratio width0.2 |
| 85AA | Ten, then a Richardson row |
| 85B4 | Leading Richardson record |
| 85BE | Previous leading value, then relative error |
| 85C8 | Negative Richardson factor |
| 85D2 | Doubled step |
| 85DC | Step |
| 85E6 | Relative tolerance |
| 85F0 | Point |
| 85FA | Default prior-error gate or explicit sentinel |
| 8604 | Default best estimate or first-byte sentinel |

The triangle descends from85B4 in ten-byte rows, reaching851E for explicit exhaustion. These addresses overlap matrix/vector bank slots7/8. The caller must refresh its typed bank before callback evaluation and after preparation/driver updates. The callback owns expression evaluation and rich finish. The driver publishes real X at8276; the caller owns native522A variable publication and saved-X restoration. An evaluator-error callback publishes its canonical F(status) at85B4 immediately, including a failed probe that is retried. An EVALUATION_OK callback carrying an F record retains the separate success channel.

The supported global80F9 contexts are C1,6,7. Other contexts return host UNIMPLEMENTED before writes. C4's20-byte complex argument/callback contract is outside this adapter. Negative host callback status leaves the API output unchanged. Timer/device RAM effects remain owned by the supplied control/platform adapter; they are not synthesized as derivative state.

The new portable suite runs118 original whole171F4 expressions live, then compares the staged C adapter at O2 and O3. It checks every callback/poll workspace snapshot8500..867F, final fixed workspace, all16 physical bank dimensions and payload829E..883D, output, polls and immutable argument values. Twenty-eight controls mutate live RAM from callbacks/polls. It retains the upstream rich-argument boundary explicitly: a stored61 input is prepared by the original parser asF9 before point staging. This does not claim full parser integration. A supplied SURD emits its six component records at8640..867B, but a variable already converted by the parser needs its upstream physical conversion stores from that parser.

The original spans are04A62..04AEC (paired samples),04AEE..04DCA (driver/preparation),04DCC..04F24 (step probes), plus15C82 and171EA/17250 callback finishing/publication. Their mathematical ranges were already recorded by the scalar derivative module; this physical adapter introduces no additional understood instruction claim.

Native CD60/CD94 comparisons copy raw records without rational conversion. Their AB3E/AB36 test returns comparison F0 whenever either raw first byte is at least10. The adapter uses named1(equal),2(less),4(greater),F0(invalid) relations and preserves each driver guard: invalid tolerance comparison is not greater, so04D1E accepts the current estimate; ratio width accepts only1/2; probe equality accepts only1. Twelve original poll-mutation controls inject F3,61 and91 into tolerance/prior-error/ratio records and verify these paths. A remaining malformed decimal coordinate with first byte below10 but invalid canonical decode returns explicit host UNIMPLEMENTED before reading decoded fields. It is not assigned a fabricated numerical F3.
