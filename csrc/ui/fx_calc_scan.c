/* Readable CALC dependency discovery. SPDX-License-Identifier: GPL-3.0-only */
#include "fx_calc_scan.h"
#include "../parse/fx_tokens.h"

static uint8_t variable_bit(uint8_t id)
{
    unsigned shift=id ? (unsigned)id-1u : 0u;
    return (uint8_t)(1u << (shift&7u));
}

int fx_calc_scan_variables(fx_platform *p)
{
    uint16_t source=0x8398;
    unsigned reads=0, count=0;
    uint8_t assigned=0, pending_assignment=255;
    int statement_started=0;
    if (!p || !p->ram) return -1;
    if (fx_data_read(p,0,0x80fc)&64) return -2;
    for (unsigned i=0;i<10;++i) fx_data_write(p,0,(uint16_t)(0x83fe + i),255);
    while (reads++<65536) {
        fx_evaluator_token token=fx_decode_evaluator_token(
            fx_data_read(p,0,source++),fx_data_read(p,0,0x80f9));
        if (token.kind==10) {
            statement_started=0;
            if (token.value!=1) return 0;
            if (pending_assignment!=255) {
                assigned|=variable_bit(pending_assignment);
                pending_assignment=255;
            }
            continue;
        }
        if (token.kind!=5 || token.value==1 || token.value==10) {
            statement_started=1;
            continue;
        }
        if (!statement_started) {
            fx_evaluator_token following=fx_decode_evaluator_token(
                fx_data_read(p,0,source++),fx_data_read(p,0,0x80f9));
            ++reads;
            statement_started=1;
            if (following.kind==2 && following.value==42) {
                pending_assignment=token.value;
                continue;
            }
            --source;
        }
        if (!(assigned&variable_bit(token.value))) {
            unsigned i;
            for (i=0;i<count;++i)
                if (fx_data_read(p,0,(uint16_t)(0x83fe + i))==token.value) break;
            if (i==count) {
                if (count>=9) return -3;
                fx_data_write(p,0,(uint16_t)(0x83fe + count++),token.value);
            }
        }
    }
    return -3;
}
