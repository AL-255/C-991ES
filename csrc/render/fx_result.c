#include "fx_render.h"
#include "fx_render_context.h"
#include "fx_result_format_state.h"
#include "../format/fx_format.h"

#include <string.h>

static uint16_t word_at(const fx_render *r, uint16_t address)
{
    return (uint16_t)(r->memory[address] | ((uint16_t)r->memory[(uint16_t)(address + 1)] << 8));
}

static void store_word(fx_render *r, uint16_t address, uint16_t value)
{
    r->memory[address] = (uint8_t)value;
    r->memory[(uint16_t)(address + 1)] = (uint8_t)(value >> 8);
}

/* 0x3374 uses the raw-character alphabet when B070 sets 8127. The
 * portable formatter produces its normal token alphabet; adapt its scientific
 * suffix here, where the controller has resolved that firmware state. */
static void raw_scientific_suffixes(uint8_t *tokens, size_t length)
{
    for (size_t n = 0; n + 2 < length; ++n) {
        if (tokens[n] != 0x90 || (tokens[n + 1] != 0x91 && tokens[n + 1] != 0x92))
            continue;
        tokens[n] += 80;
        tokens[++n] += 80;
        while (n + 1 < length && tokens[n + 1] >= 0xa0 && tokens[n + 1] <= 0xaf)
            tokens[++n] += 80;
    }
}

static unsigned token_kind(const fx_render *r, uint16_t pointer)
{
    uint8_t token = r->memory[pointer];
    unsigned kind = fx_construct_class(r, token);
    if (kind == 1) {
        uint8_t next = r->memory[(uint16_t)(pointer + 1)];
        if (next != 0xb8 && next != 0xbb && next != 0xbd)
            kind = token == 0xae || token == 0x7c ? 13 : 10;
    }
    if (kind == 3 && r->memory[(uint16_t)(pointer + 1)] == 0xb8) kind = 4;
    return kind;
}

/* The A14E close-delimiter query, restricted here to formatter-created
 * well-formed tokens. Return the owning construct's first byte. */
static uint16_t owning_construct(const fx_render *r, uint16_t pointer, uint16_t first)
{
    if (r->memory[pointer] == 0xbc) --pointer;
    if (r->memory[pointer] != 0xb9) return 0;
    unsigned depth = 1;
    while (pointer != first) {
        uint8_t token = r->memory[--pointer];
        if (token == 0xb9) ++depth;
        else if (token == 0xb8 && !--depth) {
            if (pointer == first) return 0;
            --pointer;
            if (r->memory[pointer] == 0xb9) { depth = 1; continue; }
            if (r->memory[pointer] == 0xbb) --pointer;
            if (r->memory[pointer] == 0xbd) --pointer;
            return pointer;
        }
    }
    return 0;
}

/* 0xAFE2 encodes construct boundaries for the history-text record. */
static void flatten_history(fx_render *r, uint16_t first)
{
    uint16_t source = first, destination = 0x9838;
    /* The original do-while copies an empty source's first NUL and then
     * writes another terminator. Preserve those dormant history bytes. */
    for (unsigned n = 0; n < 65535; ++n, ++source) {
        unsigned kind = token_kind(r, source);
        uint8_t token = r->memory[source];
        if (kind == 1 || kind == 3) {
            r->memory[destination++] = 127;
            uint16_t opening = kind == 1 ? source : owning_construct(r, source, first);
            uint8_t construct = opening ? r->memory[opening] : 0;
            if (construct == 0x5e) r->memory[destination++] = kind == 1 ? 90 : 91;
            if (construct == 0xa4) r->memory[destination++] = kind == 1 ? 115 : 116;
            if (kind == 1) ++source;
        } else {
            r->memory[destination++] = token >= 224 ? (uint8_t)(token + 176) : token;
        }
        if (!r->memory[(uint16_t)(source + 1)]) break;
    }
    r->memory[destination] = 0;
}

/* 0xAF5A and its 796E header constructor. Its descriptor points to the
 * fixed 9800 history record in ordinary B070 contexts. */
