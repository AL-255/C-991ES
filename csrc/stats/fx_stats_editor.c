/* Readable statistics table editing. GPL-3.0-or-later.
 * Uses the data bus only; no CPU registers, stack emulation or ROM execution. */
#include "fx_stats_editor.h"

enum {
    TABLE_BASE = 0x82ee, ROW_COUNT = 0x80de, RESERVED_COUNT = 0x80df,
    MODE = 0x80f9, MODEL = 0x80fa, FREQUENCY = 0x8109,
    TOP_ROW = 0x811c, SCREEN_ROW = 0x811d, COLUMN = 0x811e,
    CACHE_VALID = 0x812a
};

static int valid(const fx_platform *platform) { return platform && platform->ram; }
static uint8_t read_byte(fx_platform *platform, uint16_t address)
{ return fx_data_read(platform, 0, address); }
static void write_byte(fx_platform *platform, uint16_t address, uint8_t value)
{ fx_data_write(platform, 0, address, value); }
static uint16_t read_word(fx_platform *platform, uint16_t address)
{
    uint16_t low = read_byte(platform, address);
    return (uint16_t)(low | (uint16_t)read_byte(platform, (uint16_t)(address + 1)) << 8);
}
static void write_word(fx_platform *platform, uint16_t address, uint16_t value)
{
    write_byte(platform, address, (uint8_t)value);
    write_byte(platform, (uint16_t)(address + 1), (uint8_t)(value >> 8));
}
static void clear_bytes(fx_platform *platform, uint16_t address, uint16_t count)
{
    while (count--) write_byte(platform, address++, 0);
}
static void copy_forward(fx_platform *platform, uint16_t destination,
                         uint16_t source, uint16_t count)
{
    while (count--) write_byte(platform, destination++, read_byte(platform, source++));
}
static void copy_backward(fx_platform *platform, uint16_t destination,
                          uint16_t source, uint16_t count)
{
    destination = (uint16_t)(destination + count);
    source = (uint16_t)(source + count);
    while (count--) write_byte(platform, --destination, read_byte(platform, --source));
}
static void copy_record_words(fx_platform *platform, uint16_t destination,
                              uint16_t source)
{
    int offset;
    for (offset = 8; offset >= 0; offset -= 2) {
        uint16_t value = read_word(platform, (uint16_t)(source + offset));
        write_word(platform, (uint16_t)(destination + offset), value);
    }
}

uint8_t fx_stats_editor_columns(fx_platform *platform)
{
    uint8_t mode, columns;
    if (!valid(platform)) return 0;
    mode = read_byte(platform, MODE);
    if (mode == 12) return 2;
    if (mode == 0x88)
        return read_byte(platform, 0x810e) && !(read_byte(platform, 0x8138) & 0x80) ? 3 : 2;
    columns = read_byte(platform, MODEL) == 1 ? 1 : 2;
    return (uint8_t)(columns + (read_byte(platform, FREQUENCY) != 0));
}

/* Provider50E2 snapshots the row count before writing the base address. */
static uint16_t table_region(fx_platform *platform, uint8_t selector, uint8_t *rows)
{
    uint16_t base = TABLE_BASE;
    *rows = read_byte(platform, ROW_COUNT);
    if (selector == 3) {
        base = (uint16_t)(base + 10u * (uint8_t)(*rows * fx_stats_editor_columns(platform)));
        *rows = read_byte(platform, RESERVED_COUNT);
    }
    return base;
}
static uint16_t cell_offset(fx_platform *platform, uint8_t selector, uint8_t row)
{
    unsigned columns = selector == 3 ? 1 : fx_stats_editor_columns(platform);
    /* The native row-to-record index narrows to a byte before the second
     * multiplication by record width. Raw row0 therefore differs by width. */
    uint16_t offset = (uint16_t)(10u * (uint8_t)((uint8_t)(row - 1) * columns));
    if (selector != 3) {
        if (read_byte(platform, MODEL) == 1 && selector == 2) selector = 1;
        offset = (uint16_t)(offset + 10u * selector);
    }
    return offset;
}
static int locate_raw(fx_platform *platform, uint8_t selector, uint8_t row,
                       uint16_t *address)
{
    uint8_t rows;
    uint16_t base = table_region(platform, selector, &rows);
    if (rows < row) { *address = 0; return 2; }
    *address = (uint16_t)(base + cell_offset(platform, selector, row));
    return 0;
}

