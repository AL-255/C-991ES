#include "fx_render.h"
#include "fx_layout_validate.h"
#include "fx_render_context.h"

/* Recursive typesetting, translated as boxes and geometry rather than
 * registers. Child metric slots retain the original four-byte RAM format. */
static uint8_t read_byte(const fx_render *r, uint16_t address)
{
    return address < 0x8000 ? (address < r->rom_size ? r->rom[address] : 0)
                            : r->memory[address];
}

static uint16_t read_word(const fx_render *r, uint16_t address)
{
    return (uint16_t)(read_byte(r, address)
                    | ((uint16_t)read_byte(r, (uint16_t)(address + 1)) << 8));
}

static fx_box cache_box(const fx_render *r, unsigned slot)
{
    uint16_t address = (uint16_t)(0x8640 + slot * 4);
    fx_box box = {read_word(r, address), read_byte(r, (uint16_t)(address + 2)),
                  read_byte(r, (uint16_t)(address + 3))};
    return box;
}

static void cache_store(fx_render *r, unsigned slot, fx_box box)
{
    uint16_t address = (uint16_t)(0x8640 + slot * 4);
    r->memory[address] = (uint8_t)box.width;
    r->memory[(uint16_t)(address + 1)] = (uint8_t)(box.width >> 8);
    r->memory[(uint16_t)(address + 2)] = box.height;
    r->memory[(uint16_t)(address + 3)] = box.depth;
}

static uint8_t layout_kind(fx_render *r, uint16_t pointer);

static void adjust_cursor_x(fx_render *r, uint16_t amount)
{
    uint16_t value = (uint16_t)(read_word(r, 0x8002) + amount);
    r->memory[0x8002] = (uint8_t)value;
    r->memory[0x8003] = (uint8_t)(value >> 8);
}

static uint8_t suspend_cursor(fx_render *r)
{
    uint8_t previous = r->memory[0x800a];
    if (!r->memory[0x8009]) r->memory[0x800a] = 0;
    return previous;
}

static void restore_cursor(fx_render *r, uint8_t previous)
{
    if (!r->memory[0x8009] && !r->memory[0x800a]) r->memory[0x800a] = previous;
}

static int allocate_slots(fx_render *r, unsigned count, unsigned *first)
{
    *first = r->memory[0x8008];
    r->memory[0x8008] = (uint8_t)(*first + count);
    return r->memory[0x8008] <= 50;
}

/* 0x36f0 / 0x375c, the glyph spelling tables. */
static unsigned expand_token(const fx_render *r, uint8_t token, uint8_t text[258])
{
    if (!token) { text[0] = 0; return 0; }
    uint16_t pointer_base = 0x1ade, length_base = 0x1cde;
    if (token >= 200 && token < 203 && r->memory[0x80f9] == 193) {
        token = (uint8_t)(token + 56);
        pointer_base = 0x201e;
        length_base = 0x202c;
    }
    uint16_t source = read_word(r, (uint16_t)(pointer_base + token * 2));
    uint8_t description = read_byte(r, (uint16_t)(length_base + token));
    unsigned length = description & 15, offset = description >> 4;
    if (offset != 15) source = (uint16_t)(source + offset);
    unsigned copied = length ? length : 256;
    for (unsigned n = 0; n < copied; ++n)
        text[n] = read_byte(r, (uint16_t)(source + n));
    if (offset == 15) text[copied++] = '(';
    text[copied] = 0;
    return length + (offset == 15);
}

/* 0x8936 / 0x8182 / 0x11014: cursor geometry and blink metadata. Cursor
 * pixels are toggled later by a separate UI routine; this walk sets state. */
static void cursor_at(fx_render *r, uint16_t pointer, uint16_t x, uint8_t baseline)
{
    uint8_t text[258];
    unsigned count = expand_token(r, read_byte(r, pointer), text);
    if (layout_kind(r, pointer) == 1) {
        unsigned index = fx_construct_index(read_byte(r, pointer));
        count = r->rom_size > 0x2c72 + index ? r->rom[0x2c72 + index] : 1;
    }
    if (!count) count = 1;
    uint16_t end_x = (uint16_t)(x + (uint8_t)(count * 6));
    r->memory[0x8002] = (uint8_t)end_x;
    r->memory[0x8003] = (uint8_t)(end_x >> 8);
    r->memory[0x8004] = baseline;
    if (r->memory[0x8009] && r->memory[0x80fe] == 1) {
        r->memory[0x8118] = (uint8_t)(x - read_word(r, 0x8000));
        r->memory[0x8119] = (uint8_t)(baseline - r->memory[0x8005] - fx_font_ascent(r));
        int math = fx_display_has_natural_input(r);
        unsigned kind = layout_kind(r, (uint16_t)(0x8154 + r->memory[0x8114]));
        if (math && (kind == 3 || kind == 5 || kind == 9 || kind == 11 || kind == 12)
            && (r->memory[0x80f8] & 0x80))
            r->memory[0x80f8] = (uint8_t)((r->memory[0x80f8] + 128) & ~8);
        unsigned length = 0;
        while (read_byte(r, (uint16_t)(0x8154 + length)) && length < 65536) ++length;
        uint8_t character = (uint8_t)(length + 11) >= 100 ? 204
                            : (r->memory[0x80f8] & 0x80) ? 207 : 124;
        if (math && (r->memory[0x80f8] & 0x80)) character = 158;
        r->memory[0x811a] = character;
        r->memory[0x811b] = r->memory[0x811f];
    }
}

