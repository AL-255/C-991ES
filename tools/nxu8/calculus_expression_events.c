/* Complete calculus-expression observation adapter. GPL-3.0-or-later.
 * Original ROM and CPU execute every instruction. The host only answers
 * the5550/5564 timer request and observes callback/poll coordinates. */
#include "harness.c"

unsigned calculus_expression_callbacks, calculus_expression_polls;
uint8_t calculus_expression_x[8192][10], calculus_expression_poll_x[8192][10];

int calculus_expression_call(uint32_t address, uint64_t limit, unsigned abort_poll) {
    calculus_expression_callbacks = calculus_expression_polls = 0;
    memset(calculus_expression_x, 0, sizeof(calculus_expression_x));
    memset(calculus_expression_poll_x, 0, sizeof(calculus_expression_poll_x));
    harness_set_sp(0x8dee); harness_set_lr(0x2fffe); harness_set_pc(address);
    for (uint64_t index = 0; index < limit; ++index) {
        uint32_t pc = harness_get_pc();
        if (pc == 0x5564) {
            if (calculus_expression_polls < 8192)
                memcpy(calculus_expression_poll_x[calculus_expression_polls], ram+0x8276, 10);
            ++calculus_expression_polls;
            if (!abort_poll || calculus_expression_polls != abort_poll) ram[0x8e00] = 0;
        }
        if (pc == 0x171ea && harness_get_reg(6) == 1 && !LCSR &&
            (LR == 0x434e || LR == 0x4442 || LR == 0x47aa || LR == 0x47c4 ||
             LR == 0x47ea || LR == 0x4804 || LR == 0x4504 || LR == 0x45b4 ||
             (LR >= 0x4a62 && LR < 0x4f26))) {
            if (calculus_expression_callbacks < 8192)
                memcpy(calculus_expression_x[calculus_expression_callbacks], ram+0x8276, 10);
            ++calculus_expression_callbacks;
        }
        int status = harness_run(1, 0x2fffe, false);
        if (status == 100) return 100;
        if (status != 103) return status;
    }
    return 103;
}
