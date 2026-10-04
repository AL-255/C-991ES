#include "fx_linalg_store.h"
#include <string.h>

void fx_linalg_bank_reset(fx_linalg_bank *bank)
{
    if (bank) memset(bank->slots,0,sizeof(bank->slots));
}
fx_numeric_status fx_linalg_bank_define(fx_linalg_bank *bank, unsigned identity,
    uint8_t rows, uint8_t columns)
{
    if (!bank || identity >= 9) return FX_NUMERIC_INVALID;
    bank->slots[identity].rows = rows;
    bank->slots[identity].columns = columns;
    memset(bank->slots[identity].cells,0,sizeof(bank->slots[identity].cells));
    return FX_NUMERIC_OK;
}
fx_numeric_status fx_linalg_bank_ensure_dimensions(fx_linalg_bank *bank,
    unsigned identity, uint8_t rows, uint8_t columns)
{
    if (!bank || identity >= 9) return FX_NUMERIC_INVALID;
    if (bank->slots[identity].rows == rows && bank->slots[identity].columns == columns)
        return FX_NUMERIC_OK;
    return fx_linalg_bank_define(bank,identity,rows,columns);
}
fx_numeric_status fx_linalg_bank_copy(fx_linalg_bank *bank,
    unsigned destination, unsigned source)
{
    if (!bank || destination >= 9 || source >= 9) return FX_NUMERIC_INVALID;
    bank->slots[destination] = bank->slots[source];
    return FX_NUMERIC_OK;
}
fx_numeric_status fx_linalg_bank_copy_answer(fx_linalg_bank *bank,
    const fx_number *reference)
{
    unsigned kind,identity;
    if (!bank || !reference) return FX_NUMERIC_INVALID;
    kind = reference->bytes[0] & 0xf0;
    identity = reference->bytes[0] & 15;
    if ((kind != 0x60 && kind != 0x90) || identity >= 9)
        return FX_NUMERIC_INVALID;
    return fx_linalg_bank_copy(bank,3,identity);
}
void fx_linalg_bank_begin_evaluation(fx_linalg_bank *bank, uint8_t context)
{
    if (bank) bank->temporary_mask = context == 6 ? 0x18 : 0;
}
unsigned fx_linalg_bank_first_free(uint8_t mask)
{
    unsigned identity;
    for (identity=4;identity<9;++identity)
        if (!(mask & (0x80 >> (identity-4)))) return identity;
    return 0;
}
fx_numeric_status fx_linalg_bank_mark(fx_linalg_bank *bank, unsigned identity)
{
    if (!bank || identity < 4 || identity > 8) return FX_NUMERIC_INVALID;
    bank->temporary_mask |= (uint8_t)(0x80 >> (identity-4));
    return FX_NUMERIC_OK;
}
fx_numeric_status fx_linalg_bank_release(fx_linalg_bank *bank, unsigned identity)
{
    if (!bank || identity < 4 || identity > 8) return FX_NUMERIC_INVALID;
    bank->temporary_mask &= (uint8_t)~(0x80 >> (identity-4));
    return FX_NUMERIC_OK;
}
fx_numeric_status fx_linalg_bank_reference(fx_number *out,
    const fx_linalg_bank *bank, uint8_t kind, unsigned identity,
    uint8_t *firmware_status)
{
    if (!out || !bank || !firmware_status || identity >= 9 ||
        (kind != 0x60 && kind != 0x90)) return FX_NUMERIC_INVALID;
    if (!bank->slots[identity].rows && !bank->slots[identity].columns) {
        *firmware_status = 9;
    } else {
        memset(out,0,sizeof(*out));
        out->bytes[0] = (uint8_t)(kind|identity); *firmware_status = 0;
    }
    return FX_NUMERIC_OK;
}
fx_numeric_status fx_linalg_bank_value(fx_linalg_value *out,
    const fx_linalg_bank *bank, const fx_number *reference)
{
    unsigned kind,identity;
    if (!out || !bank || !reference) return FX_NUMERIC_INVALID;
    kind = reference->bytes[0] & 0xf0; identity = reference->bytes[0] & 15;
    if ((kind != 0x60 && kind != 0x90) || identity >= 9)
        return FX_NUMERIC_INVALID;
    out->reference = *reference;
    out->rows = bank->slots[identity].rows;
    out->columns = bank->slots[identity].columns;
    memcpy(out->cells,bank->slots[identity].cells,sizeof(out->cells));
    return FX_NUMERIC_OK;
}
/* Native1D362/1D3C4 copies words at offsets8,6,4,2,0. Loading
 * each pair before storing preserves partial overlaps within the bank. */
