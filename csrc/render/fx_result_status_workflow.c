/* SPDX-License-Identifier: GPL-3.0-only */
/* B070 equation/paired-status workflow over prepared renderer state. */
#include "fx_result_status_workflow.h"
#include "fx_result_pair.h"
#include "fx_result_complex.h"
#include "fx_result_special.h"
#include "../format/fx_format_budget.h"
#include "../format/fx_format_base.h"
#include "../platform/fx_host_bridge.h"
#include "../platform/fx_persistent.h"
#include "../numeric/fx_surd_components.h"
#include "fx_render_context.h"
#include "fx_render_memory.h"
#include "fx_result_format_state.h"
#include "fx_result_inequality.h"
#include "fx_result_verify.h"
#include "../complex/fx_complex_angle.h"
#include "../format/fx_format.h"
#include "../trig/fx_math_context.h"
#include <string.h>

static uint16_t word_at(const fx_render *r, uint16_t address)
{
    return (uint16_t)(r->memory[address] | (uint16_t)r->memory[(uint16_t)(address+1)] << 8);
}
static void put_word(fx_render *r, uint16_t address, uint16_t value)
{
    r->memory[address]=(uint8_t)value;
    r->memory[(uint16_t)(address+1)]=(uint8_t)(value>>8);
}
static int append(uint8_t *text, size_t *length, size_t capacity,
                   const uint8_t *suffix, size_t added)
{
    if (*length>=capacity || added>=capacity-*length) return 0;
    if (added) memcpy(text+*length,suffix,added);
    *length+=added; text[*length]=0; return 1;
}
static void put_text(fx_render *r, uint16_t address, const uint8_t *text, size_t length)
{
    for (size_t n=0;n<=length;++n) r->memory[(uint16_t)(address+n)]=text[n];
}
static void raw_exponents(uint8_t *text, size_t length)
{
    for (size_t n=0;n+2<length;++n) {
        if (text[n]!=0x90 || (text[n+1]!=0x91 && text[n+1]!=0x92)) continue;
        text[n]+=80; text[++n]+=80;
        while (n+1<length && text[n+1]>=0xa0 && text[n+1]<=0xaf) text[++n]+=80;
    }
}
/*17576's caller-private decimal conversion retains its six pool records.
 *CCF6's opposite-sign arm additionally commits its decimal to slot0. */
static int dms_surd_workspace(fx_render *r, const fx_number *source)
{
    uint8_t classification;
    fx_number absolute=*source, decimal;
    if (fx_scalar_numeric_classify(&classification,source)!=FX_NUMERIC_OK) return 0;
    absolute.bytes[0]&=(uint8_t)~0x40;
    if (classification==2 && fx_number_negate(&absolute,&absolute)!=FX_NUMERIC_OK) return 0;
    if (fx_surd_components_convert_copy(r->memory,&decimal,&absolute)!=FX_NUMERIC_OK) return 0;
    /*BED6 classifies the original source after spelling the absolute value. */
    if ((uint8_t)(source->bytes[8]+source->bytes[9])==7) {
        if (fx_surd_components_convert_copy(r->memory,&decimal,source)!=FX_NUMERIC_OK) return 0;
        memcpy(r->memory+0x8640,decimal.bytes,10);
    }
    return 1;
}
static uint64_t component_integer(const fx_number *number)
{
    fx_decimal value;
    if (fx_decimal_decode(&value,number)!=FX_NUMERIC_OK || !value.mantissa) return 0;
    uint64_t divisor=1;
    for (int exponent=value.exponent;exponent<14;++exponent) divisor*=10;
    return value.mantissa/divisor;
}
static uint64_t common_factor(uint64_t a, uint64_t b)
{
    while (b) { uint64_t remainder=a%b; a=b; b=remainder; }
    return a;
}
static void commit_pool(fx_render *r, unsigned index, const fx_number *value)
{
    memcpy(r->memory+0x8640+10*index,value->bytes,10);
}
/*18176 decomposes exact SURD spelling into coefficient/radical/coefficient/
 *radical/common-denominator slots0..4. Its source six-tuple is at6..11;
 *slot5 survives the preceding decimal preparation. All arithmetic reuses
 *the exact existing decimal kernels; bounded compact coefficients/denoms
 *are integers<=99, so product magnitudes fit9801. */