static void world_text(fx_render *r, const uint8_t *text, uint16_t x, uint8_t baseline)
{
    if (!r->memory[0x8009]) return;
    uint16_t scroll = read_word(r, 0x8000);
    uint16_t minimum = (uint16_t)(scroll + r->memory[0x8116]);
    uint8_t top = (uint8_t)(baseline - fx_font_ascent(r));
    unsigned n = 0;
    while (x < minimum && text[n]) { ++n; x = (uint16_t)(x + 6); }
    uint16_t screen_x = (uint16_t)(x - scroll);
    int screen_y = (int)top - r->memory[0x8005];
    if (screen_x > 95 || screen_y < -10 || screen_y > 31) return;
    unsigned advance = r->memory[0x811f] == 6 ? 4 : 6;
    unsigned maximum = r->memory[0x811f] == 6 ? 24 : 16;
    for (unsigned count = 0; text[n] && screen_x <= 96 - advance && count < maximum;
         ++count, ++n, screen_x = (uint16_t)(screen_x + advance))
        fx_draw_glyph(r, (uint8_t)screen_x, (int8_t)screen_y, text[n]);
}

static unsigned token_glyphs(fx_render *r, uint8_t token, uint16_t x,
                              uint8_t baseline, int omit_last)
{
    uint8_t text[258];
    unsigned length;
    if (r->memory[0x8127] && (token < 94 || token >= 192)) {
        text[0] = token >= 224 ? (uint8_t)(token + 176) : token;
        text[1] = 0;
        length = 1;
    } else {
        length = expand_token(r, token, text);
    }
    /* Native R4 is a byte. Malformed tokens with an empty spelling wrap
     * 0-1 to 255, rather than underflowing a host array index. */
    if (omit_last) { length = (uint8_t)(length - 1); text[length] = 0; }
    world_text(r, text, x, baseline);
    return length * 6;
}

static void world_pixel(fx_render *r, uint16_t x, uint8_t y)
{
    if (!r->memory[0x8009]) return;
    uint16_t scroll = read_word(r, 0x8000);
    if (x < (uint16_t)(scroll + r->memory[0x8116])) return;
    x = (uint16_t)(x - scroll);
    if (x > 95 || y < r->memory[0x8005]) return;
    unsigned screen_y = y - r->memory[0x8005];
    if (screen_y <= 31) fx_set_pixel(r, (int8_t)x, (int8_t)screen_y);
}

static void world_horizontal(fx_render *r, uint16_t x0, uint16_t x1, uint8_t y)
{
    if (!r->memory[0x8009] || y < r->memory[0x8005]) return;
    unsigned sy = y - r->memory[0x8005];
    if (sy > 31) return;
    uint16_t scroll = read_word(r, 0x8000);
    uint16_t minimum = (uint16_t)(scroll + r->memory[0x8116]);
    if (x1 < minimum) return;
    if (x0 < minimum) x0 = minimum;
    unsigned sx0 = (uint16_t)(x0 - scroll), sx1 = (uint16_t)(x1 - scroll);
    if (sx0 > 95) return;
    if (sx1 > 95) sx1 = 95;
    fx_draw_line(r, (int8_t)sx0, (int8_t)sy, (int8_t)sx1, (int8_t)sy);
}

static void world_vertical(fx_render *r, uint16_t x, uint8_t y0, uint8_t y1)
{
    if (!r->memory[0x8009]) return;
    uint16_t scroll = read_word(r, 0x8000);
    if (x < (uint16_t)(scroll + r->memory[0x8116])) return;
    unsigned sx = (uint16_t)(x - scroll);
    if (sx > 95 || y1 < r->memory[0x8005]) return;
    unsigned sy0 = y0 < r->memory[0x8005] ? 0 : y0 - r->memory[0x8005];
    unsigned sy1 = y1 - r->memory[0x8005];
    if (sy0 > 31) return;
    if (sy1 > 31) sy1 = 31;
    fx_draw_vertical(r, (uint8_t)sx, (uint8_t)sy0, (uint8_t)sy1, 0);
}

/* The root's sloping stem is usually vertical or one pixel to the right.
 * Its geometry comes from 0x867a, followed by original line rasterization. */
