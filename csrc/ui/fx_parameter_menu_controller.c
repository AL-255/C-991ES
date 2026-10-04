/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_parameter_menu_controller.h"
#include <string.h>

enum { PARAMETER_SIMPLE = 1, PARAMETER_BANK, PARAMETER_CHILD,
       PARAMETER_COMPLETE, PARAMETER_RESET, PARAMETER_UNKNOWN };

static uint8_t get(fx_platform *p, uint16_t address)
{ return fx_data_read(p, 0, address); }

static fx_parameter_menu_status complete(fx_parameter_menu_controller *s,
                                         uint8_t returned)
{
    s->returned = returned;
    s->phase = PARAMETER_COMPLETE;
    return FX_PARAMETER_MENU_DONE;
}

static int table_grid(fx_platform *p)
{ return get(p, 0x80f9) == 0x88 && get(p, 0x80fc) == 18; }

static int admitted(fx_platform *p)
{
    if (get(p, 0x80fe) & 0x40) return 0;
    int equation_result = get(p, 0x80f9) == 0x45 && get(p, 0x80fc) == 1;
    int inequality_result = !equation_result &&
        get(p, 0x80f9) == 0x4b && get(p, 0x80fc) == 1;
    if ((equation_result || inequality_result) && get(p, 0x80f5) != 8) return 0;
    int distribution_result = get(p, 0x80f9) == 12 && get(p, 0x80fc) == 1;
    int distribution_parameters = !distribution_result && get(p, 0x80f9) == 12
        && get(p, 0x80fe) == 5 && (get(p, 0x80fc) & 16) && get(p, 0x811e) >= 2;
    if (distribution_result || distribution_parameters) {
        uint8_t key = get(p, 0x80f5);
        if (key != 8 && key != 1) return 0;
    }
    return 1;
}

static fx_parameter_menu_status simple_status(fx_platform *p,
    fx_parameter_menu_controller *s, fx_menu_status status)
{
    if (status == FX_MENU_DONE) {
        uint8_t selection, result;
        if (fx_menu_navigator_finish(&s->menu, &selection, &result) != FX_MENU_DONE)
            return FX_PARAMETER_MENU_INVALID;
        if (result == 2) {
            fx_data_write(p, 0, 0x80f5, selection);
            return complete(s, 1);
        }
        return complete(s, 0);
    }
    if (status == FX_MENU_RESET) {
        s->reset_source = s->phase;
        s->phase = PARAMETER_RESET;
    }
    return (fx_parameter_menu_status)status;
}

static fx_parameter_menu_status simple_begin(fx_platform *p,
    fx_parameter_menu_controller *s, uint8_t required_mode, uint8_t page)
{
    if (required_mode && get(p, 0x80f9) != required_mode) return complete(s, 0);
    s->phase = PARAMETER_SIMPLE;
    return simple_status(p, s, fx_menu_navigator_begin(p, &s->menu, page, 0));
}

static fx_parameter_menu_status bank_status(fx_parameter_menu_controller *s,
                                           fx_menu_status status)
{
    if (status == FX_MENU_DONE) {
        uint8_t returned;
        if (fx_mode_bank_menu_finish(&s->bank, &returned) != FX_MENU_DONE)
            return FX_PARAMETER_MENU_INVALID;
        return complete(s, returned);
    }
    if (status == FX_MENU_RESET) {
        s->reset_source = s->phase;
        s->phase = PARAMETER_RESET;
    }
    return (fx_parameter_menu_status)status;
}

static fx_parameter_menu_status child_status(fx_parameter_menu_controller *s,
                                            fx_parameter_menu_status status)
{
    if (status == FX_PARAMETER_MENU_DONE) {
        uint8_t returned;
        if (!s->services.finish ||
            s->services.finish(s->services.context, &returned) != FX_PARAMETER_MENU_DONE)
            return FX_PARAMETER_MENU_INVALID;
        return complete(s, returned);
    }
    if (status == FX_PARAMETER_MENU_RESET) {
        s->reset_source = s->phase;
        s->phase = PARAMETER_RESET;
    }
    return status;
}

static fx_parameter_menu_status child_begin(fx_platform *p,
    fx_parameter_menu_controller *s, fx_parameter_menu_child kind,
    uint8_t page, uint8_t argument)
{
    s->phase = PARAMETER_CHILD;
    s->request.kind = kind; s->request.page = page; s->request.argument = argument;
    if (!s->services.begin) return FX_PARAMETER_MENU_REQUEST;
    return child_status(s, s->services.begin(p, s->services.context, &s->request));
}

