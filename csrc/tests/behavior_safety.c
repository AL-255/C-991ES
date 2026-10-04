/* Bounds and undefined-behavior checks for the portable public APIs.
 * These checks supplement, and do not replace, original-ROM comparisons. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "parse/fx_eval.h"
#include "format/fx_format.h"
#include "render/fx_render.h"
#include "data/fx_rom_data.h"
#include "ui/fx_editor.h"

static uint32_t random_state = 0x991ec001;
static uint32_t random_word(void)
{
    random_state ^= random_state << 13;
    random_state ^= random_state >> 17;
    random_state ^= random_state << 5;
    return random_state;
}

static void parser_bounds(void)
{
    static const uint8_t alphabet[] = "0123456789.+-()\x4e\x4f\x60\x68\x74\x75\x76\x77\x81\x82\x85\x86\x87\x98\x5e\xae\xa0\xa1\xa2\xa3\xb0\xb1\xb2";
    uint8_t input[1024];
    fx_eval_result result;
    for (unsigned n = 0; n < 20000; ++n) {
        size_t length = random_word() % sizeof(input);
        for (size_t i = 0; i < length; ++i)
            input[i] = alphabet[random_word() % (sizeof(alphabet) - 1)];
        fx_eval_status status = fx_evaluate(input, length, NULL, &result);
        assert(status == FX_EVAL_OK || status == FX_EVAL_SYNTAX || status == FX_EVAL_MATH ||
               status == FX_EVAL_UNIMPLEMENTED || status == FX_EVAL_RESOURCE_LIMIT);
        assert(result.consumed <= length);
    }
    memset(input, '1', sizeof(input));
    for (size_t i = 252; i < 260; ++i) {
        input[i] = 0x74; input[i+1] = 0x60; input[i+2] = '9'; input[i+3] = 0;
        assert(fx_evaluate(input, i+4, NULL, &result) == FX_EVAL_RESOURCE_LIMIT || i < 255);
        memset(input, '1', sizeof(input));
    }
    memset(input, '(', sizeof(input)); input[sizeof(input)-1] = '1';
    assert(fx_evaluate(input, sizeof(input), NULL, &result) == FX_EVAL_RESOURCE_LIMIT);
    assert(fx_evaluate(NULL, 0, NULL, &result) == FX_EVAL_SYNTAX);
    assert(fx_evaluate(input, sizeof(input), NULL, NULL) == FX_EVAL_SYNTAX);
}

static void formatter_bounds(void)
{
    static const uint8_t selections[] = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15};
    static const uint8_t modes[] = {0, 4, 8, 9};
    for (unsigned n = 0; n < 20000; ++n) {
        fx_decimal d;
        fx_number number;
        fx_format_options options = fx_format_default_options();
        fx_format_result result = {0, 0, 0};
        uint8_t storage[67];
        size_t capacity = random_word() % 65;
        d.sign = random_word() % 2 ? -1 : 1;
        d.exponent = (int)(random_word() % 199) - 99;
        d.mantissa = UINT64_C(100000000000000) +
                     (((uint64_t)random_word() << 32) | random_word()) % UINT64_C(900000000000000);
        d.flags = 0;
        assert(fx_decimal_encode(&number, &d) == FX_NUMERIC_OK);
        options.selection = selections[random_word() % sizeof(selections)];
        options.display_mode = modes[random_word() % sizeof(modes)];
        options.math_output = (uint8_t)(random_word() % 2);
        options.mixed_fraction = (uint8_t)(random_word() % 2);
        options.digits = (uint8_t)(random_word() % 10);
        options.format_context = (uint8_t)(random_word() % 4);
        memset(storage, 0xa5, sizeof(storage));
        fx_format_status status = fx_format_number(&number, &options, storage+1, capacity, &result);
        assert(storage[0] == 0xa5 && storage[capacity+1] == 0xa5);
        if (status == FX_FORMAT_OK) assert(capacity > result.length && storage[result.length+1] == 0);
        if (status == FX_FORMAT_BUFFER_TOO_SMALL && capacity) assert(storage[capacity] == 0);
    }
}

static void render_bounds(void)
{
    static uint8_t memory[65536];
    fx_render render = {fx_rom_data, 0x30000, memory};
    static const uint8_t fonts[] = {6, 7, 10};
    for (unsigned n = 0; n < 20000; ++n) {
        memory[0x811f] = fonts[random_word() % sizeof(fonts)];
        memory[0x8121] = (uint8_t)(random_word() % 2);
        memory[0x8122] = (uint8_t)random_word();
        fx_draw_glyph(&render, (uint8_t)random_word(), (int8_t)random_word(), (uint8_t)random_word());
        fx_draw_line(&render, (int8_t)random_word(), (int8_t)random_word(),
                     (int8_t)random_word(), (int8_t)random_word());
    }
    static const uint8_t fraction[] = "\xae\xbb\xb8\x98\xb8" "998" "\xb9\xb9\xb8" "99" "\xb9\xbc";
    memset(memory, 0, sizeof(memory));
    memory[0x8121] = 1; memory[0x8114] = 255;
    memcpy(memory+0x8200, fraction, sizeof(fraction));
    for (unsigned draw = 0; draw < 2; ++draw) {
        fx_box box;
        fx_begin_layout_pass(&render, (uint8_t)draw);
        assert(fx_layout_sequence(&render, 0x8200, &box, 2, 17) != 0);
    }
    fx_flush_framebuffer(&render);
}

static void editor_bounds(void)
{
    static uint8_t storage[65538];
    fx_platform platform = {fx_rom_data, 0x30000, storage+1, 0, FX_MEMORY_OK};
    uint8_t *memory = storage+1;
    storage[0] = storage[65537] = 0xa5;
    for (unsigned n = 0; n < 20000; ++n) {
        unsigned length = random_word() % 100;
        memset(memory+0x8154, 0, 356);
        for (unsigned i = 0; i < length; ++i)
            memory[0x8154+i] = (uint8_t)(1 + random_word() % 255);
        memory[0x8114] = (uint8_t)(random_word() % (length+1));
        memory[0x80f8] = (uint8_t)random_word();
        memory[0x80f9] = 0xc1; memory[0x80fc] = 1;
        memory[0x812c] = 0x54; memory[0x812d] = 0x81;
        memory[0x8106] = (uint8_t)(random_word() % 2);
        int status = fx_editor_insert_byte(&platform, (uint8_t)random_word());
        assert(status == 0 || status == 1);
        assert(fx_editor_refresh_cursor(&platform) == 0);
        assert(fx_editor_update_modifiers(&platform, (uint8_t)random_word()) == 0);
        static const uint8_t actions[] = {0xe0, 0xe1, 0xe2, 0xe3, 0xfe};
        status = fx_editor_text_action(&platform, actions[random_word() % sizeof(actions)]);
        assert(status == 0 || status == -1);
        assert(storage[0] == 0xa5 && storage[65537] == 0xa5);
    }
    static const uint8_t constructs[] = {0x5e, 0x68, 0x75, 0x76, 0x77, 0x7c,
                                        0x98, 0x9f, 0xa0, 0xa8, 0xae, 0xb0};
    for (unsigned n = 0; n < 20000; ++n) {
        unsigned length = random_word() % 100;
        memset(memory+0x8154, 0, 356);
        for (unsigned i = 0; i < length; ++i)
            memory[0x8154+i] = (uint8_t)('0' + random_word() % 10);
        memory[0x8114] = (uint8_t)(random_word() % (length+1));
        memory[0x80f8] = (uint8_t)random_word();
        memory[0x80f9] = 0xc1; memory[0x80fc] = 1; memory[0x8106] = 1;
        memory[0x812c] = 0x54; memory[0x812d] = 0x81;
        int status = fx_editor_insert_construct(&platform, constructs[random_word() % sizeof(constructs)]);
        assert(status == 0 || status == 1);
        static const uint8_t actions[] = {0xe0, 0xe1, 0xe2, 0xe3, 0xfe};
        status = fx_editor_text_action(&platform, actions[random_word() % sizeof(actions)]);
        assert(status == 0 || status == -1);
        assert(storage[0] == 0xa5 && storage[65537] == 0xa5);
    }
}

int main(void)
{
    parser_bounds(); formatter_bounds(); render_bounds(); editor_bounds();
    puts("Public API bounds checks passed (100000 deterministic fuzz cases plus boundaries).");
    return 0;
}
