/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_simulator_engine.h"
#include "fx_simulator_input.h"
#include "../parse/fx_eval.h"
#include "../format/fx_format.h"
#include "../format/fx_format_base.h"
#include "../render/fx_render.h"
#include "../render/fx_result_linear.h"
#include "../render/fx_result_complex.h"
#include "../render/fx_result_pair.h"
#include "../render/fx_result_special.h"
#include "../ui/fx_error_display.h"
#include "../data/fx_rom_data.h"

#include <stdlib.h>
#include <string.h>

enum { INPUT_LIMIT = FXSIM_INPUT_MAX_BYTES,
       INPUT_TOKEN_CAPACITY = INPUT_LIMIT * 2 + 1,
       TOKEN_LIMIT = 1024, PLAIN_LIMIT = 1024 };

struct fx_simulator {
    fx_eval_variables variables;
    fx_number prior_answer, random_seed;
};

typedef struct {
    char *data;
    size_t capacity, length;
} text_writer;

static void character(text_writer *w, char c)
{
    if (w->length + 1 < w->capacity) w->data[w->length] = c;
    ++w->length;
}

static void text(text_writer *w, const char *value)
{
    while (*value) character(w, *value++);
}

static void finish(text_writer *w)
{
    if (w->capacity)
        w->data[w->length < w->capacity ? w->length : w->capacity - 1] = 0;
}

static void integer(text_writer *w, int value)
{
    unsigned magnitude;
    char digits[12];
    size_t length = 0;
    if (value < 0) {
        character(w, '-');
        magnitude = (unsigned)(-(value + 1)) + 1u;
    } else magnitude = (unsigned)value;
    do { digits[length++] = (char)('0' + magnitude % 10u); magnitude /= 10u; } while (magnitude);
    while (length) character(w, digits[--length]);
}

static void hexadecimal(text_writer *w, const uint8_t *bytes, size_t length)
{
    static const char alphabet[] = "0123456789abcdef";
    for (size_t n = 0; n < length; ++n) {
        character(w, alphabet[bytes[n] >> 4]);
        character(w, alphabet[bytes[n] & 15]);
    }
}

static void quoted(text_writer *w, const char *value)
{
    static const char alphabet[] = "0123456789abcdef";
    character(w, '"');
    while (*value) {
        unsigned char c = (unsigned char)*value++;
        if (c == '"' || c == '\\') { character(w, '\\'); character(w, (char)c); }
        else if (c < 32) {
            text(w, "\\u00"); character(w, alphabet[c >> 4]); character(w, alphabet[c & 15]);
        } else character(w, (char)c);
    }
    character(w, '"');
}

fx_simulator *fxsim_create(void)
{
    return calloc(1, sizeof(fx_simulator));
}

void fxsim_destroy(fx_simulator *simulator)
{
    free(simulator);
}

void fxsim_reset(fx_simulator *simulator)
{
    if (simulator) memset(simulator, 0, sizeof *simulator);
}

static int successful(fx_eval_status status)
{
    return status == FX_EVAL_OK || status == FX_EVAL_POLAR_PAIR ||
           status == FX_EVAL_RECTANGULAR_PAIR || status == FX_EVAL_QUOTIENT_PAIR;
}

static uint8_t selected_base(unsigned mode)
{
    static const uint8_t masks[6] = {FX_BASE_DEC, FX_BASE_DEC, FX_BASE_BIN,
                                    FX_BASE_OCT, FX_BASE_DEC, FX_BASE_HEX};
    return masks[mode];
}

static int copy_tokens(uint8_t *tokens, size_t *length, const uint8_t *memory,
                       uint16_t address)
{
    size_t n = 0;
    while (n + 1 < TOKEN_LIMIT && memory[(uint16_t)(address + n)]) {
        tokens[n] = memory[(uint16_t)(address + n)]; ++n;
    }
    if (memory[(uint16_t)(address + n)]) return -1;
    tokens[n] = 0; *length = n; return 0;
}

/* Human-readable transliteration of formatter-owned DISPLAY tokens. This
 * does not recompute numbers or recognize a value from its approximation. */
