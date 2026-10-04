/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_platform.h"

uint8_t fx_data_read(fx_platform *p, uint8_t segment, uint16_t address)
{
    size_t mapped;
    p->status = FX_MEMORY_OK;
    if (segment == 0 && address >= 0x8000u) return p->ram[address];
    if (segment == 8 || segment == 9) segment = (uint8_t)(segment - 8u);
    mapped = (size_t)segment * 0x10000u + address;
    if (mapped < p->rom_size) return p->rom[mapped];
    p->status = FX_MEMORY_UNMAPPED;
    return 0;
}

void fx_data_write(fx_platform *p, uint8_t segment, uint16_t address, uint8_t value)
{
    p->status = FX_MEMORY_OK;
    if (segment != 0 || address < 0x8000u) {
        p->status = FX_MEMORY_READ_ONLY;
        return;
    }
    p->ram[address] = value;
    if (address == 0xf000u && value != 0) p->callback_pending = value;
}

uint8_t fx_take_callback(fx_platform *p)
{
    uint8_t result = p->callback_pending;
    p->callback_pending = 0;
    return result;
}

static uint16_t read_word(fx_platform *p, uint8_t segment, uint16_t address)
{
    uint16_t low = fx_data_read(p, segment, address);
    return (uint16_t)(low | (uint16_t)fx_data_read(p, segment, (uint16_t)(address + 1u)) << 8);
}

int fx_copy_startup_data(fx_platform *p)
{
    uint16_t cursor = 0xf8d0u;
    unsigned records;
    for (records = 0; records < 8192; ++records) {
        uint16_t source = read_word(p, 1, cursor);
        uint16_t destination, size, i;
        uint8_t source_segment, destination_segment;
        if (source == 0xffffu) return 0;
        destination = read_word(p, 1, (uint16_t)(cursor + 2u));
        size = read_word(p, 1, (uint16_t)(cursor + 4u));
        source_segment = fx_data_read(p, 1, (uint16_t)(cursor + 6u));
        destination_segment = fx_data_read(p, 1, (uint16_t)(cursor + 7u));
        cursor = (uint16_t)(cursor + 8u);
        for (i = 0; i < size; ++i) {
            uint8_t value = fx_data_read(p, source_segment, (uint16_t)(source + i));
            fx_data_write(p, destination_segment, (uint16_t)(destination + i), value);
        }
    }
    return -1; /* malformed data table; not reached by this firmware image */
}

static void write_word(fx_platform *p, uint16_t address, uint16_t value)
{
    fx_data_write(p, 0, address, (uint8_t)value);
    fx_data_write(p, 0, (uint16_t)(address + 1u), (uint8_t)(value >> 8));
}

void fx_timer_start(fx_platform *p, uint16_t period)
{
    write_word(p, 0xf024, 1);
    write_word(p, 0xf022, 0);
    write_word(p, 0xf020, period);
    fx_data_write(p, 0, 0xf025, 1);
    write_word(p, 0xf014, 0);
    fx_data_write(p, 0, 0xf008, 0x50);
    fx_data_write(p, 0, 0xf008, 0xa0);
    fx_data_write(p, 0, 0xf009, 2);
}

void fx_timer_restart(fx_platform *p)
{
    fx_data_write(p, 0, 0xf014, (uint8_t)(fx_data_read(p, 0, 0xf014) & 0xfdu));
    fx_data_write(p, 0, 0xf008, 0x50);
    fx_data_write(p, 0, 0xf008, 0xa0);
    fx_data_write(p, 0, 0xf009, 2);
}

uint8_t fx_timer_flags(fx_platform *p) { return fx_data_read(p, 0, 0xf014); }

uint8_t fx_acquire_busy(fx_platform *p)
{
    if (fx_data_read(p, 0, 0x80f4) & 0x80u) return 1;
    fx_data_write(p, 0, 0x80f4, 0x88);
    return 0x88;
}

