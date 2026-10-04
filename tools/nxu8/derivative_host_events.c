/* Differentiation native oracle event/observation adapter. GPL-3.0-or-later.
 * Executes every original instruction; supplies the original timer response. */
#include "harness.c"

unsigned derivative_oracle_callbacks, derivative_oracle_polls;
uint8_t derivative_oracle_x[512][10];

int derivative_oracle_call(uint32_t address, uint64_t limit, unsigned abort_poll) {
    derivative_oracle_callbacks = derivative_oracle_polls = 0;
    memset(derivative_oracle_x, 0, sizeof(derivative_oracle_x));
    harness_set_sp(0x8dee); harness_set_lr(0x2fffe); harness_set_pc(address);
    for (uint64_t index = 0; index < limit; ++index) {
        uint32_t pc = harness_get_pc();
        if (pc == 0x5564) {
            ++derivative_oracle_polls;
            if (!abort_poll || derivative_oracle_polls != abort_poll) ram[0x8e00] = 0;
        }
        if (pc == 0x171ea && harness_get_reg(6) == 1 && !LCSR &&
            LR >= 0x4a62 && LR < 0x4f26) {
            if (derivative_oracle_callbacks < 512)
                memcpy(derivative_oracle_x[derivative_oracle_callbacks], ram + 0x8276, 10);
            ++derivative_oracle_callbacks;
        }
        int status = harness_run(1, 0x2fffe, false);
        if (status == 100) return 100;
        if (status != 103) return status;
    }
    return 103;
}
