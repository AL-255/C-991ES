/* Physical terminal reference cleanup; no ROM execution. GPL-3.0-only. */
#include "fx_eval_finish.h"
#include <string.h>

static int valid(const fx_eval_storage *storage)
{
    return storage && storage->ram && storage->ram_size == 65536u;
}

static int overlaps_ram(const fx_eval_storage *storage, const void *object,
                        size_t size)
{
    uintptr_t address = (uintptr_t)object, base = (uintptr_t)storage->ram;
    if (address >= base) return address - base < 65536u;
    return base - address < size;
}

static void publish_error(fx_eval_storage *storage, fx_number *current,
                          uint16_t address, int physical, uint8_t status)
{
    unsigned word;
    if (!physical) {
        fx_number_error(current, status);
        return;
    }
    /* CDE4 writes five words. After the first odd-address transfer, EA+
     * advances to an even address, so the final record byte is retained. */
    for (word = 0; word < 5; ++word) {
        storage->ram[address] = word ? 0 : (uint8_t)(0xf0u | status);
        storage->ram[address + 1u] = 0;
        address = (uint16_t)((address + 2u) & 0xfffeu);
    }
}

static fx_numeric_status cleanup(fx_eval_storage *storage, fx_number *current,
    uint16_t address, int physical, uint8_t *native_status)
{
    uint8_t header = physical ? storage->ram[address] : current->bytes[0];
    unsigned identity = header & 15u, kind = header >> 4;
    unsigned row, column, rows, columns, base;
    *native_status = 0;
    if (kind != 6 && kind != 9) {
        *native_status = 3;
        publish_error(storage, current, address, physical, *native_status);
        return FX_NUMERIC_OK;
    }
    rows = storage->ram[0x80e0u + 2u * identity];
    columns = storage->ram[0x80e1u + 2u * identity];
    if (!rows || !columns) {
        *native_status = 9;
        publish_error(storage, current, address, physical, *native_status);
        return FX_NUMERIC_OK;
    }
    base = 0x829eu + 90u * identity;
    for (row = 0; row < rows; ++row) for (column = 0; column < columns; ++column) {
        unsigned index = (3u * row + column) & 255u;
        unsigned cell = base + 10u * index;
        fx_number value;
        fx_numeric_status status;
        unsigned decimal_header;
        if (cell + 10u > 0x883eu) return FX_NUMERIC_UNIMPLEMENTED;
        memcpy(value.bytes, storage->ram + cell, sizeof value.bytes);
        decimal_header = value.bytes[0] & 0xf0u;
        if ((decimal_header == 0 || decimal_header == 0x40u) &&
            (value.bytes[0] & 15u) > 9u) return FX_NUMERIC_UNIMPLEMENTED;
        status = fx_decimal_integer_cleanup(&value);
        if (status != FX_NUMERIC_OK) return FX_NUMERIC_UNIMPLEMENTED;
        memcpy(storage->ram + cell, value.bytes, sizeof value.bytes);
        if (value.bytes[0] >= 0xf0u && (value.bytes[0] & 15u)) {
            *native_status = value.bytes[0] & 15u;
            publish_error(storage, current, address, physical, *native_status);
            return FX_NUMERIC_OK;
        }
    }
    return FX_NUMERIC_OK;
}

fx_numeric_status fx_eval_finish_cleanup(fx_eval_storage *storage,
    fx_number *current, uint8_t *native_status)
{
    uintptr_t record, status;
    if (!valid(storage) || !current || !native_status) return FX_NUMERIC_INVALID;
    record = (uintptr_t)current; status = (uintptr_t)native_status;
    if (overlaps_ram(storage, current, sizeof *current) ||
        overlaps_ram(storage, native_status, sizeof *native_status) ||
        (status >= record && status - record < sizeof *current))
        return FX_NUMERIC_INVALID;
    return cleanup(storage, current, 0, 0, native_status);
}

fx_numeric_status fx_eval_finish_cleanup_address(fx_eval_storage *storage,
    uint16_t current, uint8_t *native_status)
{
    if (!valid(storage) || !native_status ||
        overlaps_ram(storage, native_status, sizeof *native_status))
        return FX_NUMERIC_INVALID;
    if (current < 0x80dcu || current > 65526u ||
        (current < 0x8deeu && (unsigned)current + 10u > 0x8d00u))
        return FX_NUMERIC_UNIMPLEMENTED;
    return cleanup(storage, NULL, current, 1, native_status);
}