static void world_root_stem(fx_render *r, uint16_t x0, uint8_t y0,
                             uint16_t x1, uint8_t y1)
{
    if (!r->memory[0x8009]) return;
    uint16_t scroll = read_word(r, 0x8000);
    uint16_t minimum = (uint16_t)(scroll + r->memory[0x8116]);
    uint8_t vertical = r->memory[0x8005];
    if (x1 < minimum || y1 < vertical || y0 > y1) return;
    int sx0 = (uint16_t)(x0 - scroll), sx1 = (uint16_t)(x1 - scroll);
    int sy0 = y0 - vertical, sy1 = y1 - vertical;
    /* 0x83e8 rejects an off-screen first endpoint even if the second
     * endpoint would come back onto the screen. */
    if (sx0 > 95) return;
    /* Native helper 0xc3f4 uses truncating integer interpolation at edges. */
    if (sy0 < 0 && sy1 != sy0) {
        sx0 = (sy1 * sx0 - sy0 * sx1) / (sy1 - sy0);
        sy0 = 0;
    }
    if (sy0 > 31) return;
    if (sy1 > 31 && sy1 != sy0) {
        sx1 = ((sx1 - sx0) * 31 + sy1 * sx0 - sy0 * sx1) / (sy1 - sy0);
        sy1 = 31;
    }
    fx_draw_line(r, (int8_t)sx1, (int8_t)sy1, (int8_t)sx0, (int8_t)sy0);
}

static void enclose(fx_render *r, fx_box *box, uint16_t x, uint8_t baseline,
                     uint8_t token)
{
    if (token == 0x63) { box->height++; box->width = (uint16_t)(box->width + 12); }
    else { box->height += 2; box->width = (uint16_t)(box->width + 7); }
    uint8_t bottom = (uint8_t)(baseline + box->depth - 1);
    uint8_t top = (uint8_t)(bottom - box->height + 2);
    if (token == 0x63) {
        world_vertical(r, (uint16_t)(x + 3), top, bottom);
        world_vertical(r, (uint16_t)(x + box->width - 3), top, bottom);
    } else {
        world_horizontal(r, (uint16_t)(x + 4), (uint16_t)(x + box->width - 1), top);
        world_root_stem(r, (uint16_t)(x + 4), top, (uint16_t)(x + 3), bottom);
        world_pixel(r, (uint16_t)(x + 2), (uint8_t)(bottom - 1));
        world_pixel(r, (uint16_t)(x + 1), (uint8_t)(bottom - 2));
    }
}

static uint16_t root_or_absolute(fx_render *r, uint16_t pointer, fx_box *box,
                                  uint16_t x, uint8_t baseline)
{
    uint8_t token = read_byte(r, pointer);
    uint16_t stop = fx_layout_sequence(r, (uint16_t)(pointer + 2), box,
                                       (uint16_t)(x + (token == 0x98 ? 5 : 6)), baseline);
    if (stop) enclose(r, box, x, baseline, token);
    return stop;
}

static uint16_t power(fx_render *r, uint16_t pointer, fx_box *box,
                       uint16_t x, uint8_t baseline)
{
    unsigned slot;
    if (!allocate_slots(r, 1, &slot)) return 0;
    uint8_t previous_cursor = suspend_cursor(r);
    uint8_t token = read_byte(r, pointer);
    unsigned prefix = token == 0x5e ? 0 : 6;
    uint8_t original_height = prefix ? fx_font_height(r) : box->height;
    uint8_t original_depth = prefix ? fx_font_depth(r) : box->depth;
    if (prefix) {
        uint8_t text[2] = {token == 0x73 ? 129 : 131, 0};
        world_text(r, text, x, baseline);
        x = (uint16_t)(x + 6);
    }
    uint8_t previous_font = fx_select_small_font(r);
    uint8_t extra_height = (uint8_t)(original_height - 5);
    if (r->memory[0x8009]) *box = cache_box(r, slot);
    uint8_t exponent_baseline = r->memory[0x8009]
        ? (uint8_t)(baseline - (uint8_t)(extra_height - original_depth + box->depth))
        : baseline;
    uint16_t stop = fx_layout_sequence(r, (uint16_t)(pointer + 2), box, x, exponent_baseline);
    if (!stop) return 0;
    if (!r->memory[0x8009]) cache_store(r, slot, *box);
    if (!r->memory[0x8009] && r->memory[0x800a])
        r->memory[0x8004] = (uint8_t)(r->memory[0x8004] - extra_height + original_depth - box->depth);
    if (read_byte(r, (uint16_t)(stop + 1)) == 0x5e) return 0;
    r->memory[0x811f] = previous_font;
    box->width = (uint16_t)(box->width + prefix + 1);
    box->height = (uint8_t)(box->height + extra_height);
    box->depth = original_depth;
    restore_cursor(r, previous_cursor);
    return stop;
}