static void result_history(fx_render *r, uint16_t tokens, unsigned selection)
{
    r->memory[0x9838] = 0;
    if (selection > 13) flatten_history(r, tokens);
    memset(r->memory + 0x9804, 0, 48);
    r->memory[0x9804] = 17;
    r->memory[0x9805] = 255;
    r->memory[0x9807] = 48;
    for (unsigned n = 0; n < 4; ++n) r->memory[0x9808 + n] = 255;
    uint8_t angle = r->memory[0x8105];
    r->memory[0x980d] = angle >= 4 && angle <= 6 ? (uint8_t)(angle - 3) : 0;
    for (unsigned n = 0; n < 4; ++n)
        r->memory[0x980e + n + (n == 3)] = (r->memory[0x80f8] >> (n == 0 ? 7 : n == 1 ? 3 : n == 2 ? 2 : 1)) & 1;
    r->memory[0x9813] = r->memory[0x80f8] & 1;
    if (!r->memory[0x80dd] && !r->memory[0x80fb] && r->memory[0x80fe] == 1) {
        r->memory[0x9808] = 0;
        r->memory[0x9809] = r->memory[0x8118];
        r->memory[0x980a] = 0;
        r->memory[0x980b] = r->memory[0x8119];
        r->memory[0x980c] = (uint8_t)(r->memory[0x811b] | (r->memory[0x811a] == 204 ? 128 : 0));
    }
    unsigned length = 1;
    while (r->memory[(uint16_t)(0x9838 + length - 1)] && length < 65535) ++length;
    unsigned record_length = length;
    if (length > 1) {
        record_length += 4;
        r->memory[0x9834] = 34;
        r->memory[0x9835] = 255;
        r->memory[0x9836] = (uint8_t)(record_length >> 8);
        r->memory[0x9837] = (uint8_t)record_length;
    } else r->memory[0x9834] = 0;
    unsigned full_length = (record_length + 48) & 65535;
    static const uint8_t hexadecimal[] = "0123456789ABCDEF";
    for (unsigned n = 0; n < 4; ++n)
        r->memory[0x9800 + n] = hexadecimal[(full_length >> (12 - n * 4)) & 15];
}

int fx_display_real_math_result(fx_render *r, uint16_t value_address, fx_box *final_box)
{
    /* These early controller modes have separate linear/complex/polar paths.
     * They are rejected explicitly, not silently approximated. */
    uint8_t mode = r->memory[0x80f9];
    unsigned selection = r->memory[0x8100] & 15;
    if (!(fx_display_has_natural_input(r) || fx_display_has_natural_result(r))
        || selection == 10 || mode == 137
        || (r->memory[0x80ff] & 0x10)
        || (mode == 69 && r->memory[0x80fc] == 1 && r->memory[0x80fd] == 3)
        || (mode == 75 && r->memory[0x80fc] == 1)) return -1;
    if (value_address < 0x8000 || value_address > 0xffec) return -1;
    fx_number value, imaginary;
    memcpy(value.bytes, r->memory + value_address, 10);
    memcpy(imaginary.bytes, r->memory + value_address + 10, 10);
    fx_number decimal_imaginary;
    fx_decimal decoded;
    if (fx_number_to_decimal(&decimal_imaginary, &imaginary) != FX_NUMERIC_OK
        || fx_decimal_decode(&decoded, &decimal_imaginary) != FX_NUMERIC_OK
        || decoded.mantissa != 0) return -1;

    /* 0x11072 selects persistent expression scratch from calculation mode. */
    uint16_t tokens = mode == 136 || !(mode & 0x80) ? 0x8546 : 0x8398;
    if (!(mode & 0xc0)) return -1; /* original would use a CPU-stack buffer */
    r->memory[0x8127] = 1;
    if (!r->memory[0x8130]) {
        r->memory[tokens] = 0;
        r->memory[0x8114] = 0;
        fx_format_options options = fx_format_default_options();
        options.selection = r->memory[0x8100];
        options.math_output = (uint8_t)fx_display_has_natural_result(r);
        options.mixed_fraction = r->memory[0x8107];
        options.display_mode = r->memory[0x8102];
        options.digits = r->memory[0x8103];
        options.decimal_dot = r->memory[0x8104];
        options.format_context = 0;
        fx_format_result result;
        uint8_t formatted[512];
        if (fx_format_number(&value, &options, formatted, sizeof formatted, &result) != FX_FORMAT_OK) {
            r->memory[0x8127] = 0;
            return 0;
        }
        if (result.length >= 512 || tokens + result.length >= FX_RENDER_MEMORY_BYTES) {
            r->memory[0x8127] = 0;
            return 0;
        }
        raw_scientific_suffixes(formatted, result.length);
        memcpy(r->memory + tokens, formatted, result.length + 1);
        fx_apply_result_format_state(r, &value, options.selection, result.kind);
    }

    result_history(r, tokens, selection);
    if (!fx_display_has_natural_input(r))
        memset(r->memory + FX_RAM_FRAMEBUFFER + 22 * 12, 0, 10 * 12);
    /* B456..B4A0: draw and restore the caller's expression pointer. */
    r->memory[0x8126] = 1;
    uint16_t previous_expression = word_at(r, 0x812c);
    store_word(r, 0x812c, tokens);
    int success = fx_render_viewport(r, final_box);
    store_word(r, 0x812c, previous_expression);
    r->memory[0x8127] = 0;
    return success;
}
