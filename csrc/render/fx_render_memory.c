#include "fx_render_memory.h"

#include <string.h>

static uint8_t read_byte(const fx_render *render, uint16_t address)
{
    if (address >= 0x8000) return render->memory[address];
    return address < render->rom_size ? render->rom[address] : 0;
}

static void write_byte(fx_render *render, uint16_t address, uint8_t value)
{
    if (address >= 0x8000) render->memory[address] = value;
}

static int signed_address(uint16_t address)
{
    return address & 0x8000 ? (int)address - 65536 : address;
}

/* 0x7a60's signed overlap comparison is observable when addresses wrap.
 * Counters and pointers are explicit firmware-width integers; ROM ignores
 * writes and remains readable across the low-address boundary. */
static void move_bytes(fx_render *render, uint16_t destination,
                       uint16_t source, uint16_t length)
{
    uint16_t source_end = (uint16_t)(source + length);
    if (signed_address(source) < signed_address(destination)
        && signed_address(source_end) > signed_address(destination)) {
        source = source_end;
        destination = (uint16_t)(destination + length);
        while (length--) {
            --source;
            --destination;
            write_byte(render, destination, read_byte(render, source));
        }
    } else {
        while (length--) {
            write_byte(render, destination, read_byte(render, source));
            ++destination;
            ++source;
        }
    }
}

static void clear_bytes(fx_render *render, uint16_t address, uint16_t length)
{
    while (length--) write_byte(render, address++, 0);
}

void fx_fill_display(fx_render *render, uint8_t pattern, uint8_t selection)
{
    if (selection & 1)
        memset(render->memory + FX_RAM_FRAMEBUFFER, pattern, FX_FRAMEBUFFER_BYTES);
    if (selection & 2)
        memset(render->memory + FX_LCD_FRAMEBUFFER, pattern, 512);
}

void fx_clear_from_row(fx_render *render, uint8_t row)
{
    uint16_t offset = (uint16_t)(row * 12);
    clear_bytes(render, (uint16_t)(FX_RAM_FRAMEBUFFER + offset),
                (uint16_t)(FX_FRAMEBUFFER_BYTES - offset));
}

void fx_scroll_previous_rows(fx_render *render, uint8_t removed)
{
    uint16_t offset = (uint16_t)((uint8_t)(removed + 1) * 12);
    uint16_t retained = (uint16_t)(FX_FRAMEBUFFER_BYTES - offset);
    move_bytes(render, FX_RAM_FRAMEBUFFER + 12,
               (uint16_t)(FX_RAM_FRAMEBUFFER + offset), retained);
    clear_bytes(render, (uint16_t)(FX_RAM_FRAMEBUFFER + retained + 12),
                (uint16_t)(offset - 12));
}

void fx_make_result_space(fx_render *render, uint8_t requested_height)
{
    uint8_t previous = render->memory[0x8128] ? render->memory[0x8128] : 10;
    uint8_t total = (uint8_t)(requested_height + previous);
    if (total > 31) fx_scroll_previous_rows(render, (uint8_t)(total - 31));
    render->memory[0x8128] = 0;
}
