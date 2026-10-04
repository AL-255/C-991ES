/* Statistics-only oracle host event adapter. GPL-3.0-or-later.
 * The unmodified SimU8 core executes the original firmware. The calculator
 * writes 2 to emulator host flag8e00 in5550, starts the timer, and samples
 * the flag at5564. A no-cancel host response clears it before that sample.
 * This adapter injects that response; it neither patches code nor skips an
 * instruction. It belongs only to the differential-test oracle. */
#include "harness.c"

int stats_oracle_call(uint32_t address, uint64_t limit, unsigned abort_poll) {
    unsigned polls = 0;
    harness_set_sp(0x8dee);
    harness_set_lr(0x2fffe);
    harness_set_pc(address);
    for (uint64_t index = 0; index < limit; ++index) {
        if (harness_get_pc() == 0x5564) {
            ++polls;
            if (!abort_poll || polls != abort_poll) ram[0x8e00] = 0;
        }
        int status = harness_run(1, 0x2fffe, false);
        if (status == 100) return 100;
        if (status != 103) return status;
    }
    return 103;
}
