/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_tokens.h"
#include "../data/fx_rom_data.h"

fx_evaluator_token fx_decode_evaluator_token(uint8_t token, uint8_t calculation_context)
{
    fx_evaluator_token result;
    /* Each entry is twelve bits: an eight-bit value and four-bit category. */
    unsigned bit_offset = (unsigned)token * 12u;
    unsigned byte_offset = 0x245au + bit_offset / 8u;
    unsigned shift = bit_offset % 8u;
    unsigned packed = fx_rom_data[byte_offset] | (unsigned)fx_rom_data[byte_offset + 1u] << 8;
    packed >>= shift;
    result.value = (uint8_t)packed;
    result.kind = (uint8_t)((packed >> 8) & 15u);
    /* The evaluator overrides this token in the ordinary COMP context. */
    if (token == 0xc8u && calculation_context == 0xc1u) {
        result.value = 10;
        result.kind = 5;
    }
    return result;
}

uint8_t fx_classify_display_token(uint8_t token)
{
    uint8_t packed = fx_rom_data[0x31fau + token / 2u];
    return (uint8_t)((packed >> ((token & 1u) * 4u)) & 15u);
}

uint8_t fx_classify_construct_token(uint8_t token)
{
    switch (token) {
    case 0x5d: return 0;  /* product */
    case 0x5e: return 1;  /* power */
    case 0x63: return 2;  /* absolute value */
    case 0x68: return 3;  /* logarithm with base */
    case 0x69: return 4;  /* sum */
    case 0x6a: return 5;  /* integral */
    case 0x6b: return 6;  /* derivative */
    case 0x73: return 7;  /* exponential */
    case 0x7c: return 8;  /* mixed fraction */
    case 0x93: return 9;  /* power of ten */
    case 0x98: return 10; /* square root */
    case 0x9f: return 11; /* nth root */
    case 0xa4: return 12; /* repeating decimal */
    case 0xae: return 13; /* fraction */
    default: return 15;
    }
}