void fx_mark_busy(fx_platform *p) { fx_data_write(p, 0, 0x80f4, 0x80); }
void fx_clear_busy(fx_platform *p) { fx_data_write(p, 0, 0x80f4, 0); }
uint8_t fx_is_busy(fx_platform *p) { return (uint8_t)((fx_data_read(p, 0, 0x80f4) & 0x80u) != 0); }
uint8_t fx_secondary_busy(fx_platform *p) { return (uint8_t)((fx_data_read(p, 0, 0x80f4) & 8u) != 0); }

void fx_configure_key_port(fx_platform *p)
{
    write_word(p, 0xf048, 0);
    write_word(p, 0xf04a, 7);
    fx_data_write(p, 0, 0xf04c, 7);
}

void fx_configure_interrupt_port(fx_platform *p)
{
    write_word(p, 0xf010, 0x22);
    fx_data_write(p, 0, 0xf018, 3);
}

void fx_configure_display_port(fx_platform *p)
{
    fx_data_write(p, 0, 0xf033, 3);
    fx_data_write(p, 0, 0xf030, 0);
    fx_data_write(p, 0, 0xf034, 0);
    fx_data_write(p, 0, 0xf031, 7);
    fx_data_write(p, 0, 0xf032, 17);
}

void fx_display_port_restart(fx_platform *p)
{
    uint8_t value = (uint8_t)(fx_data_read(p, 0, 0xf031) & 0xfbu);
    fx_data_write(p, 0, 0xf031, value);
    fx_data_write(p, 0, 0xf031, (uint8_t)(value | 4u));
}

void fx_display_port_active(fx_platform *p) { fx_data_write(p, 0, 0xf031, 5); }

void fx_configure_ports(fx_platform *p)
{
    fx_data_write(p, 0, 0xf00a, 1);
    fx_data_write(p, 0, 0xf221, 5);
    fx_data_write(p, 0, 0xf222, 4);
    fx_data_write(p, 0, 0xf223, 1);
    fx_configure_display_port(p);
    fx_configure_key_port(p);
    fx_configure_interrupt_port(p);
    fx_data_write(p, 0, 0xf041, 0);
    fx_data_write(p, 0, 0xf044, 0x80);
    fx_data_write(p, 0, 0xf045, 0xff);
    fx_key_drive_disable(p);
    fx_key_deselect_all(p);
}

static void clear_bits(fx_platform *p, uint16_t address, uint8_t mask)
{
    fx_data_write(p, 0, address, (uint8_t)(fx_data_read(p, 0, address) & (uint8_t)~mask));
}

void fx_display_port_sleep(fx_platform *p)
{
    if (!(fx_data_read(p, 0, 0x80fc) & 0x10)) fx_data_write(p, 0, 0xf031, 6);
    clear_bits(p, 0xf800, 0x14);
    clear_bits(p, 0xf801, 2);
    clear_bits(p, 0xf802, 0x40);
    clear_bits(p, 0xf80b, 0x80);
    clear_bits(p, 0xf80a, 8);
    clear_bits(p, 0xf80b, 0x10);
}

void fx_set_lcd_flag(fx_platform *p, uint8_t enabled)
{
    if (enabled) fx_data_write(p, 0, 0xf80b, (uint8_t)(fx_data_read(p, 0, 0xf80b) | 0x10));
    else clear_bits(p, 0xf80b, 0x10);
}

void fx_disable_display(fx_platform *p) { fx_data_write(p, 0, 0xf033, 0); }
void fx_key_drive_enable(fx_platform *p) { fx_data_write(p, 0, 0xf042, 0xff); }
void fx_key_drive_disable(fx_platform *p) { fx_data_write(p, 0, 0xf042, 0); }
void fx_key_select_all(fx_platform *p) { fx_data_write(p, 0, 0xf046, 0x7f); }
void fx_key_deselect_all(fx_platform *p) { fx_data_write(p, 0, 0xf046, 0); }
uint8_t fx_any_key(fx_platform *p)
{
    fx_key_select_all(p);
    return (uint8_t)(fx_data_read(p, 0, 0xf040) != 0xff);
}