static uint16_t fraction(fx_render *r, uint16_t pointer, fx_box *box,
                          uint16_t x, uint8_t baseline)
{
    unsigned slot;
    if (!allocate_slots(r, 2, &slot)) return 0;
    uint8_t previous_cursor = suspend_cursor(r), cursor_part = 0;
    uint8_t previous_font = fx_select_small_font(r);
    fx_box whole = {0, 0, 0};
    uint16_t child = (uint16_t)(pointer + 3);
    if (read_byte(r, pointer) == 0x7c) {
        if (!fx_mixed_whole_valid(r, (uint16_t)(pointer + 4))) return 0;
        child = fx_layout_sequence(r, (uint16_t)(pointer + 4), &whole,
                                    (uint16_t)(x + 1), baseline);
        if (!child) return 0;
        if (!r->memory[0x8009] && r->memory[0x800a]) cursor_part = 1;
        x = (uint16_t)(x + whole.width + 1);
        whole.width++;
        child = (uint16_t)(child + 2);
    }
    fx_box denominator = cache_box(r, slot + 1);
    if (r->memory[0x8009]) *box = cache_box(r, slot);
    uint16_t width = (uint16_t)((box->width > denominator.width ? box->width : denominator.width) + 2);
    uint16_t stop = fx_layout_sequence(r, child, box,
        r->memory[0x8009] ? (uint16_t)(x + ((uint16_t)(width - box->width) >> 1)) : x,
        r->memory[0x8009] ? (uint8_t)(baseline - box->depth - 1) : baseline);
    if (!stop) return 0;
    if (!r->memory[0x8009] && r->memory[0x800a] && !cursor_part) cursor_part = 2;
    if (!r->memory[0x8009]) cache_store(r, slot, *box);
    stop = fx_layout_sequence(r, (uint16_t)(stop + 2), &denominator,
        r->memory[0x8009] ? (uint16_t)(x + ((uint16_t)(width - denominator.width) >> 1)) : x,
        r->memory[0x8009] ? (uint8_t)(baseline + denominator.height - denominator.depth + 1) : baseline);
    cache_store(r, slot + 1, denominator);
    if (!stop) return 0;
    if (!r->memory[0x8009] && r->memory[0x800a] && !cursor_part) cursor_part = 3;
    if (!r->memory[0x8009]) {
        width = (uint16_t)((box->width > denominator.width ? box->width : denominator.width) + 2);
        cache_store(r, slot + 1, denominator);
        if (cursor_part == 2) {
            adjust_cursor_x(r, (uint16_t)((uint16_t)(width - box->width) >> 1));
            r->memory[0x8004] = (uint8_t)(r->memory[0x8004] - box->depth - 1);
        } else if (cursor_part == 3) {
            adjust_cursor_x(r, (uint16_t)((uint16_t)(width - denominator.width) >> 1));
            r->memory[0x8004] = (uint8_t)(r->memory[0x8004] + denominator.height - denominator.depth + 1);
        }
        restore_cursor(r, previous_cursor);
    }
    world_horizontal(r, (uint16_t)(x + 1), (uint16_t)(x + width - 1), baseline);
    r->memory[0x811f] = previous_font;
    box->width = (uint16_t)(width + whole.width);
    box->height = (uint8_t)(box->height + denominator.height + 2);
    box->depth = (uint8_t)(denominator.height + 1);
    fx_merge_vertical(box, &whole);
    return (uint16_t)(stop + 1);
}

static uint16_t nth_root(fx_render *r, uint16_t pointer, fx_box *box,
                          uint16_t x, uint8_t baseline)
{
    unsigned slot;
    if (!allocate_slots(r, 2, &slot)) return 0;
    uint8_t previous_cursor = suspend_cursor(r);
    uint8_t previous_font = fx_select_small_font(r);
    fx_box index = cache_box(r, slot);
    if (r->memory[0x8009]) *box = cache_box(r, slot + 1);
    uint8_t index_baseline = r->memory[0x8009]
        ? (uint8_t)(baseline - (uint8_t)(box->height - box->depth + index.depth - 5)) : baseline;
    uint16_t stop = fx_layout_sequence(r, (uint16_t)(pointer + 3), &index,
                                       (uint16_t)(x + 1), index_baseline);
    cache_store(r, slot, index);
    if (!stop) return 0;
    int index_cursor = !r->memory[0x8009] && r->memory[0x800a];
    r->memory[0x811f] = previous_font;
    stop = fx_layout_sequence(r, (uint16_t)(stop + 2), box,
                              (uint16_t)(x + index.width + 3), baseline);
    if (!stop) return 0;
    enclose(r, box, (uint16_t)(x + index.width - 2), baseline, 0x98);
    if (!r->memory[0x8009]) {
        cache_store(r, slot, index);
        cache_store(r, slot + 1, *box);
        if (index_cursor)
            r->memory[0x8004] = (uint8_t)(r->memory[0x8004] - box->height + box->depth - index.depth + 5);
        restore_cursor(r, previous_cursor);
    }
    box->width = (uint16_t)(box->width + index.width - 2);
    box->height = (uint8_t)(box->height + index.height - 5);
    return (uint16_t)(stop + 1);
}

static void parenthesis(fx_render *r, uint16_t x, uint8_t baseline,
                         fx_box box, int closing)
{
    if (box.height <= fx_font_height(r)) {
        uint8_t text[2] = {closing ? ')' : '(', 0};
        world_text(r, text, x, baseline);
        return;
    }
    x = (uint16_t)(x + (closing ? 3 : 2));
    uint8_t bottom = (uint8_t)(baseline + box.depth - 3);
    uint8_t top = (uint8_t)(bottom - box.height + 6);
    world_vertical(r, x, top, bottom);
    for (unsigned n = 0; n < 2; ++n) {
        x = (uint16_t)(x + (closing ? -1 : 1));
        world_pixel(r, x, --top);
        world_pixel(r, x, ++bottom);
    }
}

/* 0x8b14: find a construct's next top-level parameter. The skipped child
 * can itself contain arbitrary B8/B9-delimited constructs. */
