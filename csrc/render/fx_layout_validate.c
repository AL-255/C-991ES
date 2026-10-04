#include "fx_layout_validate.h"

static uint8_t byte_at(const fx_render *r, uint16_t address)
{
    return address < 0x8000 ? (address < r->rom_size ? r->rom[address] : 0)
                            : r->memory[address];
}

static uint8_t kind_at(const fx_render *r, uint16_t pointer)
{
    uint8_t token = byte_at(r, pointer), kind = fx_construct_class(r, token);
    if (kind == 1) {
        uint8_t next = byte_at(r, (uint16_t)(pointer + 1));
        if (next != 0xb8 && next != 0xbb && next != 0xbd)
            kind = token == 0xae || token == 0x7c ? 13 : 10;
    }
    return kind;
}

static uint8_t construct_type(const fx_render *r, uint16_t pointer)
{
    if (kind_at(r, pointer) != 1) return 5;
    uint16_t address = (uint16_t)(0x2c64 + fx_construct_index(byte_at(r, pointer)));
    return byte_at(r, address);
}

static int signed_operator(uint8_t token)
{
    return token == '`' || token == '+' || token == '-';
}

static int numeric_token(uint8_t token)
{
    return (token >= '0' && token <= '9') || token == '.' || token == 't';
}

uint8_t fx_parameter_length(const fx_render *r, uint16_t pointer, uint8_t parameter)
{
    uint8_t type = construct_type(r, pointer), count = 0;
    if (parameter >= 1 && type == 0) return 0;
    if (parameter == 2 && type != 3 && type != 4) return 0;
    count = type == 2 ? 3 : type == 4 ? 4 : 2;
    if (!parameter) return count;
    pointer = (uint16_t)(pointer + count);
    unsigned scanned = 0;
    for (unsigned child = 0; child < parameter; ++child) {
        uint8_t depth = 1;
        for (; scanned < 65536; ++scanned) {
            uint8_t token = byte_at(r, pointer);
            if (!token) break;
            if (token == 0xb8) ++depth;
            else if (token == 0xb9) { if (!--depth) break; }
            else if (token == 0xba && depth == 1) break;
            ++count; ++pointer;
        }
        ++count; ++pointer;
        if (byte_at(r, pointer) == 0xb8) { ++count; ++pointer; }
        if (scanned == 65536) break;
    }
    return count;
}

uint8_t fx_construct_length(const fx_render *r, uint16_t pointer)
{
    uint8_t type = construct_type(r, pointer);
    uint8_t count = fx_parameter_length(r, pointer, 0);
    if (!count) return 0;
    pointer = (uint16_t)(pointer + count);
    uint8_t open = type == 2 || type == 4 ? 0xbb : 0xb8;
    uint8_t close = type == 2 || type == 4 ? 0xbc : 0xb9;
    uint8_t depth = 1;
    for (unsigned scanned = 0; scanned < 65536; ++scanned, ++count, ++pointer) {
        uint8_t token = byte_at(r, pointer);
        if (!token) break;
        if (token == open) ++depth;
        else if (token == close && !--depth) break;
    }
    return count;
}

uint8_t fx_parenthesis_length(const fx_render *r, uint16_t pointer)
{
    uint8_t count = 1, depth = 1;
    ++pointer;
    for (unsigned scanned = 0; scanned < 65536; ++scanned, ++count, ++pointer) {
        uint8_t token = byte_at(r, pointer);
        if (!token || (token == ':' && (r->memory[0x80fe] & 0x40))) break;
        uint8_t kind = kind_at(r, pointer);
        if (kind == 9) { if (!--depth) break; }
        else if (kind == 8 || kind == 10) ++depth;
        else if (kind == 1) {
            uint8_t child = fx_construct_length(r, pointer);
            count = (uint8_t)(count + child);
            pointer = (uint16_t)(pointer + child);
        } else if (kind == 3 || kind == 5) break;
    }
    return count;
}

uint8_t fx_field_length(const fx_render *r, uint16_t pointer)
{
    uint8_t count = 0, depth = 1;
    for (unsigned scanned = 0; scanned < 65536; ++scanned, ++count, ++pointer) {
        uint8_t token = byte_at(r, pointer);
        if (!token) break;
        if (token == 0xb8) ++depth;
        else if (token == 0xb9) { if (!--depth) break; }
        else if (token == 0xba && depth == 1) break;
    }
    return count;
}

