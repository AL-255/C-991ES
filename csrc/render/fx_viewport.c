#include "fx_render.h"
#include "fx_render_memory.h"

static uint16_t word_at(const fx_render *r, uint16_t address)
{
    return (uint16_t)(r->memory[address] | ((uint16_t)r->memory[(uint16_t)(address + 1)] << 8));
}

static void store_word(fx_render *r, uint16_t address, uint16_t value)
{
    r->memory[address] = (uint8_t)value;
    r->memory[(uint16_t)(address + 1)] = (uint8_t)(value >> 8);
}

static void symbol(fx_render *r, uint8_t x, uint8_t y, uint8_t character)
{
    /* These helpers call the text rasterizer; its safer start bound matters. */
    unsigned advance = r->memory[0x811f] == 6 ? 4 : 6;
    if (x <= 96 - advance) fx_draw_glyph(r, x, (int8_t)y, character);
}

static void draw_model_prefix(fx_render *r, uint8_t y)
{
    unsigned source = r->memory[0x810e] && (r->memory[0x8138] & 1) ? 0x1ac0 : 0x1aba;
    uint8_t x = 0;
    while (source < r->rom_size && r->rom[source] && x <= 90) {
        symbol(r, x, y, r->rom[source++]);
        x = (uint8_t)(x + 6);
    }
}

/* 0x32D4 / 0x8164: replace an unlayoutable expression with the selected
 * persistent fallback buffer. Copy forward and retain 16-bit address wrap. */
static int copy_fallback(fx_render *r, uint16_t destination)
{
    uint8_t mode = r->memory[0x80f9];
    uint16_t source = mode == 136 || (!(mode & 0x80) && (mode & 0x40)) ? 0x8546
                      : mode & 0x80 ? 0x8398 : 0;
    if (!destination) return 1;
    if (!source) {
        if (destination >= 0x8000) r->memory[destination] = 0;
        return 1;
    }
    for (unsigned n = 0; n < 65536; ++n, ++destination, ++source) {
        uint8_t value = source < 0x8000 ? (source < r->rom_size ? r->rom[source] : 0)
                                       : r->memory[source];
        if (destination >= 0x8000) r->memory[destination] = value;
        if (!value) return 1;
    }
    return 0; /* native would keep copying a nonterminating overlap */
}

int fx_render_viewport(fx_render *r, fx_box *final_box)
{
    uint8_t selection = r->memory[0x8126];
    int result = r->memory[0x80fe] != 1 && selection != 0;
    uint16_t expression = word_at(r, 0x812c);
    store_word(r, 0x8000, 0);
    r->memory[0x8005] = 0;
    fx_begin_layout_pass(r, 0);
    fx_box box = {0, 0, 0};
    if (!fx_layout_sequence(r, expression, &box, 0, 62) || box.height > 62) {
        if (!copy_fallback(r, expression)) {
            if (final_box) *final_box = box;
            return 0;
        }
        r->memory[0x8114] = r->memory[0x8006];
        fx_begin_layout_pass(r, 0);
        if (!fx_layout_sequence(r, expression, &box, 0, 62)) {
            if (final_box) *final_box = box;
            return 0; /* a failed second measurement needs native-state audit */
        }
    }
    int model_prefix = r->memory[0x80f9] == 136 && r->memory[0x80fc] == 1;
    if (model_prefix) r->memory[0x8116] = (uint8_t)(r->memory[0x8116] + 30);
    uint16_t x = 0;
    uint8_t baseline;
    if (!result) {
        r->memory[0x8128] = box.height;
        r->memory[0x8115] = box.width > 96 ? 96 : (uint8_t)box.width;
        x = r->memory[0x8116];
        uint8_t visible = (uint8_t)(96 - r->memory[0x8116] - 6);
        unsigned iterations = 0;
        while ((uint16_t)(word_at(r, 0x8002) - word_at(r, 0x8000)) > visible
               && (uint16_t)(box.width - word_at(r, 0x8000)) > visible) {
            store_word(r, 0x8000, (uint16_t)(word_at(r, 0x8000) + 8));
            if (++iterations == 8192) return 0;
        }
        baseline = (uint8_t)(box.height - box.depth + 1);
        if (box.height > 31) {
            uint8_t cursor_distance = (uint8_t)(box.depth + 62 - r->memory[0x8004]);
            if (selection && cursor_distance > 12) {
                uint8_t maximum = (uint8_t)(93 - baseline - 4);
                iterations = 0;
                while ((uint8_t)(r->memory[0x8004] - r->memory[0x8005]) > maximum) {
                    r->memory[0x8005] = (uint8_t)(r->memory[0x8005] + 8);
                    if (++iterations == 32) return 0;
                }
            } else {
                r->memory[0x8005] = (uint8_t)(box.height - 31);
                r->memory[0x8128] = 31;
            }
        }
        fx_clear_framebuffer(r);
    } else {
        if ((uint8_t)(r->memory[0x8115] + (box.width > 96 ? 96 : box.width)) > 90)
            fx_make_result_space(r, box.height);
        if (box.width <= 96) {
            x = (uint16_t)(96 - box.width);
        } else {
            store_word(r, 0x8000, (uint16_t)(r->memory[0x8114] * 8));
            if ((uint16_t)(box.width - word_at(r, 0x8000)) <= 88) {
                --r->memory[0x8114];
                store_word(r, 0x8000, (uint16_t)(r->memory[0x8114] * 8));
                r->memory[0x80f4] = 0; /* 0x540e: stop keyboard repeat */
            }
            r->memory[0x8130] = 1;
            fx_clear_from_row(r, (uint8_t)(32 - box.height));
        }
        baseline = (uint8_t)(32 - box.depth);
    }
    fx_begin_layout_pass(r, 1);
    int success = fx_layout_sequence(r, expression, &box, x, baseline) != 0;
    uint16_t scroll_x = word_at(r, 0x8000);
    uint8_t scroll_y = r->memory[0x8005];
    uint8_t indicator_y = (uint8_t)(baseline - scroll_y - 5);
    if (model_prefix) draw_model_prefix(r, indicator_y);
    if (scroll_x) symbol(r, r->memory[0x8116], indicator_y, 159);
    if ((uint16_t)(box.width - scroll_x) > (uint16_t)(96 - r->memory[0x8116]))
        symbol(r, 90, indicator_y, selection ? 158 : 191);
    r->memory[0x8116] = 0;
    if (r->memory[0x80fe] == 1) {
        r->memory[0x811f] = 6;
        if (scroll_y) symbol(r, 46, 0, 238);
        if (box.height > (uint8_t)(scroll_y + 31)) symbol(r, 46, 26, 239);
    }
    if (final_box) *final_box = box;
    return success;
}