static int plain_sequence(text_writer *w, const uint8_t *tokens, size_t length,
                          size_t *position, int field, unsigned depth)
{
    if (depth > 32) return -1;
    while (*position < length) {
        uint8_t token = tokens[(*position)++];
        if (token == 0xb9 && field) return 0;
        if (token == 0xae) {
            if (*position + 1 >= length || tokens[*position] != 0xbb || tokens[*position+1] != 0xb8)
                return -1;
            *position += 2; character(w, '(');
            if (plain_sequence(w, tokens, length, position, 1, depth+1)) return -1;
            if (*position >= length || tokens[(*position)++] != 0xb8) return -1;
            text(w, ")/(");
            if (plain_sequence(w, tokens, length, position, 1, depth+1)) return -1;
            if (*position >= length || tokens[(*position)++] != 0xbc) return -1;
            character(w, ')');
        } else if (token == 0x98) {
            if (*position >= length || tokens[(*position)++] != 0xb8) return -1;
            text(w, "sqrt(");
            if (plain_sequence(w, tokens, length, position, 1, depth+1)) return -1;
            character(w, ')');
        } else if (token == 0x82) text(w, "pi");
        else if (token == 0x80) character(w, 'i');
        else if (token == 0x60) character(w, '-');
        else if (token == 0x93) character(w, '/');
        else if (token == 0x90 || token == 0xe0) character(w, 'e');
        else if (token == 0x91 || token == 0xe1) character(w, '+');
        else if (token == 0x92 || token == 0xe2) character(w, '-');
        else if (token >= 0xa0 && token <= 0xa9) character(w, (char)('0'+token-0xa0));
        else if (token >= 0xf0 && token <= 0xf9) character(w, (char)('0'+token-0xf0));
        else if (token == 0xaf || token == 0x88) text(w, " angle ");
        else if (token == 13) text(w, "; ");
        else if (token >= 32 && token <= 126) character(w, (char)token);
        else return -1;
    }
    return field ? -1 : 0;
}

static void plain_tokens(char out[PLAIN_LIMIT], const uint8_t *tokens, size_t length)
{
    text_writer w = {out, PLAIN_LIMIT, 0};
    size_t position = 0;
    if (plain_sequence(&w, tokens, length, &position, 0, 0) || w.length >= PLAIN_LIMIT)
        out[0] = 0;
    else finish(&w);
}

static void error_text(char out[64], unsigned status)
{
    size_t n = 0;
    if (status >= 1 && status <= 13) {
        size_t table = 0x113e + 2u * (status - 1u);
        uint16_t address = (uint16_t)(fx_rom_data[table] | (uint16_t)fx_rom_data[table+1] << 8);
        while (n + 1 < 64 && address < 0x8000 && fx_rom_data[address]) {
            uint8_t c = fx_rom_data[address++];
            out[n++] = c >= 32 && c < 127 ? (char)c : '?';
        }
    }
    out[n] = 0;
    if (!n) strcpy(out, "Calculator error");
}

static int present(uint8_t *memory, const uint8_t *input, size_t input_length,
                   unsigned mode, unsigned angle, unsigned math,
                   fx_eval_status status, const fx_eval_result *result,
                   uint8_t tokens[TOKEN_LIMIT], size_t *token_length)
{
    fx_render render = {fx_rom_data, FX_ROM_DATA_SIZE, memory};
    fx_box box;
    fx_format_options options = fx_format_default_options();
    fx_format_result formatted = {0, 0, 0};
    int display;
    memory[0x80f9] = mode >= 2 ? 2 : mode == FXSIM_CMPLX ? 0xc4 : 0xc1;
    memory[0x80fa] = selected_base(mode); memory[0x80fc] = 1;
    memory[0x80f5] = 0xf0; memory[0x8100] = 13;
    memory[0x8104] = 1; memory[0x8105] = (uint8_t)(4+angle);
    memory[0x8106] = (uint8_t)math; memory[0x8108] = 1;
    memory[0x811f] = 10; memory[0x8121] = 1;
    memory[0x812c] = 0; memory[0x812d] = 0xa0;
    memcpy(memory+0xa000, input, input_length);
    memcpy(memory+0x8300, result->value, sizeof result->value);
    if (status == FX_EVAL_POLAR_PAIR) {
        if (mode == FXSIM_CMPLX) memory[0x8101] = 2;
        else memory[0x80ff] = 18;
    } else if (status == FX_EVAL_RECTANGULAR_PAIR) {
        if (mode == FXSIM_CMPLX) memory[0x8101] = 1;
        else memory[0x80ff] = 17;
    } else if (status == FX_EVAL_QUOTIENT_PAIR) {
        if (result->value[1].bytes[0] == 0x70) memset(memory+0x830a, 0, 10);
        else memory[0x80ff] = 20;
    }
    if (mode >= 2) {
        if (fx_format_base(&result->value[0], selected_base(mode), tokens,
                           TOKEN_LIMIT, &formatted) != FX_FORMAT_OK) return -1;
        *token_length = formatted.length;
        display = fx_display_special_real_result(&render, 0x8300, &box);
    } else if (memory[0x80ff] & 16) {
        display = fx_display_pair_result(&render, 0x8300, &box);
        if (display == 1 && copy_tokens(tokens, token_length, memory,
                                        math ? 0x8398 : 0x9838)) return -1;
    } else if (mode == FXSIM_CMPLX) {
        display = fx_display_complex_result(&render, 0x8300, &box);
        if (display == 1 && copy_tokens(tokens, token_length, memory,
                                        math ? 0x8398 : 0x9838)) return -1;
    } else {
        options.math_output = (uint8_t)math; options.decimal_dot = 1;
        if (fx_format_number(&result->value[0], &options, tokens,
                             TOKEN_LIMIT, &formatted) != FX_FORMAT_OK) return -1;
        *token_length = formatted.length;
        display = math ? fx_display_real_math_result(&render, 0x8300, &box) :
                         fx_display_real_linear_result(&render, 0x8300, &box);
    }
    if (display != 1) return -1;
    fx_flush_framebuffer(&render);
    return 0;
}