static void copy_cell(fx_number *destination, const fx_number *source)
{
    uint8_t *output = (uint8_t *)destination;
    const uint8_t *input = (const uint8_t *)source;
    unsigned offset = 10;
    while (offset) {
        uint8_t low,high;
        offset -= 2;
        low = input[offset]; high = input[offset+1];
        output[offset] = low;
        output[offset+1] = high;
    }
}
static int cell_admitted(const fx_linalg_bank *bank, unsigned identity,
    unsigned row, unsigned column)
{
    return identity <= 5 && row >= 1 && row <= 3 && column >= 1 && column <= 3 &&
        row <= bank->slots[identity].rows && column <= bank->slots[identity].columns;
}
fx_numeric_status fx_linalg_bank_write_cell(fx_linalg_bank *bank,
    unsigned identity, unsigned row, unsigned column, const fx_number *value,
    uint8_t *firmware_status)
{
    if (!bank || !value || !firmware_status || identity >= 9)
        return FX_NUMERIC_INVALID;
    *firmware_status = cell_admitted(bank,identity,row,column) ? 0 : 2;
    if (!*firmware_status)
        copy_cell(&bank->slots[identity].cells[3*(row-1)+column-1],value);
    return FX_NUMERIC_OK;
}
fx_numeric_status fx_linalg_bank_read_cell(fx_number *out,
    const fx_linalg_bank *bank, unsigned identity, unsigned row,
    unsigned column, uint8_t *firmware_status)
{
    if (!out || !bank || !firmware_status || identity >= 9)
        return FX_NUMERIC_INVALID;
    *firmware_status = cell_admitted(bank,identity,row,column) ? 0 : 2;
    if (!*firmware_status)
        copy_cell(out,&bank->slots[identity].cells[3*(row-1)+column-1]);
    return FX_NUMERIC_OK;
}

fx_numeric_status fx_linalg_bank_temporary(fx_number *out,
    fx_linalg_bank *bank, const fx_number *reference, uint8_t *firmware_status)
{
    unsigned kind,source,destination;
    fx_numeric_status status;
    if (!out || !bank || !reference || !firmware_status) return FX_NUMERIC_INVALID;
    kind = reference->bytes[0] & 0xf0;
    source = reference->bytes[0] & 15;
    if ((kind != 0x60 && kind != 0x90) || source >= 9)
        return FX_NUMERIC_INVALID;
    *firmware_status = 0;
    if (source >= 4) { *out = *reference; return FX_NUMERIC_OK; }
    destination = fx_linalg_bank_first_free(bank->temporary_mask);
    if (!destination) { *firmware_status = 7; *out = *reference; return FX_NUMERIC_OK; }
    status = fx_linalg_bank_copy(bank,destination,source);
    if (status != FX_NUMERIC_OK) return status;
    (void)fx_linalg_bank_mark(bank,destination);
    *out = *reference;
    out->bytes[0] = (uint8_t)(kind|destination);
    return FX_NUMERIC_OK;
}
fx_numeric_status fx_linalg_bank_store_value(fx_linalg_bank *bank,
    unsigned identity, const fx_linalg_value *value)
{
    if (!bank || !value || identity >= 9) return FX_NUMERIC_INVALID;
    bank->slots[identity].rows = value->rows;
    bank->slots[identity].columns = value->columns;
    memcpy(bank->slots[identity].cells,value->cells,sizeof(value->cells));
    return FX_NUMERIC_OK;
}
