/* SPDX-License-Identifier: GPL-3.0-only
 * Subsystem inspection CLI. Calculator key UI remains pending. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "parse/fx_tokens.h"
#include "parse/fx_eval.h"
#include "numeric/fx_numeric.h"
#include "format/fx_format.h"
#include "render/fx_render.h"
#include "data/fx_rom_data.h"

static int digit(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static int record_from_hex(fx_number *number, const char *text)
{
    unsigned i;
    if (strlen(text) != 20) return -1;
    for (i = 0; i < 10; ++i) {
        int high = digit(text[i * 2]), low = digit(text[i * 2 + 1]);
        if (high < 0 || low < 0) return -1;
        number->bytes[i] = (uint8_t)(high * 16 + low);
    }
    return 0;
}

static int input_from_hex(uint8_t *tokens, size_t capacity, const char *text, size_t *length)
{
    size_t i, characters = strlen(text);
    if (characters % 2 || characters / 2 + 1 > capacity) return -1;
    for (i = 0; i < characters / 2; ++i) {
        int high = digit(text[i * 2]), low = digit(text[i * 2 + 1]);
        if (high < 0 || low < 0) return -1;
        tokens[i] = (uint8_t)(high * 16 + low);
    }
    tokens[i++] = 0;
    *length = i;
    return 0;
}

static int byte_from_hex(unsigned *result, const char *text)
{
    char *end;
    unsigned long n = strtoul(text, &end, 16);
    if (!text[0] || *end || n > 255) return -1;
    *result = (unsigned)n;
    return 0;
}

static void usage(void)
{
    fputs("Subsystem probe for the high-level C firmware port (incomplete).\n"
          "  fx991c --token HEX_BYTE [HEX_CONTEXT]\n"
          "  fx991c --format HEX_10_BYTE_RECORD [--linear] [--mixed] [--decimal]\n"
          "  fx991c --eval HEX_INPUT_TOKENS [--pbm OUTPUT_FILE]\n"
          "Evaluation supports COMP arithmetic, compact fractions and square root; other functions report unsupported.\n", stderr);
}

static int write_result_bitmap(const char *path, const uint8_t *input, size_t length,
                               const fx_eval_result *evaluated)
{
    static uint8_t memory[FX_RENDER_MEMORY_BYTES];
    fx_render render = {fx_rom_data, 0x30000, memory};
    fx_box box;
    if (length > 256) return -1;
    memset(memory, 0, sizeof(memory));
    memory[0x80f9] = 0xc1;
    memory[0x80f5] = 0xf0;
    memory[0x8106] = 1;
    memory[0x8100] = 13;
    memory[0x8121] = 1;
    memory[0x812c] = 0; memory[0x812d] = 0x82;
    memcpy(memory+0x8200, input, length);
    memcpy(memory+0x8300, evaluated->value, sizeof(evaluated->value));
    if (fx_display_real_math_result(&render, 0x8300, &box) != 1) return -1;
    fx_flush_framebuffer(&render);
    FILE *output = fopen(path, "wb");
    if (!output) return -1;
    int failed = fprintf(output, "P4\n96 32\n") < 0;
    for (unsigned row = 0; row < 32 && !failed; ++row)
        failed = fwrite(memory+FX_LCD_FRAMEBUFFER+row*16, 1, 12, output) != 12;
    if (fclose(output)) failed = 1;
    return failed ? -1 : 0;
}

int main(int argc, char **argv)
{
    if ((argc == 3 || (argc == 5 && !strcmp(argv[3], "--pbm"))) && !strcmp(argv[1], "--eval")) {
        uint8_t input[1024], output[512];
        size_t length, n;
        fx_eval_result evaluated;
        fx_eval_status status;
        fx_format_status formatted = FX_FORMAT_UNIMPLEMENTED;
        fx_format_options options = fx_format_default_options();
        fx_format_result result = {0, 0, 0};
        int bitmap_status = 0;
        if (input_from_hex(input, sizeof(input), argv[2], &length)) { usage(); return 2; }
        status = fx_evaluate(input, length, NULL, &evaluated);
        if (status == FX_EVAL_OK)
            formatted = fx_format_number(&evaluated.value[0], &options, output, sizeof(output), &result);
        if (argc == 5 && status == FX_EVAL_OK)
            bitmap_status = write_result_bitmap(argv[4], input, length, &evaluated);
        printf("{\"eval_status\":%d,\"consumed\":%zu,\"unsupported_token\":%u,\"record\":\"",
               status, evaluated.consumed, evaluated.unsupported_token);
        for (n = 0; n < sizeof(evaluated.value); ++n)
            printf("%02x", ((const uint8_t *)evaluated.value)[n]);
        printf("\",\"format_status\":%d,\"bitmap_status\":%d,\"kind\":%u,\"tokens\":\"", formatted, bitmap_status, result.kind);
        if (formatted == FX_FORMAT_OK)
            for (n = 0; n < result.length; ++n) printf("%02x", output[n]);
        puts("\"}");
        return status == FX_EVAL_OK && formatted == FX_FORMAT_OK && !bitmap_status ? 0 : 1;
    }
    if (argc >= 3 && !strcmp(argv[1], "--token")) {
        unsigned token, context = 0xc1;
        fx_evaluator_token result;
        if (argc > 4 || byte_from_hex(&token, argv[2]) ||
            (argc == 4 && byte_from_hex(&context, argv[3]))) {
            usage(); return 2;
        }
        result = fx_decode_evaluator_token((uint8_t)token, (uint8_t)context);
        printf("{\"value\":%u,\"kind\":%u,\"display_kind\":%u,\"construct\":%u}\n",
               result.value, result.kind, fx_classify_display_token((uint8_t)token),
               fx_classify_construct_token((uint8_t)token));
        return 0;
    }
    if (argc >= 3 && !strcmp(argv[1], "--format")) {
        fx_number number;
        fx_format_options options = fx_format_default_options();
        fx_format_result result = {0, 0, 0};
        fx_format_status status;
        uint8_t output[512];
        int i;
        size_t n;
        if (record_from_hex(&number, argv[2])) { usage(); return 2; }
        for (i = 3; i < argc; ++i) {
            if (!strcmp(argv[i], "--linear")) options.math_output = 0;
            else if (!strcmp(argv[i], "--mixed")) options.mixed_fraction = 1;
            else if (!strcmp(argv[i], "--decimal")) options.selection = 10;
            else { usage(); return 2; }
        }
        status = fx_format_number(&number, &options, output, sizeof(output), &result);
        printf("{\"status\":%d,\"kind\":%u,\"length\":%zu,\"recognized\":%u,\"tokens\":\"",
               status, result.kind, result.length, result.recognized);
        if (status == FX_FORMAT_OK)
            for (n = 0; n < result.length; ++n) printf("%02x", output[n]);
        puts("\"}");
        return status == FX_FORMAT_OK ? 0 : 1;
    }
    usage();
    return 2;
}
