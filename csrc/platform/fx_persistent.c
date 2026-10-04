/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_persistent.h"
#include "fx_boot.h"
#include "../complex/fx_complex.h"

static uint8_t byte_at(fx_platform *p, uint16_t address)
{
    return fx_data_read(p, 0, address);
}

static uint16_t word_at(fx_platform *p, uint16_t address)
{
    return (uint16_t)(byte_at(p, address)
           | (uint16_t)byte_at(p, (uint16_t)(address + 1u)) << 8);
}

static void put_byte(fx_platform *p, uint16_t address, uint8_t value)
{
    fx_data_write(p, 0, address, value);
}

static void clear_bytes(fx_platform *p, uint16_t first, unsigned count)
{
    for (unsigned n = 0; n < count; ++n) put_byte(p, (uint16_t)(first + n), 0);
}

static void copy_forward(fx_platform *p, uint16_t destination,
                         uint16_t source, unsigned count)
{
    for (unsigned n = 0; n < count; ++n)
        put_byte(p, (uint16_t)(destination + n), byte_at(p, (uint16_t)(source + n)));
}

/*1CDAE with digit zero: the first word uses the supplied address, then
 * EA+ advances to an even address for the remaining four words. At an odd
 * address the two stores overlap by one byte and preserve the last byte. */
void fx_number_zero_address(fx_platform *p, uint16_t address)
{
    clear_bytes(p, address, 2);
    clear_bytes(p, (uint16_t)((address + 2u) & 0xfffeu), 8);
}

void fx_result_clear(fx_platform *p) { clear_bytes(p, 0x8140, 20); }

void fx_result_clear_format(fx_platform *p)
{
    put_byte(p, 0x8100, 0);
    put_byte(p, 0x8130, 0);
}

void fx_result_clear_display_state(fx_platform *p)
{
    put_byte(p, 0x8101, 0);
    fx_result_clear_format(p);
}

void fx_result_clear_flags(fx_platform *p)
{
    put_byte(p, 0x80fe, 0);
    put_byte(p, 0x80ff, 0);
    fx_result_clear_display_state(p);
}

void fx_result_reset_layout(fx_platform *p)
{
    put_byte(p, 0x811c, 1);
    put_byte(p, 0x811d, 1);
    put_byte(p, 0x811e, 1);
}

void fx_result_reset_layout_and_flags(fx_platform *p)
{
    fx_result_reset_layout(p);
    fx_result_clear_flags(p);
}

uint8_t fx_result_format_kind(fx_platform *p) { return (uint8_t)(byte_at(p, 0x8100) >> 4); }
uint8_t fx_result_selection(fx_platform *p) { return (uint8_t)(byte_at(p, 0x8100) & 15u); }

void fx_result_set_selection(fx_platform *p, uint8_t selection)
{
    /* Native callers supply a low nibble. Preserve the full incoming byte
     * when called directly, including its OR with the prior high nibble. */
    put_byte(p, 0x8100, (uint8_t)(selection | (byte_at(p, 0x8100) & 0xf0)));
    put_byte(p, 0x8130, 0);
}

void fx_result_set_format(fx_platform *p, uint8_t format)
{
    put_byte(p, 0x8100, format);
    put_byte(p, 0x8130, 0);
}

void fx_store_variable_address(fx_platform *p, uint8_t slot, uint16_t source)
{
    unsigned offset = 10u*slot;
    copy_forward(p, (uint16_t)(0x8226 + offset), source, 10);
    if (byte_at(p, 0x80f9) == 0xc4)
        copy_forward(p, (uint16_t)(0x8408 + offset), (uint16_t)(source + 10u), 10);
}

void fx_store_ans_address(fx_platform *p, uint16_t source)
{
    fx_store_variable_address(p, 1, source);
}