static uint16_t parameter_after(fx_render *r, uint16_t pointer)
{
    unsigned level = 1;
    for (unsigned scanned = 0; scanned < 65536; ++scanned, ++pointer) {
        uint8_t token = read_byte(r, pointer);
        if (!token) return (uint16_t)(pointer + 1);
        if (token == 0xb8) ++level;
        else if (token == 0xb9) {
            if (!--level) return (uint16_t)(pointer + 1);
        } else if (token == 0xba && level == 1)
            return (uint16_t)(pointer + 1);
    }
    return 0;
}

static uint16_t log_base(fx_render *r, uint16_t pointer, fx_box *box,
                          uint16_t x, uint8_t baseline)
{
    unsigned slot;
    if (!allocate_slots(r, 1, &slot)) return 0;
    uint8_t previous_cursor = suspend_cursor(r);
    static const uint8_t prefix[] = {'l', 'o', 'g', 0};
    world_text(r, prefix, x, baseline);
    x = (uint16_t)(x + 18);
    fx_box base = cache_box(r, slot);
    uint8_t original_depth = fx_font_depth(r);
    uint8_t depth = (uint8_t)(base.height + original_depth - 5);
    uint8_t previous_font = fx_select_small_font(r);
    uint16_t stop = fx_layout_sequence(r, (uint16_t)(pointer + 2), &base, x,
        r->memory[0x8009] ? (uint8_t)(baseline + depth - base.depth) : baseline);
    if (!stop) return 0;
    cache_store(r, slot, base);
    r->memory[0x811f] = previous_font;
    depth = (uint8_t)(base.height + fx_font_depth(r) - 5);
    if (!r->memory[0x8009] && r->memory[0x800a])
        r->memory[0x8004] = (uint8_t)(r->memory[0x8004] + depth - base.depth);
    x = (uint16_t)(x + base.width);
    stop = fx_layout_sequence(r, (uint16_t)(stop + 1), box,
                              (uint16_t)(x + 6), baseline);
    if (!stop) return 0;
    parenthesis(r, x, baseline, *box, 0);
    parenthesis(r, (uint16_t)(x + box->width + 6), baseline, *box, 1);
    box->width = (uint16_t)(box->width + base.width + 30);
    base.depth = depth;
    base.height = (uint8_t)(base.height + fx_font_height(r) - 5);
    fx_merge_vertical(box, &base);
    restore_cursor(r, previous_cursor);
    return stop;
}

static uint16_t derivative(fx_render *r, uint16_t pointer, fx_box *box,
                            uint16_t x, uint8_t baseline)
{
    static const uint8_t d[] = {'d', 0}, dx[] = {'d', 'x', 0}, equals[] = {'x', '=', 0};
    uint8_t previous_font = fx_select_small_font(r);
    world_text(r, d, (uint16_t)(x + 4), (uint8_t)(baseline - 4));
    world_text(r, dx, (uint16_t)(x + 1), (uint8_t)(baseline + 5));
    r->memory[0x811f] = previous_font;
    world_horizontal(r, (uint16_t)(x + 1), (uint16_t)(x + 13), baseline);
    uint16_t stop = fx_layout_sequence(r, (uint16_t)(pointer + 2), box,
                                       (uint16_t)(x + 20), baseline);
    if (!stop) return 0;
    parenthesis(r, (uint16_t)(x + 14), baseline, *box, 0);
    parenthesis(r, (uint16_t)(x + 20 + box->width), baseline, *box, 1);
    previous_font = fx_select_small_font(r);
    uint16_t marker_x = (uint16_t)(x + box->width + 26);
    world_vertical(r, marker_x, (uint8_t)(baseline - 4), (uint8_t)(baseline + 7));
    world_text(r, equals, (uint16_t)(marker_x + 3), (uint8_t)(baseline + 5));
    fx_box point;
    stop = fx_layout_sequence(r, (uint16_t)(stop + 1), &point,
                              (uint16_t)(marker_x + 15), (uint8_t)(baseline + 5));
    if (!stop) return 0;
    point.depth = (uint8_t)(point.depth + 5);
    r->memory[0x811f] = previous_font;
    box->width = (uint16_t)(box->width + point.width + 42);
    fx_merge_vertical(box, &point);
    fx_box ornament = {0, 16, 8};
    fx_merge_vertical(box, &ornament);
    return stop;
}

static void sigma_or_product(fx_render *r, uint16_t x, uint8_t baseline, uint8_t token)
{
    if (token == 0x69) {
        world_pixel(r, x, baseline);
        for (unsigned n = 1; n <= 4; ++n) {
            world_pixel(r, (uint16_t)(x - n), (uint8_t)(baseline - n));
            world_pixel(r, (uint16_t)(x - n), (uint8_t)(baseline + n));
        }
        world_horizontal(r, (uint16_t)(x - 3), (uint16_t)(x + 3), (uint8_t)(baseline - 4));
        world_horizontal(r, (uint16_t)(x - 3), (uint16_t)(x + 3), (uint8_t)(baseline + 4));
        world_pixel(r, (uint16_t)(x + 3), (uint8_t)(baseline - 3));
        world_pixel(r, (uint16_t)(x + 3), (uint8_t)(baseline + 3));
    } else {
        world_horizontal(r, (uint16_t)(x - 3), (uint16_t)(x + 3), (uint8_t)(baseline - 4));
        world_vertical(r, (uint16_t)(x - 2), (uint8_t)(baseline - 4), (uint8_t)(baseline + 4));
        world_vertical(r, (uint16_t)(x + 2), (uint8_t)(baseline - 4), (uint8_t)(baseline + 4));
        world_horizontal(r, (uint16_t)(x - 3), (uint16_t)(x - 1), (uint8_t)(baseline + 4));
        world_horizontal(r, (uint16_t)(x + 1), (uint16_t)(x + 3), (uint8_t)(baseline + 4));
    }
}

