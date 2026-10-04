/* SPDX-License-Identifier: GPL-3.0-only
 * Subsystem inspection CLI. Calculator key UI remains pending. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "parse/fx_tokens.h"
#include "parse/fx_eval.h"
#include "numeric/fx_numeric.h"
#include "format/fx_format.h"
#include "format/fx_format_base.h"
#include "render/fx_render.h"
#include "render/fx_result_complex.h"
#include "render/fx_result_special.h"
#include "data/fx_rom_data.h"
#include "ui/fx_input_codec.h"

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

static uint8_t base_from_name(const char *name)
{
    if (!strcmp(name, "bin")) return FX_BASE_BIN;
    if (!strcmp(name, "oct")) return FX_BASE_OCT;
    if (!strcmp(name, "dec")) return FX_BASE_DEC;
    if (!strcmp(name, "hex")) return FX_BASE_HEX;
    return 0;
}

static void usage(void)
{
    fputs("Subsystem probe for the high-level C firmware port (incomplete).\n"
          "  fx991c --token HEX_BYTE [HEX_CONTEXT]\n"
          "  fx991c --format HEX_10_BYTE_RECORD [--linear] [--mixed] [--decimal]\n"
          "  fx991c --eval HEX_INPUT_TOKENS [--complex | --base bin|oct|dec|hex] [--pbm OUTPUT_FILE]\n"
          "  fx991c --display HEX_DISPLAY_TOKENS [--complex] [--pbm OUTPUT_FILE]\n"
          "Display input uses the natural editor's99-byte expression limit.\n"
          "Supported COMP arithmetic and functions are listed in csrc/parse/manifest.json.\n", stderr);
}

static int render_result(const char *path, const uint8_t *input, size_t length,
                         const fx_eval_result *evaluated, int complex_mode, uint8_t base_radix,
                         uint8_t *tokens, size_t capacity, fx_format_result *result)
{
    static uint8_t memory[FX_RENDER_MEMORY_BYTES];
    fx_render render = {fx_rom_data, 0x30000, memory};
    fx_box box;
    if (length > 256) return -1;
    memset(memory, 0, sizeof(memory));
    memory[0x80f9] = base_radix ? 2 : complex_mode ? 0xc4 : 0xc1;
    memory[0x80f5] = 0xf0;
    memory[0x8106] = 1;
    if (complex_mode) {
        memory[0x80fc] = 1;
        memory[0x8104] = 1;
        memory[0x8105] = 4;
        memory[0x8108] = 1;
        memory[0x811f] = 10;
    }
    if (base_radix) {
        memory[0x80fa] = base_radix;
        memory[0x811f] = 10;
    }
    memory[0x8100] = 13;
    memory[0x8121] = 1;
    memory[0x812c] = 0; memory[0x812d] = 0x82;
    memcpy(memory+0x8200, input, length);
    memcpy(memory+0x8300, evaluated->value, sizeof(evaluated->value));
    int displayed = base_radix ? fx_display_special_real_result(&render, 0x8300, &box) :
                    complex_mode ? fx_display_complex_result(&render, 0x8300, &box) :
                                   fx_display_real_math_result(&render, 0x8300, &box);
    if (displayed != 1) return -1;
    if (complex_mode) {
        size_t count = 0;
        while (count < capacity && memory[0x8398+count]) ++count;
        if (count >= capacity) return -1;
        memcpy(tokens, memory+0x8398, count+1);
        result->length = count;
        result->kind = memory[0x8100] >> 4;
        result->recognized = 0;
    }
    if (!path) return 0;
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
    if (argc >= 3 &&
        (!strcmp(argv[1], "--eval") || !strcmp(argv[1], "--display"))) {
        uint8_t input[1024], output[512];
        static uint8_t editor_memory[65536];
        fx_platform editor = {fx_rom_data, 0x30000, editor_memory, 0, FX_MEMORY_OK};
        int display_input = !strcmp(argv[1], "--display");
        int complex_mode = 0;
        uint8_t base_radix = 0;
        const char *bitmap_path = NULL;
        for (int argument = 3; argument < argc; ++argument) {
            if (!strcmp(argv[argument], "--complex") && !complex_mode && !base_radix) complex_mode = 1;
            else if (!strcmp(argv[argument], "--base") && !complex_mode && !base_radix &&
                     !display_input && argument+1 < argc) {
                base_radix = base_from_name(argv[++argument]);
                if (!base_radix) { usage(); return 2; }
            }
            else if (!strcmp(argv[argument], "--pbm") && !bitmap_path && argument+1 < argc)
                bitmap_path = argv[++argument];
            else { usage(); return 2; }
        }
        size_t length, n;
        fx_eval_result evaluated;
        fx_eval_status status;
        fx_eval_options eval_options = fx_eval_default_options();
        if (complex_mode) eval_options.calculation_context = 0xc4;
        fx_format_status formatted = FX_FORMAT_UNIMPLEMENTED;
        fx_format_options options = fx_format_default_options();
        fx_format_result result = {0, 0, 0};
        int bitmap_status = 0;
        if (input_from_hex(input, sizeof(input), argv[2], &length)) { usage(); return 2; }
        if (display_input) {
            if (length > 100) { usage(); return 2; }
            memset(editor_memory, 0, sizeof(editor_memory));
            editor_memory[0x80f9] = eval_options.calculation_context;
            editor_memory[0x80fc] = 1; editor_memory[0x8106] = 1;
            editor_memory[0x812c] = 0x54; editor_memory[0x812d] = 0x81;
            memcpy(editor_memory+0x8154, input, length);
            int allowed = fx_editor_input_boundaries(&editor, 0x8154);
            if (allowed != 1 || fx_editor_export_input(&editor, 0x8154, 0x8200, 0, 1)) {
                printf("{\"conversion_status\":%d,\"display_cursor\":%u}\n",
                       allowed == 0 ? FX_EVAL_SYNTAX : FX_EVAL_RESOURCE_LIMIT, editor_memory[0x8114]);
                return 1;
            }
            for (length = 0; length + 1 < sizeof(input); ++length) {
                input[length] = editor_memory[0x8200+length];
                if (!input[length]) break;
            }
            ++length;
        }
        status = base_radix ? fx_evaluate_base_n(input, length, base_radix, &eval_options, NULL, NULL, &evaluated) :
                              fx_evaluate(input, length, &eval_options, &evaluated);
        if (display_input && (status == FX_EVAL_SYNTAX || status == FX_EVAL_MATH))
            (void)fx_editor_export_input(&editor, 0x8154, 0x8400, (uint8_t)evaluated.consumed, 0);
        if (status == FX_EVAL_OK && base_radix)
            formatted = fx_format_base(&evaluated.value[0], base_radix, output, sizeof(output), &result);
        else if (status == FX_EVAL_OK && !complex_mode)
            formatted = fx_format_number(&evaluated.value[0], &options, output, sizeof(output), &result);
        if (status == FX_EVAL_OK && (complex_mode || bitmap_path)) {
            bitmap_status = render_result(bitmap_path, input, length, &evaluated, complex_mode, base_radix,
                                          output, sizeof(output), &result);
            if (complex_mode && !bitmap_status) formatted = FX_FORMAT_OK;
        }
        putchar('{');
        if (display_input) {
            printf("\"conversion_status\":0,\"display_cursor\":%u,\"input_tokens\":\"", editor_memory[0x8114]);
            for (n = 0; n + 1 < length; ++n) printf("%02x", input[n]);
            fputs("\",", stdout);
        }
        printf("\"eval_status\":%d,\"consumed\":%zu,\"unsupported_token\":%u,\"record\":\"",
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
