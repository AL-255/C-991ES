/* SPDX-License-Identifier: GPL-3.0-only */
#include <stddef.h>
#include <string.h>
#include "parse/fx_eval_transport.h"

#define SAVED_POLL_CAPACITY 1024u
unsigned fx_saved_polls, fx_saved_poll_overflow;
uint8_t fx_saved_poll_data[SAVED_POLL_CAPACITY][100];

static int poll(void *userdata)
{
    const uint8_t *ram = userdata;
    if (fx_saved_polls < SAVED_POLL_CAPACITY)
        memcpy(fx_saved_poll_data[fx_saved_polls], ram + 0x8078, 100);
    else ++fx_saved_poll_overflow;
    ++fx_saved_polls;
    return 0;
}

int fx_saved_operand_probe(uint8_t *ram, const uint8_t *rom, size_t rom_size,
    uint16_t input, size_t length, uint16_t output,
    uint16_t *cursor, fx_eval_result *result)
{
    fx_eval_storage storage = {ram, 65536, rom, rom_size};
    fx_eval_source source = {input, output, NULL, NULL};
    fx_eval_effects effects;
    fx_calculus_control control = {poll, ram};
    fx_saved_polls = fx_saved_poll_overflow = 0;
    return fx_evaluate_prepared_source(length, NULL, NULL, NULL, &control,
        NULL, &storage, &source, cursor, &effects, result);
}

size_t fx_saved_operand_abi(unsigned item)
{
    switch (item) {
    case 0: return sizeof(fx_number);
    case 1: return sizeof(fx_eval_result);
    case 2: return offsetof(fx_eval_result, consumed);
    case 3: return offsetof(fx_eval_result, unsupported_token);
    case 4: return sizeof(fx_eval_storage);
    case 5: return offsetof(fx_eval_storage, ram);
    case 6: return offsetof(fx_eval_storage, ram_size);
    case 7: return offsetof(fx_eval_storage, rom);
    case 8: return offsetof(fx_eval_storage, rom_size);
    case 9: return sizeof(fx_eval_source);
    case 10: return offsetof(fx_eval_source, input_address);
    case 11: return offsetof(fx_eval_source, output_address);
    case 12: return offsetof(fx_eval_source, before_sample);
    case 13: return offsetof(fx_eval_source, userdata);
    case 14: return sizeof(fx_calculus_control);
    case 15: return offsetof(fx_calculus_control, cancelled);
    case 16: return offsetof(fx_calculus_control, userdata);
    case 17: return sizeof(fx_eval_status);
    default: return 0;
    }
}
