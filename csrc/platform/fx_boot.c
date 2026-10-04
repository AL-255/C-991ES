/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_boot.h"
#include "../ui/fx_editor.h"
#include "../render/fx_render_memory.h"
#include "../render/fx_result_special.h"

static uint8_t byte_at(fx_platform *p, uint16_t address)
{
    return fx_data_read(p, 0, address);
}

static void put_byte(fx_platform *p, uint16_t address, uint8_t value)
{
    fx_data_write(p, 0, address, value);
}

static void fill(fx_platform *p, uint16_t destination, unsigned count, uint8_t value)
{
    for (unsigned n = 0; n < count; ++n)
        put_byte(p, (uint16_t)(destination + n), value);
}

static fx_render display(fx_platform *p)
{
    fx_render render = {p->rom, p->rom_size, p->ram};
    return render;
}

void fx_boot_write_signature(fx_platform *p)
{
    for (unsigned n = 0; n < 15; ++n)
        put_byte(p, (uint16_t)(0x860e + n), (uint8_t)(15u - n));
}

uint8_t fx_boot_retained_state_invalid(fx_platform *p)
{
    for (unsigned n = 0; n < 15; ++n)
        if (byte_at(p, (uint16_t)(0x860e + n)) != 15u - n) return 1;
    uint8_t contrast = byte_at(p, 0x8112);
    if (contrast < 4 || contrast > 29) return 1;
    for (unsigned n = 0; n < 10; ++n) {
        uint16_t value = (uint16_t)(0x8226 + 10u*n);
        if ((byte_at(p, value) & 15) >= 10 || (byte_at(p, (uint16_t)(value + 9)) & 0xf0))
            return 1;
    }
    return (uint8_t)((byte_at(p, 0x80dc) & 0xf8) != 0);
}

void fx_boot_clear_expression(fx_platform *p) { fill(p, 0x8154, 100, 0); }
void fx_boot_clear_exported_input(fx_platform *p) { fill(p, 0x81b8, 100, 0); }

void fx_boot_clear_result_workspaces(fx_platform *p)
{
    uint8_t mode = byte_at(p, 0x80f9);
    put_byte(p, 0x8129, 0);
    if (mode == 0xc1 || mode == 2 || mode == 0xc4 || mode == 0x89)
        fill(p, 0x829e, 250, 0);
    fx_boot_clear_exported_input(p);
}

static void reset_layout_dimensions(fx_platform *p)
{
    put_byte(p, 0x811c, 1);
    put_byte(p, 0x811d, 1);
    put_byte(p, 0x811e, 1);
}

static void reset_layout_flags(fx_platform *p)
{
    reset_layout_dimensions(p);
    put_byte(p, 0x80fe, 0);
    put_byte(p, 0x80ff, 0);
    put_byte(p, 0x8101, 0);
    put_byte(p, 0x8100, 0);
    put_byte(p, 0x8130, 0);
}

static fx_boot_status default_result_line(fx_platform *p)
{
    uint8_t mode = byte_at(p, 0x80f9);
    if (mode == 0x88 && byte_at(p, 0x80fc) == 1) return FX_BOOT_READY;
    if (mode == 0x89) {
        /* 802a joins the active labels named by the startup pointer table.
         * Its native local buffer is sixteen bytes; oversized labels are
         * rejected here instead of corrupting the firmware call stack. */
        uint8_t label[16];
        size_t length = 0;
        uint16_t first = (uint16_t)(byte_at(p, 0x8df4) | (uint16_t)byte_at(p, 0x8df5) << 8);
        uint16_t second = (uint16_t)(byte_at(p, 0x8df2) | (uint16_t)byte_at(p, 0x8df3) << 8);
        if (first) {
            while (byte_at(p, first)) {
                if (length == sizeof label - 1) return FX_BOOT_MALFORMED;
                label[length++] = byte_at(p, first++);
            }
        }
        if (length == sizeof label - 1) return FX_BOOT_MALFORMED;
        label[length++] = byte_at(p, 0x31b9);
        if (second) {
            while (byte_at(p, second)) {
                if (length == sizeof label - 1) return FX_BOOT_MALFORMED;
                label[length++] = byte_at(p, second++);
            }
        } else length = 0;
        fx_render render = display(p);
        uint8_t x = (uint8_t)(96u - 6u*length);
        unsigned advance = byte_at(p, 0x811f) == 6 ? 4 : 6;
        unsigned maximum = byte_at(p, 0x811f) == 6 ? 24 : 16;
        for (unsigned n = 0; n < length && n < maximum && x <= 96u - advance; ++n) {
            fx_draw_glyph(&render, x, 22, label[n]);
            x = (uint8_t)(x + advance);
        }
        return FX_BOOT_READY;
    }
    if (fx_editor_has_natural_input(p)) return FX_BOOT_READY;
    fx_render render = display(p);
    const fx_number zero = {{0}};
    int status = fx_display_special_real_number(&render, &zero, NULL);
    return status == 1 ? FX_BOOT_READY : FX_BOOT_UNIMPLEMENTED;
}

