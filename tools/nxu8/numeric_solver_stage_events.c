/* Passive observer: only this independent test executes the original ROM. */
#include "harness.c"

uint8_t solver_stage_ram[160][65536];
uint32_t solver_stage_pc[160], solver_stage_lr[160];
unsigned solver_stage_count, solver_stage_polls;

static void save(uint32_t pc)
{
    if (solver_stage_count >= 160) return;
    memcpy(solver_stage_ram[solver_stage_count], ram, 65536);
    solver_stage_pc[solver_stage_count] = pc;
    solver_stage_lr[solver_stage_count] = ((uint32_t)LCSR << 16) | LR;
    ++solver_stage_count;
}

void solver_stage_reset(void)
{
    solver_stage_count = solver_stage_polls = 0;
}

int solver_stage_run(uint64_t budget, unsigned cancel_at)
{
    for (uint64_t i = 0; i < budget; ++i) {
        uint32_t pc = harness_get_pc();
        if (pc == 0x5550) save(pc);
        if (pc == 0x5564) {
            ++solver_stage_polls;
            ram[0x8e00] = (uint8_t)(solver_stage_polls == cancel_at ? 2 : 0);
        }
        if (pc == 0x15658 || pc == 0x2fffe) {
            save(pc);
            return pc == 0x15658 ? 105 : 100;
        }
        if (solver_stage_count >= 160) return -40;
        int status = harness_run(1, 0x2fffe, false);
        if (status != 103) return status;
    }
    return 103;
}