void fx_store_variable_records(fx_platform *p, uint8_t slot, const fx_number values[2])
{
    unsigned offset = 10u*slot;
    fx_number real = values[0];
    for (unsigned n = 0; n < 10; ++n) put_byte(p, (uint16_t)(0x8226 + offset + n), real.bytes[n]);
    if (byte_at(p, 0x80f9) == 0xc4) {
        fx_number imaginary = values[1];
        for (unsigned n = 0; n < 10; ++n)
            put_byte(p, (uint16_t)(0x8408 + offset + n), imaginary.bytes[n]);
    }
}

void fx_store_ans_records(fx_platform *p, const fx_number values[2])
{
    fx_store_variable_records(p, 1, values);
}

uint16_t fx_replay_buffer(fx_platform *p)
{
    uint8_t mode = byte_at(p, 0x80f9);
    if (mode == 0x45 || mode == 0x4a) return 0x8406;
    if (mode == 12) return 0x84e2;
    if (mode == 0x89) return 0x829e;
    unsigned low = mode & 15u;
    return (uint16_t)(low == 3 || low >= 6 ? 0 : 0x829e);
}

int fx_replay_next(fx_platform *p, uint16_t entry, uint16_t *out_next)
{
    if (!out_next) return -1;
    *out_next = 0;
    uint16_t base = fx_replay_buffer(p);
    if (!base) return 0;
    unsigned end = base + 250u;
    if (entry < base || entry > end) return -1;
    unsigned expression = entry + 3u + (byte_at(p, entry) & 0x80 ? 20u : 10u);
    if (expression > end) return 0;
    for (unsigned address = expression; address <= end; ++address) {
        uint8_t token = byte_at(p, (uint16_t)address);
        if (!token) return 0;
        if (token == ':') {
            if (address == end) return -1;
            *out_next = (uint16_t)(address + 1u);
            return 0;
        }
    }
    return -1;
}

int fx_replay_count(fx_platform *p, uint8_t *out_count)
{
    if (!out_count) return -1;
    *out_count = 0;
    uint16_t entry = fx_replay_buffer(p);
    if (!entry) return 0;
    uint8_t mode = byte_at(p, 0x80f9);
    if ((mode == 0x45 || mode == 12) && byte_at(p, 0x80fc) != 1) return 0;
    while (entry) {
        uint16_t next;
        int status = fx_replay_next(p, entry, &next);
        if (status) return status;
        if (!next) return 0;
        ++*out_count;
        entry = next;
    }
    return 0;
}

int fx_replay_used(fx_platform *p, uint16_t entry, uint8_t *out_used)
{
    if (!out_used) return -1;
    *out_used = 0;
    uint16_t base = fx_replay_buffer(p);
    if (!base) return 0;
    if (entry < base || entry > base + 250u) return -1;
    uint16_t first = entry;
    while (entry) {
        uint16_t next;
        int status = fx_replay_next(p, entry, &next);
        if (status) return status;
        if (!next) break;
        entry = next;
    }
    *out_used = (uint8_t)(entry - first);
    return 0;
}

static int expression_span(fx_platform *p, uint16_t source,
                            int continuation, unsigned *out_length)
{
    /* Native lengths and capacity arithmetic truncate to a byte. Reject the
     * wrap/unterminated domain before any persistent replay modification. */
    for (unsigned length = 0; length < 256; ++length) {
        uint8_t token = byte_at(p, (uint16_t)(source + length));
        if (continuation && token == ':') { *out_length = length; return 0; }
        if (!token) {
            if (continuation) return -1;
            *out_length = length;
            return 0;
        }
    }
    return -1;
}