static int exact_surd_workspace(fx_render *r, const fx_number *source)
{
    fx_number parts[6], product[3], tuple[5];
    if (fx_surd_components_unpack_copy(parts,source)!=FX_NUMERIC_OK) return 0;
    for (unsigned n=0;n<6;++n) commit_pool(r,6+n,&parts[n]);
    int rational_first=component_integer(&parts[1])==1;
    if (rational_first) {
        if (fx_decimal_binary(&product[0],&parts[0],&parts[5],FX_MULTIPLY)!=FX_NUMERIC_OK) return 0;
        commit_pool(r,0,&product[0]); tuple[0]=product[0];
        tuple[1]=parts[1];commit_pool(r,1,&tuple[1]);
        if (fx_decimal_binary(&product[1],&parts[2],&parts[3],FX_MULTIPLY)!=FX_NUMERIC_OK) return 0;
        commit_pool(r,2,&product[1]);tuple[2]=product[1];
        tuple[3]=parts[4];commit_pool(r,3,&tuple[3]);
    } else {
        if (fx_decimal_binary(&product[0],&parts[2],&parts[3],FX_MULTIPLY)!=FX_NUMERIC_OK) return 0;
        commit_pool(r,0,&product[0]);tuple[0]=product[0];
        tuple[1]=parts[4];commit_pool(r,1,&tuple[1]);
        if (fx_decimal_binary(&product[1],&parts[0],&parts[5],FX_MULTIPLY)!=FX_NUMERIC_OK) return 0;
        commit_pool(r,2,&product[1]);tuple[2]=product[1];
        tuple[3]=parts[1];commit_pool(r,3,&tuple[3]);
    }
    if (fx_decimal_binary(&product[2],&parts[2],&parts[5],FX_MULTIPLY)!=FX_NUMERIC_OK) return 0;
    tuple[4]=product[2];commit_pool(r,4,&tuple[4]);
    /*174A0 preserves the literal raw zero/unit gate, including negative1. */
    for (unsigned n=0;n<5;n+=2)
        if (!tuple[n].bytes[0] || (tuple[n].bytes[0]==1 && !tuple[n].bytes[8]))
            return 1;
    uint64_t factor=common_factor(component_integer(&tuple[0]),component_integer(&tuple[2]));
    factor=common_factor(component_integer(&tuple[4]),factor);
    if (factor>1) {
        fx_decimal decoded={1,0,0,0};
        uint64_t normalized=factor;
        while (normalized<UINT64_C(100000000000000)) { normalized*=10; --decoded.exponent; }
        decoded.exponent+=14;decoded.mantissa=normalized;
        fx_number divisor;
        if (fx_decimal_encode(&divisor,&decoded)!=FX_NUMERIC_OK) return 0;
        for (unsigned n=0;n<5;n+=2) {
            if (fx_decimal_binary(&tuple[n],&tuple[n],&divisor,FX_DIVIDE)!=FX_NUMERIC_OK) return 0;
            commit_pool(r,n,&tuple[n]);
        }
    }
    return 1;
}
/* C060's error and mode policies precede the status-bit4 budget gate. */
int fx_format_status_component(fx_render *r, const fx_number *number,
                              uint8_t context, uint8_t text[512],
                              fx_format_result *result)
{
    if (!r || !r->memory || !number || !text || !result
        || (!r->rom && r->rom_size)) return -1;
    fx_number saved=*number;
    number=&saved;
    if ((number->bytes[0]&0xf0)==0xf0) {
        result->kind=0; result->recognized=0;
        result->length=(number->bytes[0]&15)==13?0:5;
        if (result->length) memcpy(text,"ERROR",5);
        text[result->length]=0; return 1;
    }
    if (r->memory[0x80f9]==137)
        return fx_format_verify_result(r,number,text,512,result)==FX_FORMAT_OK;
    if (r->memory[0x80f9]==2)
        return fx_format_base(number,r->memory[0x80fa],text,512,result)==FX_FORMAT_OK;
    if (r->memory[0x80ff]&0x10) {
        uint8_t selection=r->memory[0x8100]&15, previous=r->memory[0x8100]>>4;
        fx_format_options options=fx_format_default_options();
        options.selection=1; options.math_output=(uint8_t)fx_display_has_natural_result(r);
        options.decimal_dot=r->memory[0x8104];
        int dms=selection==1 || ((number->bytes[0]&0xf0)==0x40
            && (selection==0 || (selection==13 && !previous)));
        if (dms || (selection>10 && previous==1)) {
            if (!(fx_number_kind(number)==FX_NUMBER_RATIONAL && number->bytes[0]>0x4f)) {
                if (fx_format_number(number,&options,text,512,result)!=FX_FORMAT_OK) return 0;
                if (result->kind==1) return 1;
            }
            r->memory[0x8100]=(uint8_t)((r->memory[0x8100]&0xf0)|10);
            r->memory[0x8130]=0;
        } else if (selection>10 && previous>1 && previous<10) {
            r->memory[0x8100]=(uint8_t)((r->memory[0x8100]&0xf0)|previous);
            r->memory[0x8130]=0;
        }
        /*CC90 rounds the prepared decimal before BDD0 clamps exponent-100.
         *That order can carry a top mantissa into the admissible exponent-99.
         *The public budget formatter assumes a canonical exponent; normalize
         *only this raw prepared boundary using the same ten-digit rounding. */
        fx_number finite=*number;
        fx_decimal decoded;
        if (fx_number_kind(number)==FX_NUMBER_DECIMAL
            && fx_decimal_decode(&decoded,number)==FX_NUMERIC_OK
            && decoded.exponent < -99) {
            const uint64_t unit=UINT64_C(100000);
            decoded.mantissa=((decoded.mantissa+unit/2)/unit)*unit;
            if (decoded.mantissa>=UINT64_C(1000000000000000)) {
                decoded.mantissa/=10; ++decoded.exponent;
            }
            if (decoded.mantissa<UINT64_C(100000000000000))
                fx_number_zero(&finite);
            else if (fx_decimal_encode(&finite,&decoded)!=FX_NUMERIC_OK) return 0;
        }
        return fx_format_budget(&finite,12,r->memory[0x8127],
            r->memory[0x80ff]==20,r->memory[0x8104],text,512,result)==FX_FORMAT_OK;
    }
    fx_format_options options=fx_format_default_options();
    options.selection=r->memory[0x8100];
    options.math_output=(uint8_t)fx_display_has_natural_result(r);
    options.mixed_fraction=r->memory[0x8107];
    options.display_mode=r->memory[0x8102]; options.digits=r->memory[0x8103];
    options.decimal_dot=r->memory[0x8104]; options.format_context=context;
    /*AB8E's1D030 decimal preparation consumes a caller-private compact
     *source and commits178BA's six ordered components even when the later
     *spelling remains exact. This is formatter preparation, after mode/error
     *admission; numeric classification alone does not perform this commit.
     *AB8E selection15 goes directly to7EE0, bypassing1D030. */
    if ((number->bytes[0]&0xf0)==0x80 && (options.selection&15)!=15) {
        fx_number decimal;
        if (fx_surd_components_convert_copy(r->memory,&decimal,number)!=FX_NUMERIC_OK)
            return 0;
    }
    if (fx_format_number(number,&options,text,512,result)!=FX_FORMAT_OK) return 0;
    if ((number->bytes[0]&0xf0)==0x80) {
        if (result->kind==1) {
            if (!dms_surd_workspace(r,number)) return 0;
        } else if (result->kind==13 && (options.selection&15)==13 && options.math_output) {
            if (!exact_surd_workspace(r,number)) return 0;
        }
    }
    if (r->memory[0x8127]) raw_exponents(text,result->length);
    fx_apply_result_format_state(r,number,options.selection,result->kind);
    r->memory[0x8100]=(uint8_t)((options.selection&0xf0)|(r->memory[0x8100]&15));
    return 1;
}
int fx_result_equation_is_vertex(const fx_render *r, uint8_t *answer)
{
    if (!r || !r->memory || !answer || (!r->rom && r->rom_size)) return -1;
    *answer=0;
    if (r->memory[0x80fa]!=3 || r->memory[0x80f9]!=69) return 0;
    uint8_t index=r->memory[0x8113], count;
    fx_platform platform={r->rom,r->rom_size,r->memory,0,FX_MEMORY_OK};
    if (fx_replay_count(&platform,&count)) return -1;
    *answer=(uint8_t)(index>(count==4?2:1));
    return 0;
}
/*382E returns the complete preference byte, unless forced by a branch. */
int fx_result_equation_rectangular(const fx_render *r, uint8_t *answer)
{
    if (!r || !r->memory || !answer || (!r->rom && r->rom_size)) return -1;
    *answer=1;
    int equation=r->memory[0x80f9]==69 && r->memory[0x80fc]==1;
    if (r->memory[0x80f9]!=196 && !equation) return 0;
    if (equation) {
        if (r->memory[0x80fa]<=2) return 0;
        uint8_t vertex;
        if (fx_result_equation_is_vertex(r,&vertex)) return -1;
        if (vertex) return 0;
    }
    *answer=r->memory[0x8108];
    if (r->memory[0x8101]==1) *answer=1;
    else if (r->memory[0x8101]==2) *answer=0;
    return 0;
}
static int dms_first(const fx_render *r, const fx_number *number)
{
    uint8_t selection=r->memory[0x8100]&15, previous=r->memory[0x8100]>>4;
    return selection==1 || ((number->bytes[0]&0xf0)==0x40
        && (selection==0 || (selection==13 && !previous)));
}
static void draw_row(fx_render *r, const uint8_t *text, size_t length, uint8_t row)
{
    uint8_t x=(uint8_t)(96-(uint8_t)(length*6));
    unsigned advance=r->memory[0x811f]==6?4:6, maximum=r->memory[0x811f]==6?24:16;
    for (unsigned n=0;n<length && text[n] && x<=96-advance && n<maximum;
         ++n,x=(uint8_t)(x+advance)) fx_draw_glyph(r,x,(int8_t)row,text[n]);
}

