/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_verify_controller.h"

fx_ui_status fx_verify_controller_begin(fx_platform *platform,
    fx_verify_controller *state,uint8_t refresh_only,
    const fx_calculus_control *cancellation)
{
    if(!platform || !platform->ram || !state ||
       (!platform->rom && platform->rom_size))return FX_UI_INVALID;
    if(platform->ram[0x80f9]!=0x89 || platform->ram[0x80fc]!=1)
        return FX_UI_UNIMPLEMENTED;
    return fx_ui_controller_begin(platform,&state->screen,refresh_only,cancellation);
}

fx_ui_status fx_verify_controller_tick(fx_platform *platform,
    fx_verify_controller *state)
{
    if(!platform || !platform->ram || !state)return FX_UI_INVALID;
    if(state->screen.context.calculation_mode!=0x89 ||
       platform->ram[0x80f9]!=0x89)return FX_UI_UNIMPLEMENTED;
    return fx_ui_controller_tick(platform,&state->screen);
}

fx_ui_status fx_verify_controller_finish(fx_verify_controller *state,
    uint8_t *context_return)
{
    if(!state)return FX_UI_INVALID;
    return fx_ui_controller_finish(&state->screen,context_return);
}

uint8_t fx_verify_controller_export_mask(const fx_verify_controller *state)
{
    return state?fx_ui_controller_export_mask(&state->screen):0;
}