static uint16_t sum_or_product(fx_render *r, uint16_t pointer, fx_box *box,
                                uint16_t x, uint8_t baseline)
{
    unsigned slot;
    if (!allocate_slots(r, 2, &slot)) return 0;
    uint8_t previous_cursor = suspend_cursor(r), cursor_part = 0;
    uint16_t lower_pointer = parameter_after(r, (uint16_t)(pointer + 2));
    if (!lower_pointer) return 0;
    uint8_t previous_font = fx_select_small_font(r);
    fx_box lower = cache_box(r, slot), upper = cache_box(r, slot + 1);
    uint16_t column = lower.width > upper.width ? lower.width : upper.width;
    if (column < 9) column = 9;
    uint8_t bound_depth = (uint8_t)(lower.height + 5);
    if (r->memory[0x8009]) {
        static const uint8_t equals[] = {'x', '=', 0};
        uint16_t lower_x = (uint16_t)(x + ((uint16_t)(column - lower.width) >> 1));
        uint8_t lower_y = (uint8_t)(baseline + bound_depth - lower.depth);
        world_text(r, equals, lower_x, lower_y);
    }
    uint16_t stop = fx_layout_sequence(r, lower_pointer, &lower,
        r->memory[0x8009] ? (uint16_t)(x + ((uint16_t)(column - lower.width) >> 1) + 12) : (uint16_t)(x + 12),
        r->memory[0x8009] ? (uint8_t)(baseline + bound_depth - lower.depth) : baseline);
    cache_store(r, slot, lower);
    if (!stop) return 0;
    if (!r->memory[0x8009] && r->memory[0x800a]) cursor_part = 2;
    stop = fx_layout_sequence(r, (uint16_t)(stop + 1), &upper,
        r->memory[0x8009] ? (uint16_t)(x + ((uint16_t)(column - upper.width) >> 1)) : x,
        r->memory[0x8009] ? (uint8_t)(baseline - upper.depth - 5) : baseline);
    if (!stop) return 0;
    if (!r->memory[0x8009] && r->memory[0x800a] && !cursor_part) cursor_part = 3;
    if (!r->memory[0x8009]) {
        lower.width = (uint16_t)(lower.width + 12);
        cache_store(r, slot, lower);
        cache_store(r, slot + 1, upper);
        column = lower.width > upper.width ? lower.width : upper.width;
        if (column < 9) column = 9;
        bound_depth = (uint8_t)(lower.height + 5);
        if (cursor_part == 2) {
            adjust_cursor_x(r, (uint16_t)((uint16_t)(column - lower.width) >> 1));
            r->memory[0x8004] = (uint8_t)(r->memory[0x8004] + bound_depth - lower.depth);
        } else if (cursor_part == 3) {
            adjust_cursor_x(r, (uint16_t)((uint16_t)(column - upper.width) >> 1));
            r->memory[0x8004] = (uint8_t)(r->memory[0x8004] - upper.depth - 5);
        }
    }
    uint16_t final_stop = stop;
    r->memory[0x811f] = previous_font;
    stop = fx_layout_sequence(r, (uint16_t)(pointer + 2), box,
                              (uint16_t)(x + column + 5), baseline);
    if (!stop) return 0;
    parenthesis(r, (uint16_t)(x + column - 1), baseline, *box, 0);
    parenthesis(r, (uint16_t)(x + column + box->width + 5), baseline, *box, 1);
    box->width = (uint16_t)(box->width + column + 12);
    upper.height = (uint8_t)(upper.height + lower.height + 10);
    upper.depth = bound_depth;
    fx_merge_vertical(box, &upper);
    sigma_or_product(r, (uint16_t)(x + (column >> 1)), baseline, read_byte(r, pointer));
    restore_cursor(r, previous_cursor);
    return final_stop;
}

static void integral_ornament(fx_render *r, uint16_t x, uint8_t baseline, fx_box bounds)
{
    x = (uint16_t)(x + 2);
    uint8_t bottom = (uint8_t)(baseline + bounds.depth - 2);
    uint8_t top = (uint8_t)(bottom - bounds.height + 4);
    world_vertical(r, x, top, bottom);
    world_pixel(r, (uint16_t)(x + 1), (uint8_t)(top - 1));
    world_pixel(r, (uint16_t)(x - 1), (uint8_t)(bottom + 1));
    world_pixel(r, (uint16_t)(x + 2), top);
    world_pixel(r, (uint16_t)(x - 2), bottom);
}

