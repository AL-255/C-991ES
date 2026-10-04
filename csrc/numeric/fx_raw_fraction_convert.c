#include "fx_raw_fraction_convert.h"
#include "fx_raw_decimal_parts.h"
#include "fx_raw_decimal_divide.h"
#include "fx_raw_decimal_multiply_add.h"

fx_numeric_status fx_raw_fraction_convert(fx_number *out,
                                           const fx_number *input)
{
    fx_raw_fraction_parts parts;
    fx_numeric_status status = FX_NUMERIC_OK;
    unsigned kind;
    if (!out || !input) return FX_NUMERIC_INVALID;
    kind = input->bytes[0] & 0xb0;
    if (kind != 0x20) return FX_NUMERIC_INVALID;
    fx_raw_fraction_split(&parts,input);
    fx_raw_decimal_normalize(parts.whole);
    if (parts.has_middle) {
        /* Native mixed fractions preserve the middle component unnormalized
         * until after whole*denominator. Both decimal operations complete
         * before the division; their finite order affects guard digits. */
        status = fx_raw_decimal_multiply(parts.whole,parts.whole,parts.denominator);
        if (status == FX_NUMERIC_OK)
            status = fx_raw_decimal_add(parts.whole,parts.whole,parts.middle);
    }
    if (status == FX_NUMERIC_OK)
        status = fx_raw_decimal_divide(parts.whole,parts.whole,parts.denominator);
    if (status != FX_NUMERIC_OK) return status;
    fx_raw_decimal_cleanup(parts.whole);
    for (unsigned pair = 0; pair < 8; ++pair)
        out->bytes[pair] = parts.whole[9-pair];
    out->bytes[8] = parts.whole[0]; out->bytes[9] = parts.whole[1];
    return FX_NUMERIC_OK;
}
