/* High-level exact-output context predicate18212. GPL-3.0-or-later. */
#include "fx_math_context.h"

int fx_exact_output_allowed(const uint8_t memory[65536])
{
    if (!memory) return 0;
    /* ED selects the context that disables exact output. The operation
     * flags, Math setting, complex format, mode and restricted-state bit
     * supply the remaining eligibility gates. */
    return memory[0x80f5] != 0xed && !(memory[0x80fc] & 0x40) &&
           memory[0x8106] != 0 && memory[0x810c] != 1 &&
           (memory[0x80f9] & 0x40) != 0 && !(memory[0x8124] & 1);
}
