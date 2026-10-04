/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_stats_value.h"
#include "fx_stats.h"
#include <string.h>

int fx_stats_mean_y_prepared(fx_number *out, const uint8_t *ram, size_t ram_size)
{
    fx_number cells[255 * 3];
    fx_stats_table table = {cells, 0, 2, 0};
    unsigned columns, frequency_field, width;
    if (!out || !ram || ram_size != 65536u) return FX_NUMERIC_INVALID;
    table.rows = ram[0x80de];
    table.frequency = ram[0x8109] != 0;
    /*05110 chooses physical row width. Y remains field1 even when80FA
     * selects one variable; frequency field2 is remapped to1 only there. */
    if (ram[0x80f9] == 12) columns = 2;
    else if (ram[0x80f9] == 0x88)
        columns = ram[0x810e] && !(ram[0x8138] & 0x80) ? 3u : 2u;
    else columns = (ram[0x80fa] == 1 ? 1u : 2u) + table.frequency;
    width = 2u + table.frequency;
    frequency_field = ram[0x80fa] == 1 ? 1u : 2u;
    for (unsigned row = 0; row < table.rows; ++row) {
        size_t address = 0x82eeu + 10u * columns * row;
        fx_number_zero(&cells[width * row]);
        memcpy(cells[width * row + 1].bytes, ram + address + 10, 10);
        if (table.frequency)
            memcpy(cells[width * row + 2].bytes,
                   ram + address + 10u * frequency_field, 10);
    }
    int status = fx_stats_mean(out, &table, 1);
    if (status < 0) return FX_NUMERIC_UNIMPLEMENTED;
    if (fx_decimal_integer_cleanup(out) != FX_NUMERIC_OK)
        return FX_NUMERIC_UNIMPLEMENTED;
    return out->bytes[0] >= 0xf0 ? out->bytes[0] & 15 : 0;
}

int fx_stats_higher_x_prepared(fx_number *out, const uint8_t *ram,
                             size_t ram_size, unsigned power)
{
    fx_number cells[255 * 2], cubes, fourths;
    fx_stats_table table = {cells, 0, 1, 0};
    unsigned columns, frequency_field, width;
    if (!out || !ram || ram_size != 65536u || (power != 3 && power != 4))
        return FX_NUMERIC_INVALID;
    table.rows = ram[0x80de];
    table.frequency = ram[0x8109] != 0;
    if (ram[0x80f9] == 12) columns = 2;
    else if (ram[0x80f9] == 0x88)
        columns = ram[0x810e] && !(ram[0x8138] & 0x80) ? 3u : 2u;
    else columns = (ram[0x80fa] == 1 ? 1u : 2u) + table.frequency;
    width = 1u + table.frequency;
    frequency_field = ram[0x80fa] == 1 ? 1u : 2u;
    for (unsigned row = 0; row < table.rows; ++row) {
        size_t address = 0x82eeu + 10u * columns * row;
        memcpy(cells[width * row].bytes, ram + address, 10);
        if (table.frequency)
            memcpy(cells[width * row + 1].bytes,
                   ram + address + 10u * frequency_field, 10);
    }
    int status = fx_stats_higher_moments(&cubes, &fourths, &table, NULL);
    if (status < 0) return FX_NUMERIC_UNIMPLEMENTED;
    *out = power == 3 ? cubes : fourths;
    if (fx_decimal_integer_cleanup(out) != FX_NUMERIC_OK)
        return FX_NUMERIC_UNIMPLEMENTED;
    return out->bytes[0] >= 0xf0 ? out->bytes[0] & 15 : 0;
}
