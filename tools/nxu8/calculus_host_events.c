/* Calculus-only native oracle adapter. GPL-3.0-or-later.
 * Original ROM and unmodified CPU execute every instruction.5550 writes2
 * to the emulator host flag8e00, starts a timer and samples it at5564. A
 * no-cancel timer response clears that flag before the sample; abort_poll
 * leaves it set at one selected sample. No code is patched or skipped.
 * The adapter also observes each expression re-evaluation's local X. */
#include "harness.c"

unsigned calculus_oracle_callbacks, calculus_oracle_polls;
uint8_t calculus_oracle_x[256][10];

int calculus_oracle_call(uint32_t address, uint64_t limit, unsigned abort_poll) {
    calculus_oracle_callbacks = calculus_oracle_polls = 0;
    memset(calculus_oracle_x, 0, sizeof(calculus_oracle_x));
    harness_set_sp(0x8dee);
    harness_set_lr(0x2fffe);
    harness_set_pc(address);
    for (uint64_t index = 0; index < limit; ++index) {
        uint32_t pc = harness_get_pc();
        if (pc == 0x5564) {
            ++calculus_oracle_polls;
            if (!abort_poll || calculus_oracle_polls != abort_poll)
                ram[0x8e00] = 0;
        }
        if (pc == 0x171ea && harness_get_reg(6) == 1 && !LCSR &&
            (LR == 0x434e || LR == 0x4442)) {
            if (calculus_oracle_callbacks < 256)
                memcpy(calculus_oracle_x[calculus_oracle_callbacks], ram + 0x8276, 10);
            ++calculus_oracle_callbacks;
        }
        int status = harness_run(1, 0x2fffe, false);
        if (status == 100) return 100;
        if (status != 103) return status;
    }
    return 103;
}
