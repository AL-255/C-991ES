/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_equation_result.h"
#include "../platform/fx_persistent.h"
#include "../trig/fx_math_context.h"
#include <string.h>
static uint8_t byte_at(fx_platform *p,uint16_t a) { return fx_data_read(p,0,a); }
static void put(fx_platform *p,uint16_t a,uint8_t v) { fx_data_write(p,0,a,v); }
static void copy(fx_platform *p,uint16_t to,uint16_t from,unsigned count)
{ for(unsigned n=0;n<count;++n) put(p,(uint16_t)(to+n),byte_at(p,(uint16_t)(from+n))); }
static void store(fx_platform *p,uint16_t to,const fx_number *v)
{ for(unsigned n=0;n<10;++n)put(p,(uint16_t)(to+n),v->bytes[n]); }
int fx_equation_solve_linear(fx_platform *p,uint8_t *action,fx_solver_result *numerical)
{
    if(!p || !p->ram || !action || !numerical)return -2;
    uint8_t selector=byte_at(p,0x80fa),key=byte_at(p,0x80f5);
    if(byte_at(p,0x80f9)!=0x45 || selector<1 || selector>2 ||
       byte_at(p,0x80fc)!=21 || byte_at(p,0x80fd) ||
       (key!=0xed && key!=0xf0) || !byte_at(p,0x80f7))return -1;
    fx_number coefficients[12];memset(coefficients,0,sizeof coefficients);
    unsigned count=selector==1?6:12;
    for(unsigned i=0;i<count;++i)
        for(unsigned n=0;n<10;++n)coefficients[i].bytes[n]=byte_at(p,(uint16_t)(0x829e + 10*i+n));
    fx_solver_context context={(uint8_t)fx_exact_output_allowed(p->ram),0,0};
    fx_solver_result solved,cleaned;
    if(fx_solver_solve(&solved,coefficients,(fx_solver_kind)selector,&context)!=FX_NUMERIC_OK ||
       solved.firmware_status || solved.count!=selector+1 ||
       fx_solver_cleanup(&cleaned,&solved)!=FX_NUMERIC_OK || cleaned.firmware_status)return -1;
    uint8_t imaginary_class[3];
    for(unsigned root=0;root<cleaned.count;++root)
        if(fx_scalar_numeric_classify(&imaginary_class[root],&cleaned.roots[root].imaginary)!=FX_NUMERIC_OK)return -1;
    /* E86A, then 14F16's forced 54E6 entry. Physical polling is the caller's
     * passive no-abort device; every successful solver check restarts it. */
    put(p,0x8129,0);put(p,0xf031,6);fx_display_port_sleep(p);
    for(unsigned check=0;check<solved.cancellation_checks;++check) {
        put(p,0x8e00,2);fx_timer_start(p,0x129a);put(p,0x8e00,0);
    }
    for(unsigned n=0;n<180;++n)put(p,(uint16_t)(0x8406+n),0);
    put(p,0x80e8,solved.coefficient_rows);put(p,0x80e9,solved.coefficient_columns);
    put(p,0x80ea,solved.root_rows);put(p,0x80eb,solved.root_columns);
    for(unsigned i=0;i<9;++i){store(p,(uint16_t)(0x8406+10*i),&solved.coefficient_work[i]);store(p,(uint16_t)(0x8460+10*i),&solved.root_work[i]);}
    /* 15658: result flags, initial C046 format, empty replay expression. */
    fx_result_clear_flags(p);
    fx_result_set_format(p,byte_at(p,0x8106) && !byte_at(p,0x810c)?13:0);
    put(p,0x8154,0);put(p,0x812c,0x54);put(p,0x812d,0x81);put(p,0x8113,0);
    copy(p,0x80e6,0x80e8,2);copy(p,0x83ac,0x8406,90);
    for(unsigned n=0;n<270;++n)put(p,(uint16_t)(0x8406+n),0);
    for(unsigned root=0;root<solved.count;++root) {
        uint16_t source=(uint16_t)(0x83ac+30*root);
        /* D12C copies the imaginary ten-byte component first. */
        copy(p,0x814a,(uint16_t)(source+10),10);copy(p,0x8140,source,10);
        store(p,0x814a,&cleaned.roots[root].imaginary);store(p,0x8140,&cleaned.roots[root].real);
        if(fx_replay_append_prepared(p,imaginary_class[root]))return -1;
    }
    /* E8E6: the retained decoded EXE drives the following replay cycle. */
    put(p,0x80fc,1);put(p,0x80fd,2);*action=0;*numerical=cleaned;return 0;
}
