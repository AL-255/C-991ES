/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_input_recover.h"
#include "../platform/fx_boot.h"
#include "../platform/fx_persistent.h"
#include "../render/fx_result_special.h"

static uint8_t read_byte(fx_platform *p, uint16_t a)
{
    return fx_data_read(p, 0, a);
}

static void write_byte(fx_platform *p, uint16_t a, uint8_t v)
{
    fx_data_write(p, 0, a, v);
}

static int copy_string(fx_platform *p, uint16_t destination, uint16_t source)
{
    if (!destination) return 0;
    if (!source) { write_byte(p, destination, 0); return 0; }
    for (unsigned i = 0; i < 65536; ++i) {
        uint8_t byte = read_byte(p, source++);
        write_byte(p, destination++, byte);
        if (!byte) return 0;
    }
    return -1;
}

static void prepare_input(fx_platform *p)
{
    write_byte(p, 0x80fc, 1);
    write_byte(p, 0x80fd, 0);
    write_byte(p, 0x80fe, 1);
    write_byte(p, 0x80ff, 0);
}

int fx_input_recover_after_error(fx_platform *p, fx_input_recovery_context *context)
{
    if (!p || !context) return -1;
    if (fx_boot_initialize_editor(p, 2) != FX_BOOT_READY) return -1;
    fx_render render = {p->rom, p->rom_size, p->ram};
    if (context->saved_math_result) {
        fx_result_clear_flags(p);
        if (fx_display_special_real_result(&render, context->result_address, NULL) != 1) return -1;
        context->return_value = 1;
        return 0;
    }
    if (read_byte(p, 0x80f9) == 12) {
        fx_clear_framebuffer(&render);
        fx_boot_initialize_mode12(p);
        write_byte(p, 0x80f5, 0);
        write_byte(p, 0x8129, 0);
        context->return_value = 0;
        return 0;
    }
    fx_result_clear(p);
    if (context->calculation_mode == 0x88) {
        if (read_byte(p, 0x80fd)) {
            if (copy_string(p, context->display_address, 0x81b8)) return -1;
            write_byte(p, 0x80fd, 0);
        } else if (read_byte(p, 0x810e) == 1 && (read_byte(p, 0x8138) & 1)) {
            for (unsigned i = 0; i < 100; ++i) write_byte(p, (uint16_t)(0x85aa + i), 0);
        } else fx_boot_clear_exported_input(p);
        fx_clear_framebuffer(&render);
    }
    prepare_input(p);
    return 1;
}

int fx_input_reset_context(fx_platform *p, fx_input_recovery_context *context)
{
    if (!p || !context) return -1;
    if (fx_boot_initialize_editor(p, 1) != FX_BOOT_READY) return -1;
    fx_result_reset_layout_and_flags(p);
    write_byte(p, 0x80fc, context->calculation_mode == 0x4b ? 24 : 21);
    if (context->calculation_mode == 12) fx_boot_initialize_mode12(p);
    write_byte(p, 0x80f5, 0);
    write_byte(p, 0x8129, 0);
    context->return_value = 0;
    return 0;
}