static uint16_t integral(fx_render *r, uint16_t pointer, fx_box *box,
                          uint16_t x, uint8_t baseline)
{
    unsigned slot;
    if (!allocate_slots(r, 2, &slot)) return 0;
    uint8_t previous_cursor = suspend_cursor(r), cursor_part = 0;
    uint16_t lower_pointer = parameter_after(r, (uint16_t)(pointer + 2));
    if (!lower_pointer) return 0;
    uint8_t previous_font = fx_select_small_font(r);
    fx_box lower = cache_box(r, slot), upper = cache_box(r, slot + 1);
    uint8_t bound_depth = (uint8_t)(lower.height + 2);
    uint16_t stop = fx_layout_sequence(r, lower_pointer, &lower, (uint16_t)(x + 6),
        r->memory[0x8009] ? (uint8_t)(baseline + bound_depth - lower.depth) : baseline);
    if (!stop) return 0;
    if (!r->memory[0x8009] && r->memory[0x800a]) cursor_part = 2;
    stop = fx_layout_sequence(r, (uint16_t)(stop + 1), &upper, (uint16_t)(x + 6),
        r->memory[0x8009] ? (uint8_t)(baseline - upper.depth - 3) : baseline);
    cache_store(r, slot + 1, upper);
    if (!stop) return 0;
    if (!r->memory[0x8009] && r->memory[0x800a] && !cursor_part) cursor_part = 3;
    if (!r->memory[0x8009]) cache_store(r, slot, lower);
    uint16_t final_stop = stop;
    bound_depth = (uint8_t)(lower.height + 2);
    if (!r->memory[0x8009]) {
        if (cursor_part == 2)
            r->memory[0x8004] = (uint8_t)(r->memory[0x8004] + bound_depth - lower.depth);
        else if (cursor_part == 3)
            r->memory[0x8004] = (uint8_t)(r->memory[0x8004] - upper.depth - 3);
    }
    uint16_t column = (uint16_t)((lower.width > upper.width ? lower.width : upper.width) + 7);
    r->memory[0x811f] = previous_font;
    stop = fx_layout_sequence(r, (uint16_t)(pointer + 2), box,
                              (uint16_t)(x + column), baseline);
    if (!stop) return 0;
    box->width = (uint16_t)(box->width + column + 12);
    lower.height = (uint8_t)(lower.height + upper.height + 6);
    lower.depth = bound_depth;
    fx_merge_vertical(box, &lower);
    static const uint8_t dx[] = {'d', 'x', 0};
    world_text(r, dx, (uint16_t)(x + box->width - 12), baseline);
    integral_ornament(r, (uint16_t)(x + 1), baseline, lower);
    restore_cursor(r, previous_cursor);
    return final_stop;
}

static uint16_t repetend(fx_render *r, uint16_t pointer, fx_box *box,
                          uint16_t x, uint8_t baseline)
{
    uint16_t scan = (uint16_t)(pointer + 2);
    if (read_byte(r, scan) == '!') ++scan;
    while (read_byte(r, scan) != 0xb9) {
        uint8_t token = read_byte(r, scan++);
        if (token < '0' || token > '9') return 0;
    }
    uint8_t style = r->rom_size > 0x1ffe2 ? r->rom[0x1ffe2] : 0;
    uint16_t child_x = (uint16_t)(x + (style == 3 ? 6 : 1));
    uint16_t stop = fx_layout_sequence(r, (uint16_t)(pointer + 2), box, child_x, baseline);
    if (!stop) return 0;
    uint8_t next = read_byte(r, (uint16_t)(stop + 1));
    if (next >= '0' && next <= '9') return 0;
    if (style == 3) box->width = (uint16_t)(box->width + 12);
    else { box->height += 2; box->width = (uint16_t)(box->width + 2); }
    if (style == 2) box->depth += 2;
    if (style <= 1) baseline = (uint8_t)(baseline - fx_font_ascent(r) - 1);
    if (style == 2) baseline = (uint8_t)(baseline + fx_font_depth(r) + 1);
    if (style == 0) {
        world_pixel(r, (uint16_t)(child_x + 3), baseline);
        world_pixel(r, (uint16_t)(child_x + box->width - 5), baseline);
    } else if (style == 1 || style == 2) {
        world_horizontal(r, child_x, (uint16_t)(child_x + box->width - 2), baseline);
    } else {
        static const uint8_t left[] = {0xad, 0}, right[] = {0xae, 0};
        world_text(r, left, (uint16_t)(child_x - 6), baseline);
        world_text(r, right, (uint16_t)(child_x + box->width - 12), baseline);
    }
    return stop;
}

static uint8_t layout_kind(fx_render *r, uint16_t pointer)
{
    uint8_t token = read_byte(r, pointer);
    uint8_t kind = fx_construct_class(r, token);
    if (kind == 1) {
        uint8_t next = read_byte(r, (uint16_t)(pointer + 1));
        if (next != 0xb8 && next != 0xbb && next != 0xbd)
            kind = token == 0xae || token == 0x7c ? 13 : 10;
    }
    return kind;
}

/* 0x8a6c: determine whether this ')' closes a recursive parenthesis frame,
 * without confusing parentheses inside B8/B9-delimited child expressions. */
