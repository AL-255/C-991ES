/* SPDX-License-Identifier: GPL-3.0-only */
#include "ui/fx_equation_controller.h"
#include "platform/fx_persistent.h"
#include <stddef.h>

/* Original E680 first clears display state, then routes screen21 through
 * E782. The production helper owns physical copying and state publication. */
int equation_commit_apply(fx_platform *platform, uint16_t source)
{
    fx_result_clear_display_state(platform);
    return fx_equation_commit_coefficient(platform, source);
}
size_t equation_commit_abi(unsigned field)
{
    switch (field) {
    case 0: return sizeof(fx_platform);
    case 1: return offsetof(fx_platform, rom);
    case 2: return offsetof(fx_platform, rom_size);
    case 3: return offsetof(fx_platform, ram);
    case 4: return offsetof(fx_platform, callback_pending);
    case 5: return offsetof(fx_platform, status);
    case 6: return sizeof(uint16_t);
    default: return (size_t)-1;
    }
}