uint8_t fx_atom_length(const fx_render *r, uint16_t pointer, uint8_t stop, uint8_t allow_signed)
{
    uint8_t count = 0;
    uint8_t token = byte_at(r, pointer), next = byte_at(r, (uint16_t)(pointer + 1));
    if (token == '!' && (next == 0xb9 || next == 0xba)) return 0;
    int had_sign = signed_operator(token);
    unsigned signs = 0;
    while (signed_operator(byte_at(r, pointer))) {
        ++count; ++pointer;
        if (++signs == 65536) return count;
    }
    if (had_sign && (!numeric_token(byte_at(r, pointer)) || !allow_signed)) return 0;
    for (unsigned scanned = 0; scanned < 65536; ++scanned) {
        uint8_t kind = kind_at(r, pointer);
        if (kind == 9 || kind == 3 || kind == 5 || kind == 11 || kind == 12 || kind == 13)
            return count;
        if (kind == 1) {
            uint8_t child = fx_construct_length(r, pointer);
            count = (uint8_t)(count + child);
            pointer = (uint16_t)(pointer + child);
            ++count;
        } else if (kind == 8 || kind == 10) {
            uint8_t child = fx_parenthesis_length(r, pointer);
            count = (uint8_t)(count + child);
            pointer = (uint16_t)(pointer + child);
            if (byte_at(r, pointer) != ')') return count;
            ++count;
        } else if (!numeric_token(byte_at(r, pointer))) {
            ++count;
        } else {
            uint8_t exponent = 0, point = 0;
            unsigned digits = 0;
            do {
                if (++digits == 65536) return count;
                token = byte_at(r, pointer);
                if (token == 't') {
                    if (exponent) break;
                    exponent = point = 1;
                    ++count; ++pointer;
                    while (signed_operator(byte_at(r, pointer))) {
                        ++count; ++pointer;
                        if (++digits == 65536) return count;
                    }
                } else {
                    if (token == '.') { if (point) break; point = 1; }
                    ++count; ++pointer;
                }
            } while (numeric_token(byte_at(r, pointer)));
            if (stop) return count;
            continue;
        }
        if (stop) return count;
        ++pointer;
    }
    return count;
}

static uint16_t expression_root(const fx_render *r)
{
    return (uint16_t)(r->memory[0x812c] | ((uint16_t)r->memory[0x812d] << 8));
}

uint16_t fx_owning_construct(const fx_render *r, uint16_t position, uint8_t *parameter)
{
    uint16_t pointer = position, root = expression_root(r);
    if (parameter) *parameter = 0;
    if (byte_at(r, pointer) == 0xbc) --pointer;
    if (byte_at(r, pointer) == 0xb9) --pointer;
    uint8_t depth = 1;
    for (unsigned scanned = 0; scanned < 65536 && pointer != root; ++scanned) {
        uint8_t token = byte_at(r, pointer--);
        if (token == 0xb9) ++depth;
        else if (token == 0xb8 && !--depth && byte_at(r, pointer) != 0xb9) {
            if (byte_at(r, pointer) == 0xbb) --pointer;
            if (byte_at(r, pointer) == 0xbd) --pointer;
            uint8_t distance = (uint8_t)(position - pointer);
            if (distance > fx_construct_length(r, pointer)) return 0;
            uint8_t type = construct_type(r, pointer);
            if (parameter && type && distance >= fx_parameter_length(r, pointer, 1)) {
                *parameter = 1;
                if (type != 1 && type != 2 && distance >= fx_parameter_length(r, pointer, 2))
                    *parameter = 2;
            }
            return pointer;
        }
    }
    return 0;
}

uint16_t fx_parenthesis_start(const fx_render *r, uint16_t pointer, uint8_t *matched)
{
    uint16_t root = expression_root(r);
    uint8_t children = 1, parentheses = 1;
    if (matched) *matched = 0;
    for (unsigned scanned = 0; scanned < 65536 && pointer != root; ++scanned) {
        uint8_t kind = kind_at(r, --pointer);
        if (children == 1 && kind == 9) ++parentheses;
        else if (children == 1 && (kind == 8 || kind == 10)) {
            if (!--parentheses) { if (matched) *matched = 1; return pointer; }
        } else if (kind == 3) ++children;
        else if (kind == 2) { if (!--children) return pointer; }
        else if (children == 1 && kind == 5) return pointer;
    }
    return pointer;
}

uint16_t fx_previous_atom_start(const fx_render *r, uint16_t position)
{
    uint16_t root = expression_root(r), pointer = (uint16_t)(position - 1);
    for (unsigned scanned = 0; scanned < 65536; ++scanned) {
        uint8_t kind = kind_at(r, pointer);
        if (kind == 8 || kind == 10 || kind == 2 || kind == 5 || kind >= 12)
            return (uint16_t)(pointer + 1);
        if (kind == 3 || kind == 7) {
            pointer = fx_owning_construct(r, pointer, 0);
        } else if (kind == 9) {
            uint8_t matched;
            pointer = fx_parenthesis_start(r, pointer, &matched);
            if (!matched && pointer != root) return (uint16_t)(pointer + 1);
        } else if (numeric_token(byte_at(r, pointer))) {
            for (unsigned number = 0; number < 65536; ++number) {
                if (pointer == root) return pointer;
                --pointer;
                if (signed_operator(byte_at(r, pointer))) {
                    uint16_t signs = pointer;
                    while (signed_operator(byte_at(r, signs))) {
                        if (signs == root) return (uint16_t)(pointer + 1);
                        --signs;
                    }
                    if (byte_at(r, signs) != 't') return (uint16_t)(pointer + 1);
                    pointer = signs;
                }
                if (!numeric_token(byte_at(r, pointer))) break;
            }
            continue;
        }
        if (pointer == root) return pointer;
        --pointer;
    }
    return 0;
}

int fx_mixed_whole_valid(const fx_render *r, uint16_t expression)
{
    uint8_t length = fx_atom_length(r, expression, 1, 1);
    if (!length) length = 1;
    if (length != fx_field_length(r, expression)) return 0;
    uint8_t token = byte_at(r, expression);
    return signed_operator(token) || numeric_token(token) || token == '(' || token == '!';
}