static int closes_parenthesis_frame(fx_render *r, uint16_t pointer)
{
    uint16_t root = read_word(r, 0x812c);
    unsigned parentheses = 1, children = 1;
    if (pointer == root) return 0;
    do {
        --pointer;
        uint8_t kind = layout_kind(r, pointer);
        if (children == 1 && kind == 9) ++parentheses;
        else if (children == 1 && (kind == 8 || kind == 10)) {
            if (!--parentheses) return 1;
        } else if (kind == 3) ++children;
        else if (kind == 2) {
            if (!--children) return 0;
        } else if (kind == 5 && children == 1) return 0;
    } while (pointer != root);
    return 0;
}

uint16_t fx_layout_sequence(fx_render *r, uint16_t pointer, fx_box *box,
                            uint16_t x, uint8_t baseline)
{
    ++r->memory[0x8007];
    if (r->memory[0x8007] > 27) { --r->memory[0x8007]; return 0; }
    box->width = 0;
    box->height = fx_font_height(r);
    box->depth = fx_font_depth(r);
    fx_box child = *box;
    uint16_t returned = pointer;
    /* Firmware pointers wrap. The cap only protects a malformed stream with
     * no stopping delimiter from looping forever in the portable API. */
    for (unsigned scanned = 0; scanned < 65536; ++scanned) {
        if ((uint8_t)(pointer - r->memory[0x812c]) == r->memory[0x8114]) {
            cursor_at(r, pointer, (uint16_t)(x + box->width), baseline);
            if (!r->memory[0x8009]) r->memory[0x800a] = 1;
        }
        uint8_t token = read_byte(r, pointer);
        uint8_t kind = layout_kind(r, pointer);
        if (kind == 3 || kind == 5 || kind == 11) { returned = pointer; break; }
        if (kind == 1) {
            ++r->memory[0x8007];
            uint16_t stop;
            switch (token) {
            case 0x98: case 0x63:
                stop = root_or_absolute(r, pointer, &child, (uint16_t)(x + box->width), baseline); break;
            case 0x5e: case 0x73: case 0x93:
                stop = power(r, pointer, &child, (uint16_t)(x + box->width), baseline); break;
            case 0xae: case 0x7c:
                stop = fraction(r, pointer, &child, (uint16_t)(x + box->width), baseline); break;
            case 0x9f:
                stop = nth_root(r, pointer, &child, (uint16_t)(x + box->width), baseline); break;
            case 0x68:
                stop = log_base(r, pointer, &child, (uint16_t)(x + box->width), baseline); break;
            case 0x6b:
                stop = derivative(r, pointer, &child, (uint16_t)(x + box->width), baseline); break;
            case 0x69: case 0x5d:
                stop = sum_or_product(r, pointer, &child, (uint16_t)(x + box->width), baseline); break;
            case 0x6a:
                stop = integral(r, pointer, &child, (uint16_t)(x + box->width), baseline); break;
            case 0xa4:
                stop = repetend(r, pointer, &child, (uint16_t)(x + box->width), baseline); break;
            default: stop = 0; break; /* malformed or unknown construct token */
            }
            if (!stop) { returned = 0; break; }
            --r->memory[0x8007];
            if (child.height > 62) { returned = 0; break; }
            box->width = (uint16_t)(box->width + child.width);
            fx_merge_vertical(box, &child);
            pointer = (uint16_t)(stop + 1);
            continue;
        }
        if (kind == 9) {
            parenthesis(r, (uint16_t)(x + box->width), baseline, *box, 1);
            box->width = (uint16_t)(box->width + 6);
            child = *box;
            if (closes_parenthesis_frame(r, pointer)) { returned = pointer; break; }
            ++pointer;
            returned = pointer;
            continue;
        }
        if (kind == 8 || kind == 10) {
            if (kind == 10) {
                unsigned prefix = token_glyphs(r, token, (uint16_t)(x + box->width), baseline, 1);
                box->width = (uint16_t)(box->width + prefix);
            }
            uint16_t current_x = (uint16_t)(x + box->width);
            uint16_t stop = fx_layout_sequence(r, (uint16_t)(pointer + 1), &child,
                                               (uint16_t)(current_x + 6), baseline);
            if (!stop) { returned = 0; break; }
            parenthesis(r, current_x, baseline, child, 0);
            box->width = (uint16_t)(box->width + child.width + 6);
            fx_merge_vertical(box, &child);
            pointer = stop;
            returned = pointer;
            if (read_byte(r, stop) != ')') break;
            ++pointer;
            returned = pointer;
            continue;
        }
        if (kind == 2 || kind == 4 || kind == 6 || kind == 7 || kind > 13
            ) {
            returned = 0; break;
        }
        if (!token || (token == ':' && (r->memory[0x80fe] & 0x40))) {
            returned = pointer; break;
        }
        child.height = fx_font_height(r);
        child.depth = fx_font_depth(r);
        box->width = (uint16_t)(box->width + token_glyphs(r, token,
                                     (uint16_t)(x + box->width), baseline, 0));
        ++pointer;
        returned = pointer;
    }
    --r->memory[0x8007];
    return returned;
}
