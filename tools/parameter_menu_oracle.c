/* GPL-3.0-only. Passive observation of genuine original-ROM execution.
 * This adds stop boundaries to the existing unmodified CPU oracle. It never
 * replaces a callee, writes an expected return, or manufactures a key. */
#define memorySetData parameter_menu_original_memorySetData
#include "nxu8/harness.c"
#undef memorySetData

uint8_t parameter_menu_frame_mask[65536];
static uint16_t parameter_menu_initial_sp;

void memorySetData(SR_t segment, EA_t offset, size_t size, uint64_t value)
{
    /* Keep the original data bus behavior. Observe only bytes actually
     * written inside the currently live CPU stack; untouched frame bytes
     * and every non-frame RAM/MMIO byte remain part of the comparison. */
    if (!segment)
        for (size_t i = 0; i < size; ++i) {
            uint16_t address = (uint16_t)(offset + i);
            if (address >= SP && address < parameter_menu_initial_sp)
                parameter_menu_frame_mask[address] = 1;
        }
    parameter_menu_original_memorySetData(segment, offset, size, value);
}

uint32_t parameter_menu_target;
uint32_t parameter_menu_boundary;
uint64_t parameter_menu_steps;

void parameter_menu_observer_clear(void)
{
    parameter_menu_target = parameter_menu_boundary = 0;
    parameter_menu_steps = 0;
    parameter_menu_initial_sp = harness_get_sp();
    memset(parameter_menu_frame_mask, 0, sizeof parameter_menu_frame_mask);
}

int parameter_menu_observe(uint64_t limit, int dispatch_only, int delegates)
{
    for (uint64_t i = 0; i < limit; ++i) {
        uint32_t pc = harness_get_pc();
        parameter_menu_boundary = pc;
        if (pc == 0xd9d6) return 250; /* unchanged child result at caller */
        if (pc == 0x1824e) return 203; /* actual reset request, before body */
        if (pc == 0xd85a) return 100; /* genuine MAIN caller continuation */
        if (pc == 0x1d8a4) return 200; /* actual host-key wait */
        /* 538A clobbers ER0 while copying its period to F020. Distinguish
         * DFDE's two actual timer calls by their immutable return sites;
         * keyboard settling uses this same shared53CE return instruction. */
        if (pc == 0x53ce && LCSR == 0 && (LR == 0xe0d2 || LR == 0xe126))
            return 202;
        if (delegates && (pc == 0xe17e || pc == 0xd312 ||
            pc == 0xceb0 || pc == 0xcfa8 || pc == 0xd580)) return 300;
        int result = harness_run(1, 0x2fffe, false);
        ++parameter_menu_steps;
        if (result != 103) return result;
        if (pc == 0xd6a6) {
            parameter_menu_target = harness_get_pc();
            if (dispatch_only) {
                parameter_menu_boundary = parameter_menu_target;
                return 201; /* after executing original far POP PC */
            }
        }
    }
    return 103;
}
