/* Readable B070 paired-result display, without firmware execution.
 * GPL-3.0-or-later. */
#include "fx_result_pair.h"
#include "fx_render_context.h"
#include "fx_render_memory.h"
#include "../format/fx_format_budget.h"
#include "fx_result_inequality.h"
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
/* C060's paired branch: DMS is tried before the fixed decimal budget.
 * Component calls do not commit3634 or enter ordinary recognition/MMIO. */
static int format_component(fx_render *r, const fx_number *number,
                             uint8_t text[512], fx_format_result *result)
{
    uint8_t selection=r->memory[0x8100]&15, previous=r->memory[0x8100]>>4;
    fx_format_options options=fx_format_default_options();
    options.selection=1; options.math_output=(uint8_t)fx_display_has_natural_result(r);
    options.decimal_dot=r->memory[0x8104];
    /* BD78 ignores Fix/Sci settings. Its unsuccessful generic spelling is
     * discarded before3500, so keep the reused DMS API's settings bounded
     * rather than letting arbitrary RAM precision select discarded text. */
    if ((number->bytes[0]&0xf0)==0xf0) {
        result->kind=0; result->recognized=0;
        result->length=(number->bytes[0]&15)==13?0:5;
        if (result->length) memcpy(text,"ERROR",5);
        text[result->length]=0; return 1;
    }
    int dms=selection==1 || ((number->bytes[0]&0xf0)==0x40
        && (selection==0 || (selection==13 && !previous)));
    if (dms || (selection>10 && previous==1)) {
        /* BD78 uses15C82's raw-header guard. A marked rational6x is
         * rejected there, although the general value API can convert it. */
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
    return fx_format_budget(number,12,r->memory[0x8127],
        r->memory[0x80ff]==20,r->memory[0x8104],text,512,result)==FX_FORMAT_OK;
}
/* 382E for the admitted ordinary modes. Equation-specific C2AA policy is
 * outside this entry's mode set. Any nonzero8108 means rectangular. */
static int rectangular(const fx_render *r)
{
    if (r->memory[0x80f9]!=196) return 1;
    if (r->memory[0x8101]==1) return 1;
    if (r->memory[0x8101]==2) return 0;
    return r->memory[0x8108]!=0;
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
    memset(r->memory+0x9804,0,48);
    r->memory[0x9804]=17; r->memory[0x9805]=255; r->memory[0x9807]=48;
    memset(r->memory+0x9808,255,4);
    uint8_t angle=r->memory[0x8105];
    r->memory[0x980d]=angle>=4 && angle<=6?(uint8_t)(angle-3):0;
    static const unsigned bits[5]={7,3,2,1,0}, offsets[5]={10,11,12,14,15};
    for (unsigned n=0;n<5;++n) r->memory[0x9804+offsets[n]]=(r->memory[0x80f8]>>bits[n])&1;
    if (!r->memory[0x80dd] && !r->memory[0x80fb] && r->memory[0x80fe]==1) {
        r->memory[0x9808]=0; r->memory[0x9809]=r->memory[0x8118];
        r->memory[0x980a]=0; r->memory[0x980b]=r->memory[0x8119];
        r->memory[0x980c]=(uint8_t)(r->memory[0x811b]|(r->memory[0x811a]==204?128:0));
    }
    size_t saved=0; while (saved<65535 && r->memory[(uint16_t)(0x9838+saved)]) ++saved;
    unsigned record_length=(unsigned)saved+1;
    if (saved) {
        record_length+=4; r->memory[0x9834]=34; r->memory[0x9835]=255;
        r->memory[0x9836]=(uint8_t)(record_length>>8); r->memory[0x9837]=(uint8_t)record_length;
    } else r->memory[0x9834]=0;
    unsigned full=record_length+48; static const uint8_t hex[]="0123456789ABCDEF";
    for (unsigned n=0;n<4;++n) r->memory[0x9800+n]=hex[(full>>(12-4*n))&15];
}

/* 10E7A compares the complete status byte, after admitting bit4. */
static size_t label(const fx_render *r, unsigned component, uint8_t text[1024])
{
    uint8_t status=r->memory[0x80ff], token=0;
    size_t length=0;
    if (status==17) token=(uint8_t)(component?'Y':'X');
    else if (status==18) token=component?0xc4:(r->memory[0x8127]?0x9d:'r');
    else if (status==19) {
        if (component) { memcpy(text,"L-R",3); length=3; }
        else {
            size_t position=0x1056u+r->memory[0x83fc];
            token=position<r->rom_size?r->rom[position]:0;
        }
    } else if (status==20) { if (component) token='R'; }
    else if (!component) token='F';
    if (token) text[length++]=token;
    if (length) text[length++]='=';
    text[length]=0;
    return length;
}

/* C1F0 appends all16 ROM spaces before inserting the earlier NUL.
 * Keep the dormant writes after that NUL in persistent result scratch. */
static int component_row(fx_render *r, unsigned component,
                          const uint8_t *number, size_t added,
                          uint8_t row[1024], size_t *length, size_t *written)
{
    *length=label(r,component,row); *written=*length+1;
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

int fx_display_pair_result(fx_render *r, uint16_t address, fx_box *box)
{
    uint8_t mode=r->memory[0x80f9], font=r->memory[0x811f];
    if ((mode!=1 && mode!=65 && mode!=129 && mode!=193 && mode!=196 && mode!=136)
        || (font!=6 && font!=7 && font!=10) || !(r->memory[0x80ff]&0x10)
        || r->memory[0x8127] || !fx_display_has_formula_view(r)
        || r->rom_size<=0x1add) return -1;
    int permitted=fx_display_has_natural_input(r)||fx_display_has_natural_result(r);
    if (permitted && !(mode&0xc0)) return -1;
    /* 3658 drops the complete previous-kind nibble and invalidates cache. */
    if (r->memory[0x80ff]==19 || !permitted) {
        r->memory[0x8100]=10; r->memory[0x8130]=0;
    }
    uint8_t selection=r->memory[0x8100]&15;
    int natural=permitted && selection!=10;
    uint16_t persistent=mode==136 || !(mode&0x80)?0x8546:0x8398;
    if (natural) r->memory[0x8127]=1;
    if (permitted && r->memory[0x8130]) {
        save_history(r,NULL,0,persistent,selection,1);
        if (!fx_display_has_natural_input(r)) fx_clear_from_row(r,22);
        r->memory[0x8126]=1;
        uint16_t previous=word_at(r,0x812c); put_word(r,0x812c,persistent);
        int success=fx_render_viewport(r,box);
        put_word(r,0x812c,previous); r->memory[0x8127]=0; return success;
    }
    if (address<0x8000 || address>0xffec) { r->memory[0x8127]=0; return -1; }
    fx_complex value; memcpy(&value,r->memory+address,sizeof value);
    uint8_t real_class,imaginary_class;
    if (fx_scalar_numeric_classify(&real_class,&value.real)!=FX_NUMERIC_OK
        || fx_scalar_numeric_classify(&imaginary_class,&value.imaginary)!=FX_NUMERIC_OK) {
        r->memory[0x8127]=0; return -1;
    }
    if (permitted) r->memory[persistent]=0;
    r->memory[0x8114]=0;
    if (!rectangular(r) && !(real_class==1 && imaginary_class==1)
        && !(dms_first(r,&value.real) && imaginary_class==1 && real_class==4)) {
        uint8_t unit=r->memory[0x8105];
        if (unit<4 || unit>6 || fx_complex_to_polar(&value,&value,
            (fx_angle_unit)(unit-4),fx_exact_output_allowed(r->memory))!=FX_NUMERIC_OK) {
            r->memory[0x8127]=0; return -1;
        }
    }
    if (!permitted) fx_clear_from_row(r,12);
    uint8_t first[1024]={0},second[1024]={0},formatted[512],history[2048]={0};
    size_t first_length,second_length,first_written,second_written;
    fx_format_result real_result,imaginary_result;
    if (!format_component(r,&value.real,formatted,&real_result)
        || !component_row(r,0,formatted,real_result.length,first,&first_length,&first_written))
        goto failure;
    if (permitted) memcpy(r->memory+persistent,first,first_written);
    if (!format_component(r,&value.imaginary,formatted,&imaginary_result)
        || !component_row(r,1,formatted,imaginary_result.length,second,&second_length,&second_written))
        goto failure;
    (void)second_written;
    if (selection) {
        uint8_t kind=fx_combine_result_kinds(real_result.kind,imaginary_result.kind);
        r->memory[0x8100]=(uint8_t)((r->memory[0x8100]&15)|(kind<<4));
    }
    if (natural) {
        uint16_t delimiter=r->memory[0x8104]?0x1ada:0x1adc;
        size_t delimiter_length=0;
        while ((size_t)delimiter+delimiter_length<r->rom_size
            && r->rom[delimiter+delimiter_length]) ++delimiter_length;
        if (!append(first,&first_length,sizeof first,r->rom+delimiter,delimiter_length)
            || !append(first,&first_length,sizeof first,second,second_length)) goto failure;
        put_text(r,persistent,first,first_length);
        save_history(r,NULL,0,persistent,selection,1);
        if (!fx_display_has_natural_input(r)) fx_clear_from_row(r,22);
        r->memory[0x8126]=1;
        uint16_t previous=word_at(r,0x812c); put_word(r,0x812c,persistent);
        int success=fx_render_viewport(r,box);
        put_word(r,0x812c,previous); r->memory[0x8127]=0; return success;
    }
    if (permitted) {
        size_t maximum=first_length>second_length?first_length:second_length;
        if ((uint8_t)(r->memory[0x8115]+(uint8_t)(maximum*6))>90) {
            uint8_t requested=first_length?20:10;
            uint8_t previous=r->memory[0x8128]?r->memory[0x8128]:10;
            /* Native total>=63 makes3922's retained-byte count wrap,
             * reaching the CPU stack and corrupting B070's return frame.
             * Preserve the preceding format writes, expose the boundary,
             * and leave architectural stack emulation to the caller. */
            if ((uint8_t)(requested+previous)>62) {
                r->memory[0x8127]=0; return -1;
            }
            fx_make_result_space(r,requested);
        }
    }
    draw_row(r,first,first_length,12); draw_row(r,second,second_length,22);
    size_t history_length=0;
    if (first_length) {
        uint8_t newline=13;
        if (!append(history,&history_length,sizeof history,first,first_length)
            || !append(history,&history_length,sizeof history,&newline,1)) goto failure;
    }
    if (!append(history,&history_length,sizeof history,second,second_length)) goto failure;
    save_history(r,history,history_length,0,selection,0);
    if (box) {
        box->width=(uint16_t)((first_length>second_length?first_length:second_length)*6);
        box->height=(uint8_t)(first_length?20:10); box->depth=fx_font_depth(r);
    }
    r->memory[0x8127]=0; return 1;
failure:
    r->memory[0x8127]=0; return 0;
}