fx_parameter_menu_status fx_parameter_menu_controller_begin(fx_platform *p,
    fx_parameter_menu_controller *s, const fx_parameter_menu_services *services)
{
    if (!p || !p->ram || !s) return FX_PARAMETER_MENU_INVALID;
    /* The service table may itself have been retained in this controller. */
    fx_parameter_menu_services saved;
    memset(&saved, 0, sizeof saved);
    if (services) saved = *services;
    memset(s, 0, sizeof *s); s->services = saved; s->active = 1;
    if (!admitted(p)) return complete(s, 0);
    s->key = get(p, 0x80f5);
    uint16_t descriptor = (uint16_t)(0x2d26u + 4u*s->key);
    s->target_segment = (uint8_t)(get(p, (uint16_t)(descriptor + 2u)) & 15u);
    uint16_t low = get(p, descriptor);
    s->target_offset = (uint16_t)((low |
        (uint16_t)get(p, (uint16_t)(descriptor + 1u)) << 8) & 0xfffeu);
    uint32_t target = (uint32_t)s->target_segment << 16 | s->target_offset;
    switch (target) {
    case 0xcdca: return simple_begin(p, s, 2, 25);
    case 0xcdea: return simple_begin(p, s, 0xc4, 24);
    case 0xcdd2:
    case 0xcdf2:
        if (table_grid(p)) return complete(s, 0);
        return simple_begin(p, s, 0, target == 0xcdd2 ? 27 : 28);
    case 0xd55c:
        if (get(p, 0x80f9) != 0x89 || table_grid(p)) return complete(s, 0);
        return simple_begin(p, s, 0, 53);
    case 0xd074:
        s->phase = PARAMETER_BANK;
        return bank_status(s, fx_matrix_menu_begin(p, &s->bank));
    case 0xd0a0:
        s->phase = PARAMETER_BANK;
        return bank_status(s, fx_vector_menu_begin(p, &s->bank));
    case 0xce0a:
        if (get(p, 0x80f9) == 12)
            return child_begin(p, s, FX_PARAMETER_MENU_DISTRIBUTION,
                               get(p, 0x80fc) == 18 ? 58 : 57, 0);
        if (get(p, 0x80f9) != 3) return complete(s, 0);
        return child_begin(p, s, FX_PARAMETER_MENU_STATISTICS,
            get(p, 0x80fc) == 18 ? 29 : get(p, 0x80fa) == 1 ? 30 : 31, 0);
    case 0xd3b6:
        if (table_grid(p)) return complete(s, 0);
        return child_begin(p, s, FX_PARAMETER_MENU_RECALL, 0, 6);
    case 0xd3ee:
        if (get(p, 0x80f9) == 0x88) return complete(s, 0);
        return child_begin(p, s, FX_PARAMETER_MENU_STORE, 0, 7);
    case 0xd426: return child_begin(p, s, FX_PARAMETER_MENU_CLEAR, 1, 0);
    default:
        s->phase = PARAMETER_UNKNOWN;
        return FX_PARAMETER_MENU_UNIMPLEMENTED;
    }
}

fx_parameter_menu_status fx_parameter_menu_controller_tick(fx_platform *p,
    fx_parameter_menu_controller *s)
{
    if (!p || !p->ram || !s || !s->active) return FX_PARAMETER_MENU_INVALID;
    switch (s->phase) {
    case PARAMETER_COMPLETE: return FX_PARAMETER_MENU_DONE;
    case PARAMETER_RESET: return FX_PARAMETER_MENU_RESET;
    case PARAMETER_SIMPLE: return simple_status(p, s, fx_menu_navigator_tick(p, &s->menu));
    case PARAMETER_BANK: return bank_status(s, fx_mode_bank_menu_tick(p, &s->bank));
    case PARAMETER_CHILD:
        if (!s->services.begin || !s->services.tick) return FX_PARAMETER_MENU_REQUEST;
        return child_status(s, s->services.tick(p, s->services.context));
    default: return FX_PARAMETER_MENU_UNIMPLEMENTED;
    }
}

fx_parameter_menu_status fx_parameter_menu_controller_resume_timer(fx_platform *p,
    fx_parameter_menu_controller *s)
{
    if (!p || !p->ram || !s || !s->active) return FX_PARAMETER_MENU_INVALID;
    if (s->phase == PARAMETER_SIMPLE)
        return simple_status(p, s, fx_menu_navigator_resume_timer(p, &s->menu));
    if (s->phase == PARAMETER_BANK)
        return bank_status(s, fx_mode_bank_menu_resume_timer(p, &s->bank));
    if (s->phase == PARAMETER_CHILD && s->services.begin && s->services.resume_timer)
        return child_status(s, s->services.resume_timer(p, s->services.context));
    return s->phase == PARAMETER_CHILD ? FX_PARAMETER_MENU_REQUEST : FX_PARAMETER_MENU_INVALID;
}

fx_parameter_menu_status fx_parameter_menu_controller_finish(
    fx_parameter_menu_controller *s, uint8_t *returned)
{
    if (!s || !s->active ||
        (s->phase != PARAMETER_COMPLETE && s->phase != PARAMETER_RESET))
        return FX_PARAMETER_MENU_INVALID;
    if (returned) *returned = s->returned;
    s->active = 0;
    return s->phase == PARAMETER_RESET ? FX_PARAMETER_MENU_RESET : FX_PARAMETER_MENU_DONE;
}

uint8_t fx_parameter_menu_controller_export_mask(const fx_parameter_menu_controller *s)
{
    if (!s || !s->active) return 0;
    uint8_t source = s->phase == PARAMETER_RESET ? s->reset_source : s->phase;
    if (source == PARAMETER_SIMPLE) return s->menu.keys.export_mask;
    if (source == PARAMETER_BANK) return s->bank.menu.keys.export_mask;
    if (source == PARAMETER_CHILD && s->services.export_mask)
        return s->services.export_mask(s->services.context);
    return 0;
}

uint16_t fx_parameter_menu_controller_timer_period(const fx_parameter_menu_controller *s)
{
    if (!s || !s->active) return 0;
    if (s->phase == PARAMETER_SIMPLE) return s->menu.timer_period;
    if (s->phase == PARAMETER_BANK) return s->bank.menu.timer_period;
    if (s->phase == PARAMETER_CHILD && s->services.timer_period)
        return s->services.timer_period(s->services.context);
    return 0;
}