fx_boot_status fx_boot_initialize_editor(fx_platform *p, uint8_t action)
{
    fx_render render = display(p);
    put_byte(p, 0x8124, 0);
    put_byte(p, 0x80fe, 1);
    put_byte(p, 0x80ff, 0);
    if (!(action & 0x80)) {
        fx_boot_clear_expression(p);
        put_byte(p, 0x8114, 0);
    }
    uint8_t selection = action & 15;
    put_byte(p, 0x8116, 0);
    put_byte(p, 0x8117, 1);
    put_byte(p, 0x811f, 10);
    if (!(byte_at(p, 0x80fc) & 0x10)) {
        if (selection) fx_clear_framebuffer(&render);
    } else {
        put_byte(p, 0x811f, 7);
        put_byte(p, 0x8117, 25);
        uint16_t label = 0x11a1;
        fx_draw_text(&render, 0, 25, &label);
    }
    put_byte(p, 0x8118, 0);
    put_byte(p, 0x8119, 1);
    if (fx_editor_refresh_cursor(p)) return FX_BOOT_MALFORMED;
    put_byte(p, 0x811b, byte_at(p, 0x811f));
    put_byte(p, 0x8101, 0);
    put_byte(p, 0x8100, 0);
    put_byte(p, 0x8130, 0);
    put_byte(p, 0x8128, 0);
    put_byte(p, 0x8127, 0);
    put_byte(p, 0x812c, 0x54);
    put_byte(p, 0x812d, 0x81);
    return selection == 2 ? default_result_line(p) : FX_BOOT_READY;
}

fx_boot_status fx_boot_reset_settings(fx_platform *p)
{
    fx_boot_clear_expression(p);
    fx_boot_clear_result_workspaces(p);
    for (unsigned n = 0; n < 13; ++n)
        put_byte(p, (uint16_t)(0x8102 + n), fx_data_read(p, 1, (uint16_t)(0xffd0 + n)));
    put_byte(p, 0x80f9, 0xc1);
    put_byte(p, 0x80fa, 0);
    put_byte(p, 0x80fb, 3);
    put_byte(p, 0x80fc, 1);
    return fx_boot_initialize_editor(p, 2);
}

fx_boot_status fx_boot_cold_reset(fx_platform *p)
{
    fill(p, 0x8000, 0x0a17, 0);
    put_byte(p, 0x8112, 17);
    put_byte(p, 0xf032, 17);
    put_byte(p, 0x8121, 1);
    put_byte(p, 0x80dc, byte_at(p, 0xf050));
    fx_boot_status status = fx_boot_reset_settings(p);
    if (status != FX_BOOT_READY) return status;
    fx_boot_write_signature(p);
    return FX_BOOT_READY;
}

fx_boot_status fx_boot_default_screen(fx_platform *p)
{
    put_byte(p, 0x80fc, 1);
    put_byte(p, 0x80f4, 0);
    put_byte(p, 0x80f5, 0xe6);
    put_byte(p, 0x80f7, 1);
    put_byte(p, 0x812a, 0);
    put_byte(p, 0x8129, 0);
    put_byte(p, 0x80f8, (uint8_t)(byte_at(p, 0x80f8) & 0x80));
    put_byte(p, 0x8120, 0);
    put_byte(p, 0x8121, 1);
    put_byte(p, 0x80dc, byte_at(p, 0xf050));
    put_byte(p, 0x80fb, 0);
    put_byte(p, 0xf032, byte_at(p, 0x8112));
    reset_layout_flags(p);
    fx_boot_status status = fx_boot_initialize_editor(p, 2);
    if (status != FX_BOOT_READY) return status;
    fx_boot_clear_result_workspaces(p);
    if (byte_at(p, 0x80f9) == 0x88) {
        put_byte(p, 0x8138, 0);
        fill(p, 0x85aa, 100, 0);
    }
    fx_render render = display(p);
    fx_flush_framebuffer(&render);
    return FX_BOOT_READY;
}

