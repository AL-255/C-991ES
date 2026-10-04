/* Readable B070 complex/polar display, without firmware execution.
 * GPL-3.0-or-later. */
#include "fx_result_complex.h"
#include "fx_render_context.h"
#include "fx_render_memory.h"
#include "fx_result_format_state.h"
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
static void raw_exponents(uint8_t *text, size_t length)
{
    for (size_t n=0;n+2<length;++n) {
        if (text[n]!=0x90 || (text[n+1]!=0x91 && text[n+1]!=0x92)) continue;
        text[n]+=80; text[++n]+=80;
        while (n+1<length && text[n+1]>=0xa0 && text[n+1]<=0xaf) text[++n]+=80;
    }
}
/* C060 alone: preserve the previous-kind nibble until B070's final3634. */
static int format_component(fx_render *r, const fx_number *number, uint8_t context,
                             uint8_t text[512], fx_format_result *result)
{
    fx_format_options options=fx_format_default_options();
    options.selection=r->memory[0x8100];
    options.math_output=(uint8_t)fx_display_has_natural_result(r);
    options.mixed_fraction=r->memory[0x8107];
    options.display_mode=r->memory[0x8102]; options.digits=r->memory[0x8103];
    options.decimal_dot=r->memory[0x8104]; options.format_context=context;
    if (fx_format_number(number,&options,text,512,result)!=FX_FORMAT_OK) return 0;
    if (r->memory[0x8127]) raw_exponents(text,result->length);
    fx_apply_result_format_state(r,number,options.selection,result->kind);
    r->memory[0x8100]=(uint8_t)((options.selection&0xf0)|(r->memory[0x8100]&15));
    return 1;
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
int fx_display_complex_result(fx_render *r, uint16_t address, fx_box *box)
{
    uint8_t mode=r->memory[0x80f9], selection=r->memory[0x8100]&15;
    uint8_t font=r->memory[0x811f];
    if ((mode!=1 && mode!=65 && mode!=129 && mode!=193 && mode!=196 && mode!=136)
        || (font!=6 && font!=7 && font!=10) || (r->memory[0x80ff]&0x10)
        || r->memory[0x8127] || (!fx_display_has_formula_view(r)
            && !(r->memory[0x80fc]==0xa0 && r->memory[0x80fd]==2))) return -1;
    int permitted=fx_display_has_natural_input(r)||fx_display_has_natural_result(r);
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
        int result=fx_render_viewport(r,box);
        put_word(r,0x812c,previous); r->memory[0x8127]=0; return result;
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
    int rect=rectangular(r); uint8_t real_context=0;
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
    size_t first_length=0,second_length=0; uint8_t real_kind=0xf0;
    int real_included=real_class!=1 || imaginary_class==1;
    fx_format_result result;
    if (real_included) {
        if (!format_component(r,&value.real,real_context,formatted,&result)) goto formatting_failure;
        if (!append(first,&first_length,sizeof first,formatted,result.length)) goto formatting_failure;
        real_kind=result.kind;
    }
    if (imaginary_class==1) {
        r->memory[0x8100]=(uint8_t)((r->memory[0x8100]&15)|(real_kind<<4));
        if (!natural) {
            memcpy(second,first,first_length+1); second_length=first_length;
            first[0]=0; first_length=0;
        }
    } else {
        uint8_t context=real_included?(rect?1:(imaginary_class==2?2:5)):(imaginary_class==2?3:4);
        if (!format_component(r,&value.imaginary,context,formatted,&result)) goto formatting_failure;
        size_t length=result.length;
        if (rect) {
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
        if (!append(second,&second_length,sizeof second,formatted,length)) goto formatting_failure;
        if (selection) {
            uint8_t kind=fx_combine_result_kinds(real_kind,result.kind);
            r->memory[0x8100]=(uint8_t)((r->memory[0x8100]&15)|(kind<<4));
        }
    }
    if (natural) {
        if (!append(first,&first_length,sizeof first,second,second_length)) goto formatting_failure;
        put_text(r,persistent,first,first_length);
        /* History eligibility uses the initial selection, not a DMS/ENG
         * fallback selection produced by one of the component calls. */
        save_history(r,NULL,0,persistent,selection,1);
        if (!fx_display_has_natural_input(r)) fx_clear_from_row(r,22);
        r->memory[0x8126]=1; uint16_t previous=word_at(r,0x812c); put_word(r,0x812c,persistent);
        int success=fx_render_viewport(r,box);
        put_word(r,0x812c,previous); r->memory[0x8127]=0; return success;
    }
    if (permitted) {
        put_text(r,persistent,first,first_length);
        size_t maximum=first_length>second_length?first_length:second_length;
        if ((uint8_t)(r->memory[0x8115]+(uint8_t)(maximum*6))>90)
            fx_make_result_space(r,first_length?20:10);
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
