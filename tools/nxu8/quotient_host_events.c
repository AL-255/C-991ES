/* Read-only native quotient wrapper observations; no arithmetic replacement. */
#include "harness.c"

unsigned quotient_accepts, quotient_rejects, quotient_fallbacks;
unsigned quotient_polls, quotient_error_admissions;
unsigned quotient_truncations, quotient_noncanonical_prefixes;
uint8_t quotient_normalized[20];

int quotient_wrapper_call(uint64_t limit)
{
    quotient_accepts = quotient_rejects = quotient_fallbacks = 0;
    quotient_polls = quotient_error_admissions = 0;
    quotient_truncations = quotient_noncanonical_prefixes = 0;
    memset(quotient_normalized,0,sizeof quotient_normalized);
    harness_set_sp(0x8dee); harness_set_lr(0x2fffe);
    harness_set_pc(0x1c138);
    for (uint64_t i = 0; i < limit; ++i) {
        uint32_t pc = harness_get_pc();
        if (pc == 0x1c158) {
            memcpy(quotient_normalized,ram + 0x8000,10);
            memcpy(quotient_normalized + 10,ram + 0x8010,10);
        }
        if (pc == 0x191b2) ++quotient_accepts;
        if (pc == 0x1b328 && ram[0x8009] < 0xf0) {
            ++quotient_truncations;
            if ((ram[0x8000] >> 4) > 9 || (ram[0x8000] & 15) > 9 ||
                ram[0x8001] > 9) ++quotient_noncanonical_prefixes;
        }
        if (pc == 0x191ba) ++quotient_rejects;
        if (pc == 0x1c178) ++quotient_fallbacks;
        if (pc == 0x1c172) ++quotient_error_admissions;
        if (pc == 0x5550 || pc == 0x5564) ++quotient_polls;
        int status = harness_run(1,0x2fffe,false);
        if (status != 103) return status;
    }
    return 103;
}