/* AFE2 history flattening uses native byte-count span/owner queries. */
static unsigned history_token_kind(const fx_render *r, uint16_t pointer)
{
    uint8_t token=r->memory[pointer]; unsigned kind=fx_construct_class(r,token);
    if (kind==1) {
        uint8_t next=r->memory[(uint16_t)(pointer+1)];
        if (next!=0xb8 && next!=0xbb && next!=0xbd) kind=token==0xae || token==0x7c?13:10;
    }
    if (kind==3 && r->memory[(uint16_t)(pointer+1)]==0xb8) kind=4;
    return kind;
}
static uint16_t history_owner(const fx_render *r, uint16_t pointer, uint16_t first)
{
    if (r->memory[pointer]==0xbc) --pointer;
    if (r->memory[pointer]!=0xb9) return 0;
    unsigned depth=1;
    while (pointer!=first) {
        uint8_t token=r->memory[--pointer];
        if (token==0xb9) ++depth;
        else if (token==0xb8 && !--depth) {
            if (pointer==first) return 0;
            --pointer;
            if (r->memory[pointer]==0xb9) { depth=1; continue; }
            if (r->memory[pointer]==0xbb) --pointer;
            if (r->memory[pointer]==0xbd) --pointer;
            return pointer;
        }
    }
    return 0;
}
static void flattened_history(fx_render *r, uint16_t first)
{
    uint16_t source=first,destination=0x9838;
    /* AFE2 is a do-while walk: an empty source still copies its first NUL
     * and writes a second terminator, including dormant history bytes. */
    for (unsigned n=0;n<65535;++n,++source) {
        unsigned kind=history_token_kind(r,source); uint8_t token=r->memory[source];
        if (kind==1 || kind==3) {
            r->memory[destination++]=127;
            uint16_t opening=kind==1?source:history_owner(r,source,first);
            uint8_t construct=opening?r->memory[opening]:0;
            if (construct==0x5e) r->memory[destination++]=kind==1?90:91;
            if (construct==0xa4) r->memory[destination++]=kind==1?115:116;
            if (kind==1) ++source;
        } else r->memory[destination++]=token>=224?(uint8_t)(token+176):token;
        if (!r->memory[(uint16_t)(source+1)]) break;
    }
    r->memory[destination]=0;
}
static void save_history(fx_render *r, const uint8_t *text, size_t length,
                          uint16_t expression, unsigned selection, int natural)
{
    if (natural) {
        r->memory[0x9838]=0;
        if (selection>13) flattened_history(r,expression);
    } else put_text(r,0x9838,text,length);
    fx_platform platform={r->rom,r->rom_size,r->memory,0,FX_MEMORY_OK};
    fx_host_descriptor descriptor;
    fx_host_descriptor_default(&descriptor);
    (void)fx_host_write_text_packet_fields(&platform,&descriptor);
}
/* B468..B48E replaces the natural history with raw result tokens in VERIFY.
 * Its emptiness query is byte-valued, while the subsequent copy is a full
 * terminated string. This second history publication follows the first. */