uint8_t fx_boot_probe_welcome_key(fx_platform *p)
{
    put_byte(p, 0xf046, 1);
    uint8_t remaining = 5;
    while (remaining && byte_at(p, 0xf040) == 0x7b) --remaining;
    if (!remaining) {
        put_byte(p, 0x80f2, 0x80);
        put_byte(p, 0x80f3, 1);
    }
    fx_key_deselect_all(p);
    return remaining;
}

fx_boot_status fx_boot_initialize(fx_platform *p)
{
    fill(p, 0x8a18, 0x320, 0x5a);
    fx_configure_ports(p);
    fx_timer_start(p, 0x03b8);
    put_byte(p, 0x80dd, 0);
    return fx_boot_retained_state_invalid(p) ? fx_boot_cold_reset(p) : FX_BOOT_READY;
}

void fx_boot_initialize_mode12(fx_platform *p)
{
    put_byte(p, 0x8101, 0);
    put_byte(p, 0x8100, 0);
    put_byte(p, 0x8130, 0);
    if (byte_at(p, 0x8137)) {
        reset_layout_dimensions(p);
        put_byte(p, 0x80fc, 18);
        put_byte(p, 0x80fd, 0);
        put_byte(p, 0x80fe, 0);
    } else {
        put_byte(p, 0x80fc, 9);
        put_byte(p, 0x80fd, 0);
        put_byte(p, 0x80fe, 4);
    }
}

fx_boot_status fx_boot_resume(fx_platform *p)
{
    fx_boot_status status = fx_boot_default_screen(p);
    if (status != FX_BOOT_READY) return status;
    fx_disable_display(p);
    fx_display_port_active(p);
    unsigned sample;
    for (sample = 0; sample < 3; ++sample) {
        uint8_t keys = byte_at(p, 0xf040);
        if (!keys || (keys & 0x18)) break;
    }
    if (sample == 3) return FX_BOOT_DIAGNOSTIC;
    if (!fx_boot_probe_welcome_key(p)) return FX_BOOT_WELCOME;
    uint8_t mode = byte_at(p, 0x80f9);
    fx_render render = display(p);
    if (mode == 0x45 || mode == 0x4b || mode == 0x4a) {
        put_byte(p, 0x80fe, 0);
        put_byte(p, 0x80f5, 0);
        fx_fill_display(&render, 0, 2);
        put_byte(p, 0x80fc, (uint8_t)(mode == 0x45 ? 21 : mode == 0x4b ? 24 : 23));
    }
    if (mode == 12) {
        put_byte(p, 0x80f5, 0);
        fx_fill_display(&render, 0, 2);
        fx_boot_initialize_mode12(p);
    }
    return FX_BOOT_READY;
}

fx_boot_status fx_boot_prepare_power_off(fx_platform *p)
{
    if (byte_at(p, 0x80dd)) return FX_BOOT_READY;
    fx_render render = display(p);
    fx_clear_framebuffer(&render);
    for (unsigned n = 0; n < 156; ++n)
        put_byte(p, (uint16_t)(0x8848 + n), fx_data_read(p, 0, (uint16_t)(0x2db4 + n)));
    fx_flush_framebuffer(&render);
    fx_timer_start(p, 5000);
    put_byte(p, 0xf031, 3);
    put_byte(p, 0xf00a, 0);
    put_byte(p, 0xf010, 0);
    put_byte(p, 0xf011, 0);
    fx_key_drive_disable(p);
    fx_key_deselect_all(p);
    put_byte(p, 0xf008, 0x50);
    put_byte(p, 0xf008, 0xa0);
    put_byte(p, 0xf009, 2);
    return FX_BOOT_RESTART;
}

fx_boot_status fx_boot_reset(fx_platform *p)
{
    if (fx_copy_startup_data(p)) return FX_BOOT_MALFORMED;
    put_byte(p, 0xf000, 0);
    fx_boot_status status = fx_boot_initialize(p);
    return status == FX_BOOT_READY ? fx_boot_resume(p) : status;
}