static void commit_answer(fx_simulator *session, unsigned mode,
                          fx_eval_status status, const fx_eval_result *result)
{
    if (mode == FXSIM_COMP)
        session->prior_answer = session->variables.values[FX_VARIABLE_ANS][0];
    session->variables.values[FX_VARIABLE_ANS][0] = result->value[0];
    /*522A writes the imaginary bank only in CMPLX. Ordinary real Ans
     * publication retains its previous imaginary companion across modes. */
    if (mode == FXSIM_CMPLX) {
        if (status != FX_EVAL_QUOTIENT_PAIR)
            session->variables.values[FX_VARIABLE_ANS][1] = result->value[1];
        else fx_number_zero(&session->variables.values[FX_VARIABLE_ANS][1]);
    }
}

int fxsim_evaluate(fx_simulator *simulator, const char *expression,
                  unsigned mode, unsigned angle, unsigned math,
                  char *out, size_t capacity)
{
    uint8_t input[INPUT_TOKEN_CAPACITY], tokens[TOKEN_LIMIT] = {0};
    char plain[PLAIN_LIMIT] = {0}, error[64] = {0};
    size_t input_length = 0, error_position = 0, token_length = 0, ascii_length = 0;
    fx_eval_result result = {0};
    fx_eval_status status = FX_EVAL_UNIMPLEMENTED;
    const char *wire_status = "unsupported", *position_kind = "native-token";
    fx_simulator session;
    uint8_t *memory;
    int encoded;
    text_writer w = {out, capacity, 0};
    if (out && capacity) out[0] = 0;
    if (!simulator || !expression || !out || !capacity || mode > FXSIM_HEX ||
        angle > FXSIM_GRAD || math > 1) return -1;
    while (ascii_length <= INPUT_LIMIT && expression[ascii_length]) ++ascii_length;
    if (ascii_length > INPUT_LIMIT) return -1;
    memory = calloc(FX_RENDER_MEMORY_BYTES, 1);
    if (!memory) return -1;
    session = *simulator;
    encoded = fxsim_encode_expression_mode(expression, mode, input, sizeof input,
                                            &input_length, &error_position);
    if (encoded) {
        position_kind = "ascii-byte";
        strcpy(error, "Unsupported expression text");
    } else {
        fx_eval_options options = fx_eval_default_options();
        fx_eval_environment environment = fx_eval_default_environment();
        fx_eval_state state = {&session.variables, NULL};
        options.calculation_context = mode >= 2 ? 2 : mode == FXSIM_CMPLX ? 0xc4 : 0xc1;
        options.math_output = (uint8_t)math; options.angle_unit = (uint8_t)(4+angle);
        environment.selected_base = selected_base(mode);
        status = fx_evaluate_prepared_random(input, input_length, &options, &environment,
            &state, NULL, NULL, &session.prior_answer, &session.random_seed, NULL, &result);
        error_position = result.consumed;
        if (successful(status)) {
            wire_status = "ok";
            commit_answer(&session, mode, status, &result);
            if (present(memory, input, input_length, mode, angle, math, status,
                        &result, tokens, &token_length)) {
                wire_status = "unsupported";
                strcpy(error, "Result presentation unavailable");
                token_length = 0;
            } else plain_tokens(plain, tokens, token_length);
        } else if (status > 0) {
            fx_platform platform = {fx_rom_data, FX_ROM_DATA_SIZE, memory, 0, FX_MEMORY_OK};
            wire_status = "error"; error_text(error, (unsigned)status);
            (void)fx_error_display(&platform, (uint8_t)status);
        } else strcpy(error, status == FX_EVAL_RESOURCE_LIMIT ?
                            "Evaluator resource limit" : "Unsupported expression");
    }
    text(&w, "{\"status\":"); quoted(&w, wire_status);
    text(&w, ",\"native_status\":"); integer(&w, status);
    text(&w, ",\"error\":"); if (error[0]) quoted(&w, error); else text(&w, "null");
    text(&w, ",\"error_position\":"); integer(&w, (int)error_position);
    text(&w, ",\"error_position_kind\":"); quoted(&w, position_kind);
    text(&w, ",\"real\":\""); hexadecimal(&w, result.value[0].bytes, 10);
    text(&w, "\",\"imag\":\""); hexadecimal(&w, result.value[1].bytes, 10);
    text(&w, "\",\"tokens\":\""); hexadecimal(&w, tokens, token_length);
    text(&w, "\",\"framebuffer\":\"");
    for (unsigned row = 0; row < 32; ++row)
        hexadecimal(&w, memory+FX_LCD_FRAMEBUFFER+row*16, 12);
    text(&w, "\",\"width\":96,\"height\":32,\"plain\":"); quoted(&w, plain);
    text(&w, "}"); finish(&w); free(memory);
    if (w.length >= capacity) { out[0] = 0; return -1; }
    *simulator = session;
    return 0;
}
