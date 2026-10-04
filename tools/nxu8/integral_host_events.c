/* Integration-only native oracle event/observation adapter. GPL-3.0-or-later.
 * Executes every original instruction. Supplies the timer/cancel response
 * described by5550/5564 and observes each integration callback's X. */
#include "harness.c"

unsigned integral_oracle_callbacks, integral_oracle_polls;
uint8_t integral_oracle_x[5000][10];

int integral_oracle_call(uint32_t address, uint64_t limit, unsigned abort_poll) {
    integral_oracle_callbacks = integral_oracle_polls = 0;
    memset(integral_oracle_x, 0, sizeof(integral_oracle_x));
    harness_set_sp(0x8dee); harness_set_lr(0x2fffe); harness_set_pc(address);
    for (uint64_t index = 0; index < limit; ++index) {
        uint32_t pc = harness_get_pc();
        if (pc == 0x5564) {
            ++integral_oracle_polls;
            if (!abort_poll || integral_oracle_polls != abort_poll) ram[0x8e00] = 0;
        }
        if (pc == 0x171ea && harness_get_reg(6) == 1 && !LCSR &&
            (LR == 0x47aa || LR == 0x47c4 || LR == 0x47ea || LR == 0x4804 ||
             LR == 0x4504 || LR == 0x45b4)) {
            if (integral_oracle_callbacks < 5000)
                memcpy(integral_oracle_x[integral_oracle_callbacks], ram + 0x8276, 10);
            ++integral_oracle_callbacks;
        }
        int status = harness_run(1, 0x2fffe, false);
        if (status == 100) return 100;
        if (status != 103) return status;
    }
    return 103;
}
