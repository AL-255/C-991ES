/* GPL-3.0-only. Passive observation of genuine original-ROM execution.
 * This adds stop boundaries to the existing unmodified CPU oracle. It never
 * replaces a callee, writes an expected return, or manufactures a key. */
#include "nxu8/harness.c"

uint32_t parameter_menu_target;
uint32_t parameter_menu_boundary;
uint64_t parameter_menu_steps;

void parameter_menu_observer_clear(void)
{
    parameter_menu_target = parameter_menu_boundary = 0;
    parameter_menu_steps = 0;
}

int parameter_menu_observe(uint64_t limit, int dispatch_only, int delegates)
{
    for (uint64_t i = 0; i < limit; ++i) {
        uint32_t pc = harness_get_pc();
        parameter_menu_boundary = pc;
        if (pc == 0xd85a) return 100; /* genuine MAIN caller continuation */
        if (pc == 0x1d8a4) return 200; /* actual host-key wait */
        if (pc == 0x53ce) return 202; /* actual timer delay */
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