static void save_verify_history(fx_render *r, uint16_t expression,
                                unsigned selection)
{
    size_t length = 0;
    while (length < 65535 && r->memory[(uint16_t)(expression + length)]) ++length;
    if (!(uint8_t)length) {
        static const uint8_t empty[] = {0};
        save_history(r, empty, 0, 0, selection, 0);
    } else {
        /* Preserve the firmware's ascending terminated copy rather than
         * constructing a host pointer spanning a wrapped RAM address. */
        for (size_t n = 0; n < 65536; ++n) {
            uint8_t byte = r->memory[(uint16_t)(expression + n)];
            r->memory[(uint16_t)(0x9838 + n)] = byte;
            if (!byte) break;
        }
        /* A zero-length same-address copy retains the already-written
         * first byte; save_history derives its length from that live RAM. */
        save_history(r, r->memory + 0x9838, 0, 0, selection, 0);
    }
}
static uint8_t data_byte(const fx_render *r, uint16_t address)
{
    return address>=0x8000?r->memory[address]:
        (address<r->rom_size?r->rom[address]:0);
}
static int copied_text(const fx_render *r, uint16_t address,
                       uint8_t *text, size_t capacity, size_t *length)
{
    if (!address) { text[0]=0; *length=0; return 1; }
    for (size_t n=0;n<capacity;++n) {
        text[n]=data_byte(r,(uint16_t)(address+n));
        if (!text[n]) { *length=n; return 1; }
    }
    return 0;
}
static void prepare_number(const fx_render *r, uint16_t source, fx_number *out)
{
    out->bytes[0]=data_byte(r,source);
    out->bytes[1]=data_byte(r,(uint16_t)(source+1));
    uint16_t tail=(uint16_t)((source+2)&0xfffeu);
    for (unsigned n=2;n<10;++n) out->bytes[n]=data_byte(r,(uint16_t)(tail+n-2));
}
static size_t pair_label(const fx_render *r, unsigned component, uint8_t text[1024])
{
    uint8_t status=r->memory[0x80ff], token=0;
    size_t length=0;
    if (status==17) token=(uint8_t)(component?'Y':'X');
    else if (status==18) token=component?0xc4:(r->memory[0x8127]?0x9d:'r');
    else if (status==19) {
        if (component) { memcpy(text,"L-R",3); length=3; }
        else token=data_byte(r,(uint16_t)(0x1056+r->memory[0x83fc]));
    } else if (status==20) { if (component) token='R'; }
    else if (!component) token='F';
    if (token) text[length++]=token;
    if (length) text[length++]='=';
    text[length]=0; return length;
}
static int paired_row(fx_render *r, unsigned component, const uint8_t *number,
                      size_t added, uint8_t row[1024], size_t *length, size_t *written)
{
    *length=pair_label(r,component,row); *written=*length+1;
    if (!r->memory[0x8127]) {
        size_t old=*length;
        if (added>16 || !append(row,length,1024,r->rom+0x11a1,16)) return 0;
        *written=old+17;
        *length=16-added; row[*length]=0;
    }
    if (!append(row,length,1024,number,added)) return 0;
    if (*written<*length+1) *written=*length+1;
    return 1;
}
/*B09C's caption branch precedes numeric source reads, bit4, natural output
 * and font admission. B4B0 owns a private36-byte caption, not synthetic RAM. */