int fx_replay_append_prepared(fx_platform *p, uint8_t imaginary_classification)
{
    uint16_t base = fx_replay_buffer(p);
    if (!base) return 0;
    uint16_t source = word_at(p, 0x812c);
    unsigned result_size = imaginary_classification == 1 ? 10u : 20u;
    unsigned length;
    if (expression_span(p, source, (byte_at(p, 0x80fe) & 0x40) != 0, &length)) return -1;
    unsigned needed = result_size + length + 4u;
    if (needed > 255) return -1;
    if (needed > 250) return 0;
    uint8_t used;
    if (fx_replay_used(p, base, &used)) return -1;
    unsigned removed = 0;
    uint16_t retained = base;
    while (used + needed > 250u + removed) {
        uint16_t next;
        if (fx_replay_next(p, retained, &next) || !next) return -1;
        removed += (unsigned)(next - retained);
        retained = next;
    }
    unsigned retained_size = used - removed;
    copy_forward(p, base, retained, retained_size);
    uint16_t destination = (uint16_t)(base + retained_size);
    clear_bytes(p, destination, removed);
    /* Read live globals/source after compaction, just as the bus operations
     * do. An expression aliased into the replay store retains native order. */
    uint8_t flags = byte_at(p, 0x80ff);
    if (result_size == 20) flags |= 0x80;
    put_byte(p, destination++, flags);
    put_byte(p, destination++, byte_at(p, 0x8100));
    put_byte(p, destination++, byte_at(p, 0x8101));
    copy_forward(p, destination, 0x8140, result_size);
    destination = (uint16_t)(destination + result_size);
    copy_forward(p, destination, source, length);
    put_byte(p, (uint16_t)(destination + length), ':');
    return 0;
}

int fx_replay_append(fx_platform *p)
{
    if (!fx_replay_buffer(p)) return 0;
    fx_number imaginary;
    for (unsigned n = 0; n < 10; ++n) imaginary.bytes[n] = byte_at(p, (uint16_t)(0x814a + n));
    uint8_t classification;
    if (fx_scalar_numeric_classify(&classification, &imaginary) != FX_NUMERIC_OK) return -2;
    return fx_replay_append_prepared(p, classification);
}

int fx_replay_recall(fx_platform *p)
{
    uint16_t base = fx_replay_buffer(p);
    uint8_t selected = byte_at(p, 0x8113);
    if (!base || !selected) return 0;
    uint8_t count;
    if (fx_replay_count(p, &count) || !count || selected > count) return -1;
    uint16_t entry = base, next = 0;
    for (unsigned index = 1; index <= selected; ++index) {
        if (fx_replay_next(p, entry, &next) || !next) return -1;
        if (index < selected) entry = next;
    }
    uint8_t flags = byte_at(p, entry);
    unsigned result_size = flags & 0x80 ? 20u : 10u;
    uint16_t expression = (uint16_t)(entry + 3u + result_size);
    unsigned length = (unsigned)(next - expression - 1u);
    if (length > 99) return -1;
    uint8_t mode = byte_at(p, 0x80f9);
    uint8_t navigation = (uint8_t)(selected == 1 && (count > 1 || mode == 0x45 || mode == 12) ? 0 : 1);
    if (selected < count) navigation |= 2;
    put_byte(p, 0x8129, navigation);
    put_byte(p, 0x80fc, 1);
    put_byte(p, 0x80fd, 0);
    put_byte(p, 0x80fe, 1);
    put_byte(p, 0x80ff, 0);
    if (fx_boot_initialize_editor(p, 1) != FX_BOOT_READY) return -2;
    fx_result_set_format(p, byte_at(p, (uint16_t)(entry + 1u)));
    put_byte(p, 0x8101, byte_at(p, (uint16_t)(entry + 2u)));
    copy_forward(p, 0x8140, (uint16_t)(entry + 3u), result_size);
    if (result_size == 10) clear_bytes(p, 0x814a, 10);
    put_byte(p, 0x80fe, 0x23);
    put_byte(p, 0x80ff, (uint8_t)(flags & 0x7f));
    copy_forward(p, 0x8154, expression, length);
    put_byte(p, (uint16_t)(0x8154 + length), 0);
    if (mode == 0x45 || mode == 12) {
        uint8_t format = byte_at(p, 0x8106) && !byte_at(p, 0x810c) && (mode & 0x40) ? 13 : 0;
        fx_result_set_format(p, format);
    }
    return 0;
}