int fx_stats_editor_address_raw(fx_platform *platform, uint8_t selector,
                                uint8_t row, uint16_t output_address)
{
    uint8_t rows;
    uint16_t base, offset;
    if (!valid(platform)) return -1;
    base = table_region(platform, selector, &rows);
    write_word(platform, output_address, base);
    if (rows < row) { write_word(platform, output_address, 0); return 2; }
    /* The original output pointer can alias MODEL/FREQUENCY. Geometry is
     * deliberately read after the provider's first write, then the current
     * bus output word is used rather than the old local base. */
    offset = cell_offset(platform, selector, row);
    write_word(platform, output_address,
                (uint16_t)(read_word(platform, output_address) + offset));
    return 0;
}

int fx_stats_editor_address_checked(fx_platform *platform, uint8_t column,
                                    uint8_t row, uint16_t *address)
{
    uint8_t selector;
    if (!valid(platform) || !address || read_byte(platform, MODE) != 3) return -1;
    if (!row || !column || column > fx_stats_editor_columns(platform) ||
        row > read_byte(platform, ROW_COUNT)) { *address = 0; return 2; }
    selector = (uint8_t)(column - 1);
    if (read_byte(platform, MODEL) == 1 && selector == 1) selector = 2;
    return locate_raw(platform, selector, row, address);
}

int fx_stats_editor_write_raw(fx_platform *platform, uint8_t selector,
                              uint8_t row, uint16_t source_address)
{
    uint16_t destination;
    int status;
    if (!valid(platform)) return -1;
    status = locate_raw(platform, selector, row, &destination);
    if (!status) copy_record_words(platform, destination, source_address);
    return status;
}
int fx_stats_editor_read_raw(fx_platform *platform, uint8_t selector,
                             uint8_t row, uint16_t destination_address)
{
    uint16_t source;
    int status;
    if (!valid(platform)) return -1;
    status = locate_raw(platform, selector, row, &source);
    if (!status) copy_record_words(platform, destination_address, source);
    return status;
}

static unsigned capacity(fx_platform *platform)
{
    uint8_t mode = read_byte(platform, MODE);
    if (mode == 3 && read_byte(platform, MODEL) == 1) return 40;
    return mode == 12 ? 50 : 80;
}

int fx_stats_editor_insert(fx_platform *platform, uint8_t row)
{
    unsigned columns, rows, reserved, width;
    uint16_t position, end;
    int available;
    if (!valid(platform)) return -1;
    columns = fx_stats_editor_columns(platform);
    rows = read_byte(platform, ROW_COUNT);
    reserved = read_byte(platform, RESERVED_COUNT);
    available = (int)capacity(platform) - (int)(rows * columns + reserved);
    if (available < (int)columns) return 1;
    if (!row || row > rows + 1) return 2;
    width = 10u * columns;
    position = (uint16_t)(TABLE_BASE + (row - 1u) * width);
    end = (uint16_t)(TABLE_BASE + 10u * (rows * columns + reserved));
    write_byte(platform, ROW_COUNT, (uint8_t)(rows + 1));
    copy_backward(platform, (uint16_t)(position + width), position,
                   (uint16_t)(end - position));
    clear_bytes(platform, position, (uint16_t)width);
    if (read_byte(platform, FREQUENCY)) {
        uint16_t frequency;
        if (!locate_raw(platform, 2, row, &frequency)) {
            clear_bytes(platform, frequency, 10);
            write_byte(platform, frequency, 1);
            write_byte(platform, (uint16_t)(frequency + 9), 1);
        }
    }
    return 0;
}

int fx_stats_editor_delete(fx_platform *platform, uint8_t row)
{
    unsigned columns, rows, reserved, width;
    uint16_t position, end;
    if (!valid(platform)) return -1;
    rows = read_byte(platform, ROW_COUNT);
    if (!row || row > rows) return 2;
    columns = fx_stats_editor_columns(platform);
    reserved = read_byte(platform, RESERVED_COUNT);
    width = 10u * columns;
    position = (uint16_t)(TABLE_BASE + (row - 1u) * width);
    end = (uint16_t)(TABLE_BASE + 10u * (rows * columns + reserved));
    copy_forward(platform, position, (uint16_t)(position + width),
                  (uint16_t)(end - position - width));
    clear_bytes(platform, (uint16_t)(end - width), (uint16_t)width);
    write_byte(platform, ROW_COUNT, (uint8_t)(rows - 1));
    return 0;
}

