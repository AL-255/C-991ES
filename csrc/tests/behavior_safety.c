/* Bounds and undefined-behavior checks for the portable public APIs.
 * These checks supplement, and do not replace, original-ROM comparisons. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "parse/fx_eval.h"
#include "format/fx_format.h"
#include "render/fx_render.h"
#include "render/fx_result_complex.h"
#include "data/fx_rom_data.h"
#include "ui/fx_editor.h"
#include "ui/fx_input_codec.h"
#include "ui/fx_cursor.h"
#include "ui/fx_key_dispatch.h"

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
    static const uint8_t alphabet[] = "0123456789.+-()\x4e\x4f\x60\x63\x68\x70\x71\x72\x73\x74\x75\x76\x77\x80\x81\x82\x85\x86\x87\x88\x90\x91\x92\x93\x98\x9f\x5e\xae\xa0\xa1\xa2\xa3\xa8\xb0\xb1\xb2\xbe\xbf\xc3";
    uint8_t input[1024];
    fx_eval_result result;
    for (unsigned n = 0; n < 20000; ++n) {
        size_t length = random_word() % sizeof(input);
        for (size_t i = 0; i < length; ++i)
            input[i] = alphabet[random_word() % (sizeof(alphabet) - 1)];
        fx_eval_options options = fx_eval_default_options();
        options.calculation_context = n % 2 ? 0xc4 : 0xc1;
        options.math_output = (uint8_t)(n % 3 != 0);
        options.angle_unit = (uint8_t)(4 + n % 3);
        fx_eval_status status = fx_evaluate(input, length, &options, &result);
        assert(status == FX_EVAL_OK || status == FX_EVAL_SYNTAX || status == FX_EVAL_MATH ||
               status == FX_EVAL_STACK || status == FX_EVAL_ARGUMENT ||
               status == FX_EVAL_CONVERGENCE ||
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
    assert(fx_evaluate(input, sizeof(input), NULL, &result) == FX_EVAL_STACK);
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
        options.format_context = (uint8_t)(random_word() % 7);
        memset(storage, 0xa5, sizeof(storage));
        fx_format_status status = fx_format_number(&number, &options, storage+1, capacity, &result);
        assert(storage[0] == 0xa5 && storage[capacity+1] == 0xa5);
        if (status == FX_FORMAT_OK) assert(capacity > result.length && storage[result.length+1] == 0);
        if (status == FX_FORMAT_BUFFER_TOO_SMALL && capacity) assert(storage[capacity] == 0);
    }
}

static void base_parser_bounds(void)
{
    static const uint8_t masks[] = {FX_BASE_BIN, FX_BASE_OCT, FX_BASE_DEC, FX_BASE_HEX};
    static const uint8_t alphabet[] = "0123456789+-(),\x2f\x4e\x4f\x50\x51\x52\x53\x5c\x60\x61\x62\x63\x6e\x6f\x7e\x7f\xae\xb8\xb9\xba\xbb\xbc\xbd\xfb\xfc";
    uint8_t input[128], original[128];
    fx_number retained;
    struct {
        uint8_t before;
        fx_eval_result result;
        uint8_t after;
    } guarded;
    for (unsigned n = 0; n < 20000; ++n) {
        size_t length = random_word() % sizeof input;
        for (size_t i = 0; i < sizeof input; ++i)
            original[i] = input[i] = alphabet[random_word() % (sizeof alphabet - 1)];
        for (size_t i = 0; i < sizeof retained.bytes; ++i)
            retained.bytes[i] = (uint8_t)random_word();
        guarded.before = guarded.after = 0xa5;
        fx_eval_status status = fx_evaluate_base_n(input, length, masks[n % 4],
            NULL, NULL, &retained, &guarded.result);
        assert(status == FX_EVAL_OK || status == FX_EVAL_SYNTAX || status == FX_EVAL_MATH ||
               status == FX_EVAL_STACK || status == FX_EVAL_ARGUMENT ||
               status == FX_EVAL_CONVERGENCE ||
               status == FX_EVAL_UNIMPLEMENTED || status == FX_EVAL_RESOURCE_LIMIT);
        assert(guarded.result.consumed <= length);
        assert(memcmp(&guarded.result.value[1], &retained, sizeof retained) == 0);
        assert(memcmp(input, original, sizeof input) == 0);
        assert(guarded.before == 0xa5 && guarded.after == 0xa5);
    }
    assert(fx_evaluate_base_n(NULL, 0, FX_BASE_DEC, NULL, NULL, &retained,
                             &guarded.result) == FX_EVAL_SYNTAX);
    assert(memcmp(&guarded.result.value[1], &retained, sizeof retained) == 0);
}

static void input_codec_bounds(void)
{
    static uint8_t storage[65538];
    fx_platform platform = {fx_rom_data, 0x30000, storage+1, 0, FX_MEMORY_OK};
    uint8_t *memory = storage+1;
    static const uint8_t constructs[] = {0x5e, 0x68, 0x75, 0x76, 0x77, 0x7c,
                                        0x98, 0x9f, 0xa0, 0xa8, 0xae, 0xb0};
    storage[0] = storage[65537] = 0xa5;
    for (unsigned n = 0; n < 20000; ++n) {
        unsigned length = random_word() % 90;
        memset(memory, 0, 65536);
        for (unsigned i = 0; i < length; ++i)
            memory[0x8154+i] = (uint8_t)('0' + random_word() % 10);
        memory[0x8114] = (uint8_t)(random_word() % (length+1));
        memory[0x80f9] = 0xc1; memory[0x80fc] = 1; memory[0x8106] = 1;
        memory[0x812c] = 0x54; memory[0x812d] = 0x81;
        assert(fx_editor_insert_construct(&platform,
            constructs[random_word() % sizeof(constructs)]) >= 0);
        int status = fx_editor_input_boundaries(&platform, 0x8154);
        assert(status == 0 || status == 1 || status == -1);
        status = fx_editor_export_input(&platform, 0x8154, 0x8400,
                                       (uint8_t)random_word(), 1);
        assert(status == 0 || status == -1);
        assert(memory[0x83ff] == 0 && memory[0x8500] == 0);
        status = fx_editor_export_input(&platform, 0x8154, 0x8600,
                                       (uint8_t)random_word(), 0);
        assert(status == 0 || status == -1);
        assert(memory[0x85ff] == 0 && memory[0x8700] == 0);
        assert(storage[0] == 0xa5 && storage[65537] == 0xa5);
    }
}

static void cursor_key_bounds(void)
{
    static uint8_t storage[65538];
    fx_platform p = {fx_rom_data, 0x30000, storage+1, 0, FX_MEMORY_OK};
    uint8_t *memory = storage+1;
    storage[0] = storage[65537] = 0xa5;
    for (unsigned n = 0; n < 20000; ++n) {
        uint16_t source = (uint16_t)random_word(), destination = (uint16_t)random_word();
        memory[0x811b] = (uint8_t)random_word();
        fx_cursor_capture(&p, destination, source);
        fx_cursor_restore(&p, source, destination);
        fx_cursor_tick(&p, (uint16_t)random_word());
        assert(fx_cursor_is_visible(&p) <= 1);
        /* Valid finite expression for EC's glyph refresh; other state bytes
         * retain the deterministic mutations from the cursor operations. */
        memcpy(memory+0x8154, "123", 4);
        uint8_t output;
        int status = fx_key_process_token(&p, (uint8_t)random_word(),
                                           (uint16_t)random_word(), &output);
        assert(status == 0 || status == 1);
        assert(storage[0] == 0xa5 && storage[65537] == 0xa5);
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
    fx_number pair[2];
    assert(fx_decimal_parse(&pair[0], "1") == FX_NUMERIC_OK);
    assert(fx_decimal_parse(&pair[1], "2") == FX_NUMERIC_OK);
    for (unsigned polar = 0; polar < 2; ++polar) {
        for (unsigned selection = 0; selection < 14; ++selection) {
            memset(memory, 0, sizeof memory);
            memory[0x80f9] = 0xc4; memory[0x80fc] = 1;
            memory[0x8100] = (uint8_t)selection; memory[0x8104] = 1;
            memory[0x8105] = 4; memory[0x8106] = 1;
            memory[0x8108] = (uint8_t)!polar;
            memory[0x811f] = 10; memory[0x8121] = 1;
            memory[0x812d] = 0x82;
            memcpy(memory+0x8300, pair, sizeof pair);
            fx_box box;
            assert(fx_display_complex_result(&render, 0x8300, &box) == 1);
            assert(!memcmp(memory+0x8300, pair, sizeof pair));
            /* Cached output intentionally bypasses the numeric address. */
            memory[0x8130] = 0;
            assert(fx_display_complex_result(&render, 0x7fff, &box) == -1);
            memory[0x8130] = 0;
            assert(fx_display_complex_result(&render, 0xffed, &box) == -1);
        }
    }
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
    parser_bounds(); base_parser_bounds(); formatter_bounds(); render_bounds(); editor_bounds(); input_codec_bounds(); cursor_key_bounds();
    puts("Public API bounds checks passed (160000 deterministic fuzz cases plus boundaries).");
    return 0;
}
