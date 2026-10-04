# Prepared SOLVE controller

`fx_solve_controller` represents the SOLVE frontend with named host state. Its
input, variable bank, selected ID and descriptor are separate from CPU registers
and frames. The production implementation executes no firmware instructions and
uses no host floating point.

The normal host sequence is `enter`, `advance` to prepare the list and first
prompt, then `edit` and `accept` for each typed coefficient or guess. After typed
acceptance, `advance` presents the next cell. Accepting an unchanged prompt
advances immediately without evaluating or rewriting the stored record. The
selected variable is always the final prompt. A terminating FF changes the native
item to4; the next `advance` restores the saved equation, sets the synthetic ED
token and captures a fresh descriptor with special-view byte0. `tick` then calls
the frozen finite-decimal SOLVE kernel.

Successful status0 and retained-estimate status36 preserve the root/residual pair,
publish the chosen variable, copy old Ans to PreAns and copy only the root to Ans.
Their item bytes are32 and64 respectively, with flags19 and result state3. The
ordinary replay bank and imaginary variable bank are retained. The display packet
at9800 is a separate host presentation packet and is updated when a prompt is
painted.

Prompt formatting preserves the original stored record. In particular, a marked
fraction with header6x reaches C060's decimal fallback with that same header;
its decimal serializer emits an empty string. The coefficient remains intact,
the result kind is10, and the host packet contains an empty text field. This
differs from an ordinary header2x fraction, which is displayed normally. Direction
keys on an unchanged FE4 prompt leave its expression cursor untouched; editing
starts only when a data token opens the coefficient input.

The expression callback returns both raw sides. It also reports the two named
evaluator effects for equation admission and restricted state. It receives the
existing Math setting together with an explicit C0 environment; exact-output
permission is resolved separately. Stored surds are decimalized on a C0 read,
while rational sides remain rational. The numeric kernel owns cleaned trial
publication policy, guard failures, finite arithmetic, alternate starts and
cancellation sampling. The frontend owns the selected bank, cursor and outer
commit.

The builtin expression adapter passes the platform's complete segment-zero data
view to the prepared parser. Native temporary/error-record copies can therefore
publish physical bank and allocation-mask changes beyond an ordinary real
variable store. An explicit external callback instead owns any additional bus
writes through its userdata; ordinary C1 stores retain the imaginary bank.

`ERROR` stops before the original error banner. A following `tick` enters the
shared nonblocking error controller and exposes its WAIT/EXPORT/RESET outcomes.
Final root/residual drawing and physical keyboard/menu acquisition belong to the
enclosing UI scheduler. See `manifest.json` for the current capability limits and
the independent differential report path.

The current source-pinned canonical report passes5,702 original controller
observations and35,657 checks. It includes an uninterrupted coefficient prompt,
typed expression, retained guess, fresh preparation, default prepared-memory
numerical evaluation and result commit for both Math settings and poisoned RAM.
It compares the full persistent RAM image, framebuffer and host display packets;
the measured CPU stack and named numerical scratch are documented exclusions.
Final root/residual presentation remains a separate scheduler/display stage.

The static/live evidence is reproducible under
`analysis/native-fixtures/solve-expression-grammar`. In particular, DE1C restores
an already-special screen's saved formula; saving an ordinary formula happens in
DCA4's E852 preparation before its first coefficient prompt.