int fx_stats_editor_clear(fx_platform *platform)
{
    uint8_t mode;
    if (!valid(platform)) return -1;
    mode = read_byte(platform, MODE);
    if (mode != 3) return mode;
    write_byte(platform, ROW_COUNT, 0);
    write_byte(platform, RESERVED_COUNT, 0);
    write_byte(platform, TOP_ROW, 1);
    write_byte(platform, SCREEN_ROW, 1);
    write_byte(platform, COLUMN, 1);
    clear_bytes(platform, TABLE_BASE, 800);
    write_byte(platform, CACHE_VALID, 0);
    return 0;
}

/* 51AA clears the pending input flags after a handled cursor action. A
 * handled action may end at its starting position and still clears them. */
static void clear_input_flags(fx_platform *platform)
{
    write_byte(platform, 0x8101, 0);
    write_byte(platform, 0x8100, 0);
    write_byte(platform, 0x8130, 0);
}

int fx_stats_editor_move(fx_platform *platform, uint8_t key)
{
    uint8_t columns, rows, used, remaining, limit, top, screen, column;
    int handled = 0;
    if (!valid(platform)) return -1;
    columns = fx_stats_editor_columns(platform);
    rows = read_byte(platform, ROW_COUNT);
    used = (uint8_t)(rows * columns + read_byte(platform, RESERVED_COUNT));
    remaining = (uint8_t)(capacity(platform) - used);
    limit = (uint8_t)(rows - (remaining < columns));
    top = read_byte(platform, TOP_ROW);
    screen = read_byte(platform, SCREEN_ROW);
    column = read_byte(platform, COLUMN);
    switch (key) {
    case 0xe0:
        if (screen == 1) {
            if (top >= 2) write_byte(platform, TOP_ROW, (uint8_t)(top - 1));
            else if (limit < 3) write_byte(platform, SCREEN_ROW, (uint8_t)(limit + 1));
            else {
                write_byte(platform, SCREEN_ROW, 3);
                write_byte(platform, TOP_ROW, (uint8_t)(limit - 1));
            }
            handled = 1;
        } else if (screen > 1) {
            write_byte(platform, SCREEN_ROW, (uint8_t)(screen - 1)); handled = 1;
        }
        break;
    case 0xe1:
    case 0xed:
        if ((unsigned)top + screen > (unsigned)limit + 1) {
            if (key == 0xed) break;
            write_byte(platform, TOP_ROW, 1);
            write_byte(platform, SCREEN_ROW, 1); handled = 1;
        } else if (screen == 3) {
            /* The limit-minus-two comparison is signed sixteen-bit, so a
             * negative threshold does not wrap into a valid top row. */
            if ((int)top <= (int)limit - 2) {
                write_byte(platform, TOP_ROW, (uint8_t)(top + 1)); handled = 1;
            }
        } else {
            write_byte(platform, SCREEN_ROW, (uint8_t)(screen + 1)); handled = 1;
        }
        break;
    case 0xe2:
        if (read_byte(platform, MODE) == 12 && read_byte(platform, 0x80fe) != 5) break;
        if (column < columns) {
            write_byte(platform, COLUMN, (uint8_t)(column + 1)); handled = 1;
        }
        break;
    case 0xe3:
        if (column > 1) {
            write_byte(platform, COLUMN, (uint8_t)(column - 1)); handled = 1;
        }
        break;
    default: break;
    }
    if (handled) clear_input_flags(platform);
    return handled ? 0 : 1;
}

int fx_stats_editor_commit(fx_platform *platform, uint16_t input_address)
{
    uint8_t row, selector;
    if (!valid(platform) || read_byte(platform, MODE) != 3 ||
        read_byte(platform, 0x80fc) != 18) return -1;
    clear_input_flags(platform);
    row = (uint8_t)(read_byte(platform, TOP_ROW) + read_byte(platform, SCREEN_ROW) - 1);
    if (row > read_byte(platform, ROW_COUNT)) (void)fx_stats_editor_insert(platform, row);
    selector = (uint8_t)(read_byte(platform, COLUMN) - 1);
    if (read_byte(platform, MODEL) == 1 && selector == 1) selector = 2;
    (void)fx_stats_editor_write_raw(platform, selector, row, input_address);
    (void)fx_stats_editor_move(platform, 0xed);
    write_byte(platform, CACHE_VALID, 0);
    write_byte(platform, 0x80fe, 3);
    return 3;
}