static int equation_caption_history(fx_render *r, fx_box *box)
{
    fx_clear_framebuffer(r); r->memory[0x811f]=10;
    uint8_t selector=r->memory[0x8135], caption[36], text[53];
    uint16_t table=(uint16_t)(0x8dfa+2*(uint8_t)(selector-1));
    uint16_t pointer=(uint16_t)(data_byte(r,table)|(uint16_t)data_byte(r,(uint16_t)(table+1))<<8);
    size_t length;
    if (!copied_text(r,pointer,caption,sizeof caption,&length)) return -1;
    /*The native36-byte local/cutoff ABI is only represented for <=16-byte
     * captions. Wider text can alias the original CPU local fields. */
    if (length>16) return -1;
    memset(text,' ',16); text[16-length]=0;
    size_t padded=16-length;
    if (length) memcpy(text+padded,caption,length);
    text[16]=0;
    for (unsigned n=0;n<16;++n) fx_draw_glyph(r,(uint8_t)(6*n),22,text[n]);
    r->memory[0x8100]=(uint8_t)((r->memory[0x8100]&15)|0xd0);
    r->memory[0x9838]=0;
    put_text(r,0x9838,text,16);
    fx_platform platform={r->rom,r->rom_size,r->memory,0,FX_MEMORY_OK};
    fx_host_descriptor descriptor; fx_host_descriptor_default(&descriptor);
    if (fx_host_write_text_packet_fields(&platform,&descriptor)) return -1;
    if (box) { box->width=96; box->height=10; box->depth=5; }
    return 1;
}
/*37BC's first copy is private; paired C060 still ignores imaginary input. */
static int special_status_result(fx_render *r, uint16_t source, fx_box *box)
{
    uint8_t mode=r->memory[0x80f9], font=r->memory[0x811f];
    if (mode==2 || mode==137 || !(r->memory[0x80ff]&0x10))
        return fx_display_special_real_result(r,source,box);
    if (font!=6 && font!=7 && font!=10) return -1;
    uint8_t text[512]={0}; size_t length=0;
    if (source) {
        fx_number value; fx_format_result result;
        prepare_number(r,source,&value);
        int status=fx_format_status_component(r,&value,0,text,&result);
        if (status!=1) return status;
        length=result.length;
        if (length>=26) return -1;
        r->memory[0x8100]=(uint8_t)((r->memory[0x8100]&15)|(result.kind<<4));
    } else r->memory[0x8100]&=15;
    uint8_t y=font==10?22:25;
    fx_clear_from_row(r,y); draw_row(r,text,length,y);
    if (box) { box->width=(uint16_t)(length*6); box->height=fx_font_height(r); box->depth=fx_font_depth(r); }
    return 1;
}
int fx_display_status_workflow(fx_render *r, uint16_t address, fx_box *box)
{
    if (!r || !r->memory || (!r->rom && r->rom_size)) return -1;
    uint8_t mode=r->memory[0x80f9], font=r->memory[0x811f];
    if ((r->memory[0x80fc]&0x10) &&
        (r->memory[0x80fe]==0 || r->memory[0x80fe]==3 || r->memory[0x80fe]==5))
        return special_status_result(r,address,box);
    if (mode==69 && r->memory[0x80fc]==1 && r->memory[0x80fd]==3)
        return equation_caption_history(r,box);
    if (mode==75 && r->memory[0x80fc]==1) return fx_display_inequality_result(r,box);
    int paired=(r->memory[0x80ff]&0x10)!=0;
    if (mode!=69 && !(paired && (mode==137 || mode==6 || mode==7 || mode==2))) {
        if (paired) return fx_display_pair_result(r,address,box);
        return fx_display_complex_result(r,address,box);
    }
    if ((font!=6 && font!=7 && font!=10) || r->memory[0x8127]
        || !fx_display_has_formula_view(r) || r->rom_size<=0x1add) return -1;
    uint8_t rectangular;
    if (fx_result_equation_rectangular(r,&rectangular)) return -1;
    int permitted=fx_display_has_natural_input(r)||fx_display_has_natural_result(r);
    if (paired && (r->memory[0x80ff]==19 || !permitted)) {
        r->memory[0x8100]=10; r->memory[0x8130]=0;
    }
    uint8_t selection=r->memory[0x8100]&15;
    int natural=permitted && selection!=10;
    /* A natural result in a mode without persistent scratch uses the native
     * CPU stack as its token buffer. That storage ABI is not represented. */
    if (permitted && !(mode&0xc0)) return -1;
    uint16_t persistent=mode==136 || !(mode&0x80)?0x8546:0x8398;
    if (natural) r->memory[0x8127]=1;
    if (permitted && r->memory[0x8130]) {
        save_history(r,NULL,0,persistent,selection,1);
        if (!fx_display_has_natural_input(r)) fx_clear_from_row(r,22);
        r->memory[0x8126]=1;
        uint16_t previous=word_at(r,0x812c); put_word(r,0x812c,persistent);
        if (mode == 137) save_verify_history(r, persistent, selection);
        int result=fx_render_viewport(r,box);
        put_word(r,0x812c,previous); r->memory[0x8127]=0; return result;
    }
    if (address<0x8000 || address>0xffec) { r->memory[0x8127]=0; return -1; }
    if (permitted) r->memory[persistent]=0;
    r->memory[0x8114]=0;
    fx_complex value;
    prepare_number(r,(uint16_t)(address+10),&value.imaginary);
    prepare_number(r,address,&value.real);
    uint8_t real_class,imaginary_class;
    if (fx_scalar_numeric_classify(&real_class,&value.real)!=FX_NUMERIC_OK
        || fx_scalar_numeric_classify(&imaginary_class,&value.imaginary)!=FX_NUMERIC_OK) {
        r->memory[0x8127]=0; return -1;
    }
    int rect=rectangular!=0; uint8_t real_context=0;
    if (!rect) {
        rect=1;
        if (!(real_class==1 && imaginary_class==1)
            && !(dms_first(r,&value.real) && imaginary_class==1 && real_class==4)) {
            uint8_t unit=r->memory[0x8105];
            if (unit<4 || unit>6 || fx_complex_to_polar(&value,&value,
                (fx_angle_unit)(unit-4),fx_exact_output_allowed(r->memory))!=FX_NUMERIC_OK
                || fx_scalar_numeric_classify(&real_class,&value.real)!=FX_NUMERIC_OK
                || fx_scalar_numeric_classify(&imaginary_class,&value.imaginary)!=FX_NUMERIC_OK) {
                r->memory[0x8127]=0; return -1;
            }
            if (imaginary_class!=1) { rect=0; real_context=6; }
        }
    }
    if (!permitted) fx_clear_from_row(r,12);
    uint8_t first[1024]={0},second[1024]={0},formatted[512],history[2048]={0};
    size_t first_length=0,second_length=0,first_written=0,second_written=0; uint8_t real_kind=0xf0;
    int real_included=paired || real_class!=1 || imaginary_class==1;
    fx_format_result result;
    if (real_included) {
        if (!fx_format_status_component(r,&value.real,real_context,formatted,&result)) goto formatting_failure;
        if (paired) {
            if (!r->memory[0x8127] && result.length>16) { r->memory[0x8127]=0; return -1; }
            if (!paired_row(r,0,formatted,result.length,first,&first_length,&first_written)) goto formatting_failure;
        } else if (!append(first,&first_length,sizeof first,formatted,result.length)) goto formatting_failure;
        /* Native C060 writes its first component directly into ER4. A
         * selection10 single-real result later clears only its first byte,
         * retaining the label tail in the persistent result buffer. */
        if (permitted && paired) memcpy(r->memory+persistent,first,first_written);
        else if (permitted) put_text(r,persistent,first,first_length);
        real_kind=result.kind;
    }
    if (imaginary_class==1 && !paired) {
        r->memory[0x8100]=(uint8_t)((r->memory[0x8100]&15)|(real_kind<<4));
        if (!natural) {
            memcpy(second,first,first_length+1); second_length=first_length;
            first[0]=0; first_length=0;
        }
    } else {
        uint8_t context=real_included?(rect?1:(imaginary_class==2?2:5)):(imaginary_class==2?3:4);
        if (!fx_format_status_component(r,&value.imaginary,context,formatted,&result)) goto formatting_failure;
        size_t length=result.length;
        if (paired) {
            if (!r->memory[0x8127] && length>16) { r->memory[0x8127]=0; return -1; }
            if (!paired_row(r,1,formatted,length,second,&second_length,&second_written)) goto formatting_failure;
        } else if (rect) {
            if (length==1 && formatted[0]=='1') { formatted[0]=0x80; }
            else if (length==2 && formatted[0]==0x60 && formatted[1]=='1') formatted[1]=0x80;
            else {
                if (length+1>=sizeof formatted) goto formatting_failure;
                formatted[length++]=0x80; formatted[length]=0;
            }
            if (real_included) {
                if (formatted[0]==0x60) formatted[0]='-';
                else { uint8_t plus='+'; if (!append(second,&second_length,sizeof second,&plus,1)) goto formatting_failure; }
            }
        } else {
            uint8_t separator=r->memory[0x8127]?0xaf:0x88;
            if (!append(second,&second_length,sizeof second,&separator,1)) goto formatting_failure;
        }
        if (!paired && !append(second,&second_length,sizeof second,formatted,length)) goto formatting_failure;
        if (selection) {
            uint8_t kind=fx_combine_result_kinds(real_kind,result.kind);
            r->memory[0x8100]=(uint8_t)((r->memory[0x8100]&15)|(kind<<4));
        }
    }
    if (natural) {
        if (paired) {
            uint16_t delimiter=r->memory[0x8104]?0x1ada:0x1adc;
            uint8_t spelling[16]; size_t added;
            if (!copied_text(r,delimiter,spelling,sizeof spelling,&added)
                || !append(first,&first_length,sizeof first,spelling,added)) goto formatting_failure;
        }
        if (!append(first,&first_length,sizeof first,second,second_length)) goto formatting_failure;
        put_text(r,persistent,first,first_length);
        /* History eligibility uses the initial selection, not a DMS/ENG
         * fallback selection produced by one of the component calls. */
        save_history(r,NULL,0,persistent,selection,1);
        if (!fx_display_has_natural_input(r)) fx_clear_from_row(r,22);
        r->memory[0x8126]=1; uint16_t previous=word_at(r,0x812c); put_word(r,0x812c,persistent);
        if (mode == 137) save_verify_history(r, persistent, selection);
        int success=fx_render_viewport(r,box);
        put_word(r,0x812c,previous); r->memory[0x8127]=0; return success;
    }
    if (permitted) {
        put_text(r,persistent,first,first_length);
        size_t maximum=first_length>second_length?first_length:second_length;
        if ((uint8_t)(r->memory[0x8115]+(uint8_t)(maximum*6))>90)
        {
            uint8_t requested=first_length?20:10;
            uint8_t previous=r->memory[0x8128]?r->memory[0x8128]:10;
            if ((uint8_t)(requested+previous)>62) { r->memory[0x8127]=0; return -1; }
            fx_make_result_space(r,requested);
        }
    }
    draw_row(r,first,first_length,12); draw_row(r,second,second_length,22);
    size_t history_length=0;
    if (first_length) {
        uint8_t newline=13;
        if (!append(history,&history_length,sizeof history,first,first_length)
            || !append(history,&history_length,sizeof history,&newline,1)) goto formatting_failure;
    }
    if (!append(history,&history_length,sizeof history,second,second_length)) goto formatting_failure;
    save_history(r,history,history_length,0,selection,0);
    if (box) {
        box->width=(uint16_t)((first_length>second_length?first_length:second_length)*6);
        box->height=(uint8_t)(first_length?20:10); box->depth=fx_font_depth(r);
    }
    r->memory[0x8127]=0; return 1;
formatting_failure:
    r->memory[0x8127]=0; return 0;
}
