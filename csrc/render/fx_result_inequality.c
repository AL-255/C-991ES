/* Readable equation captions and inequality result display. GPL-3.0-or-later. */
#include "fx_result_inequality.h"
#include "fx_render_context.h"
#include "fx_result_format_state.h"
#include "../format/fx_format.h"
#include "../format/fx_format_budget.h"
#include <string.h>

static uint8_t byte_at(const fx_render *render, uint16_t address)
{
    return address < 0x8000 ? (address < render->rom_size ? render->rom[address] : 0)
                            : render->memory[address];
}
static uint16_t word_at(const fx_render *render, uint16_t address)
{
    return (uint16_t)(byte_at(render,address) | (uint16_t)byte_at(render,(uint16_t)(address+1)) << 8);
}
static void put_byte(fx_render *render, uint16_t address, uint8_t value)
{
    if (address >= 0x8000) render->memory[address] = value;
}
static void put_word(fx_render *render, uint16_t address, uint16_t value)
{
    put_byte(render,address,(uint8_t)value);
    put_byte(render,(uint16_t)(address+1),(uint8_t)(value>>8));
}
static size_t text_at(const fx_render *render, uint16_t address, uint8_t *text, size_t capacity)
{
    if (!address && capacity) { text[0]=0; return 0; }
    for (size_t n=0;n<capacity;++n,++address) {
        text[n]=byte_at(render,address);
        if (!text[n]) return n;
    }
    return capacity;
}
static int append_text(uint8_t *destination, size_t *length, size_t capacity,
                        const uint8_t *text, size_t added)
{
    if (added >= capacity || *length >= capacity-added) return 0;
    if (added) memcpy(destination+*length,text,added);
    *length+=added; destination[*length]=0;
    return 1;
}
static int append_spelling(const fx_render *render, uint8_t *text, size_t *length,
                            size_t capacity, uint16_t source)
{
    uint8_t spelling[32];
    size_t added=text_at(render,source,spelling,sizeof spelling);
    return added<sizeof spelling && append_text(text,length,capacity,spelling,added);
}

/* These actions are the semantic content of the three B60E dispatch tables,
 * not executable addresses. Their spelling remains actual ROM data. */
enum relation_action { NO_RELATION, X_EQUAL, X_GREATER_EQUAL, X_LESS, X_LESS_EQUAL,
    LESS_X, LESS_EQUAL_X, LESS_X_LESS, LESS_EQUAL_X_LESS_EQUAL,
    SEPARATOR, SEPARATOR_X_LESS, SEPARATOR_X_EQUAL, LESS_X_SEPARATOR_X_GREATER_EQUAL };
static size_t relation_text(const fx_render *render, uint8_t part, uint8_t solution,
                             uint8_t text[32])
{
    static const uint8_t first[18]={X_EQUAL,X_GREATER_EQUAL,X_LESS,X_LESS_EQUAL,
        NO_RELATION,NO_RELATION,NO_RELATION,NO_RELATION,X_LESS,X_LESS_EQUAL,
        X_EQUAL,X_GREATER_EQUAL,X_LESS_EQUAL,NO_RELATION,NO_RELATION,NO_RELATION,
        X_LESS,X_LESS_EQUAL};
    static const uint8_t second[14]={LESS_X,LESS_EQUAL_X,LESS_X_LESS,LESS_EQUAL_X_LESS_EQUAL,
        SEPARATOR,SEPARATOR,SEPARATOR,SEPARATOR_X_LESS,SEPARATOR_X_EQUAL,
        LESS_X_SEPARATOR_X_GREATER_EQUAL,LESS_X_LESS,LESS_EQUAL_X_LESS_EQUAL,
        SEPARATOR,SEPARATOR};
    static const uint8_t third[10]={LESS_X,LESS_EQUAL_X,LESS_EQUAL_X,NO_RELATION,
        NO_RELATION,NO_RELATION,SEPARATOR,SEPARATOR,LESS_X_LESS,LESS_EQUAL_X_LESS_EQUAL};
    unsigned action=NO_RELATION;
    if (!part && solution>=3 && solution<=20) action=first[solution-3];
    else if (part==1 && solution>=7 && solution<=20) action=second[solution-7];
    else if (part==2 && solution>=11 && solution<=20) action=third[solution-11];
    else if (part>=3 && solution==17) action=LESS_X;
    else if (part>=3 && solution==18) action=LESS_EQUAL_X;
    size_t length=0; text[0]=0;
    if (action>=X_EQUAL && action<=LESS_EQUAL_X_LESS_EQUAL)
        (void)append_spelling(render,text,&length,32,(uint16_t)(0x7e0+3*(action-X_EQUAL)+(action==LESS_EQUAL_X_LESS_EQUAL)));
    else {
        if (action==LESS_X_SEPARATOR_X_GREATER_EQUAL)
            (void)append_spelling(render,text,&length,32,0x7ec);
        if (action>=SEPARATOR)
            (void)append_spelling(render,text,&length,32,render->memory[0x8104]?0x1ada:0x1adc);
        if (action==SEPARATOR_X_LESS) (void)append_spelling(render,text,&length,32,0x7e6);
        if (action==SEPARATOR_X_EQUAL) (void)append_spelling(render,text,&length,32,0x7e0);
        if (action==LESS_X_SEPARATOR_X_GREATER_EQUAL) (void)append_spelling(render,text,&length,32,0x7e3);
    }
    return length;
}
uint16_t fx_append_inequality_relation(fx_render *render, uint16_t destination,
                                      uint8_t part, uint8_t solution)
{
    uint8_t text[32]; size_t length=relation_text(render,part,solution,text);
    uint16_t cursor=destination;
    unsigned n=0;
    while (byte_at(render,cursor) && n++<65536) ++cursor;
    if (n>=65536) return destination;
    for (size_t index=0;index<=length;++index,++cursor) put_byte(render,cursor,text[index]);
    return destination;
}
uint8_t fx_combine_result_kinds(uint8_t first, uint8_t second)
{
    if (first==0xf0) first=second;
    if (first==second) return first;
    uint8_t larger=first>second?first:second, smaller=first>second?second:first;
    return larger==13 && smaller!=10?smaller:larger;
}
static void draw_text(fx_render *render, const uint8_t *text, size_t length, uint8_t x, uint8_t y)
{
    unsigned advance=render->memory[0x811f]==6?4:6;
    unsigned maximum=render->memory[0x811f]==6?24:16;
    for (unsigned n=0;n<length && text[n] && x<=96-advance && n<maximum;++n,x=(uint8_t)(x+advance))
        fx_draw_glyph(render,x,(int8_t)y,text[n]);
}
static int padded_text(const uint8_t *prefix, size_t prefix_length,
                        const uint8_t *value, size_t value_length, uint8_t text[512], size_t *length)
{
    memset(text,0,512); *length=0;
    if (!append_text(text,length,512,prefix,prefix_length)) return 0;
    memset(text+*length,' ',16); *length+=16; text[*length]=0;
    /* C1F0/B4B0 subtract only the low length byte before widening the
     * insertion offset. For overlong text the preexisting NUL remains. */
    uint8_t cutoff=(uint8_t)(16-(uint8_t)value_length);
    text[cutoff]=0;
    *length=0; while (text[*length]) ++*length;
    return append_text(text,length,512,value,value_length);
}
int fx_display_equation_caption(fx_render *render, uint16_t destination, fx_box *box)
{
    if (destination<0x8000) return -1;
    uint8_t text[512], caption[36];
    uint16_t table=(uint16_t)(0x8dfa+2*(uint8_t)(render->memory[0x8135]-1));
    fx_clear_framebuffer(render); render->memory[0x811f]=10;
    size_t caption_length=text_at(render,word_at(render,table),caption,sizeof caption);
    if (caption_length==sizeof caption) return 0;
    size_t length;
    if (!padded_text(NULL,0,caption,caption_length,text,&length)) return 0;
    for (size_t n=0;n<=length;++n) put_byte(render,(uint16_t)(destination+n),text[n]);
    draw_text(render,text,length,0,22);
    render->memory[0x8100]=(uint8_t)((render->memory[0x8100]&15)|0xd0);
    if (box) { box->width=(uint16_t)(length*6); box->height=10; box->depth=5; }
    return 1;
}

/* Model the C060 call before the controller commits a combined kind with
 * 3634. The ordinary real adapter also captures recognition/LCD events;
 * retain the previous high nibble until the enclosing result is complete. */
static void component_state(fx_render *render, const fx_number *value,
                            uint8_t original, uint8_t ordinary_kind, int budgeted)
{
    uint8_t cache=render->memory[0x8130], selection=original&15, previous=original>>4;
    fx_apply_result_format_state(render,value,original,ordinary_kind);
    uint8_t current=render->memory[0x8100]&15;
    if (budgeted && ordinary_kind>=2 && ordinary_kind<=9) {
        current=selection;
        render->memory[0x8130]=cache;
        if (selection>10 && previous>=2 && previous<=9) {
            current=previous; render->memory[0x8130]=0;
        }
    }
    render->memory[0x8100]=(uint8_t)((original&0xf0)|current);
}
static int format_component(fx_render *render, const fx_number *value,
                             uint8_t text[512], fx_format_result *result)
{
    /* C060 handles error records before reading any format-status branch. */
    if ((value->bytes[0]&0xf0)!=0xf0 && (render->memory[0x80ff]&0x10)) return -1;
    fx_format_options options=fx_format_default_options();
    options.selection=render->memory[0x8100];
    options.math_output=(uint8_t)fx_display_has_natural_result(render);
    options.mixed_fraction=render->memory[0x8107];
    options.display_mode=render->memory[0x8102]; options.digits=render->memory[0x8103];
    options.decimal_dot=render->memory[0x8104];
    if (fx_format_number(value,&options,text,512,result)!=FX_FORMAT_OK) return 0;
    uint8_t ordinary_kind=result->kind;
    int budgeted=ordinary_kind>=2 && ordinary_kind<=10;
    if (budgeted && fx_format_budget(value,12,render->memory[0x8127]==1,
                                     render->memory[0x80ff]==20,options.decimal_dot,
                                     text,512,result)!=FX_FORMAT_OK) return 0;
    if (result->length>=36) return 0; /* original local formatting field */
    component_state(render,value,options.selection,ordinary_kind,budgeted);
    return 1;
}
static int viewport(fx_render *render, uint16_t expression, fx_box *box)
{
    render->memory[0x8126]=1;
    uint16_t previous=word_at(render,0x812c); put_word(render,0x812c,expression);
    int result=fx_render_viewport(render,box);
    put_word(render,0x812c,previous); render->memory[0x8127]=0;
    return result;
}
int fx_display_inequality_result(fx_render *render, fx_box *box)
{
    if (render->memory[0x80f9]!=75 || render->memory[0x80fc]!=1) return -1;
    uint8_t solution=render->memory[0x8406];
    if (solution<=2) {
        uint8_t caption[36], text[512]; size_t length;
        fx_clear_framebuffer(render); render->memory[0x811f]=10;
        uint16_t table=(uint16_t)(0x8df6+2*(uint8_t)(solution-1));
        size_t caption_length=text_at(render,word_at(render,table),caption,sizeof caption);
        if (caption_length==sizeof caption || !padded_text(NULL,0,caption,caption_length,text,&length)) return 0;
        draw_text(render,text,length,0,22);
        render->memory[0x8100]=(uint8_t)((render->memory[0x8100]&15)|0xd0);
        if (box) { box->width=(uint16_t)(length*6); box->height=10; box->depth=5; }
        return 1;
    }
    int natural=fx_display_has_natural_result(render);
    uint8_t selection=render->memory[0x8100]&15;
    uint16_t persistent=0x8546;
    render->memory[0x811f]=7;
    int recursive=natural && selection!=10;
    if (recursive) { render->memory[0x8127]=1; render->memory[0x811f]=10; }
    if (natural && render->memory[0x8130]) return viewport(render,persistent,box);
    if (natural) put_byte(render,persistent,0);
    render->memory[0x8114]=0; fx_clear_framebuffer(render);
    uint8_t banner[512], expression[512], relation[32], formatted[512], row[512];
    size_t banner_length=relation_text(render,0,solution,relation), expression_length=banner_length;
    memcpy(banner,relation,banner_length+1); memcpy(expression,relation,banner_length+1);
    unsigned count=solution>=17?3:solution>=9?2:1;
    uint8_t kind=10;
    for (unsigned n=0;n<count;++n) {
        fx_number value;
        for (unsigned index=0;index<10;++index) value.bytes[index]=byte_at(render,(uint16_t)(0x8410+10*n+index));
        fx_format_result result;
        int status=format_component(render,&value,formatted,&result);
        if (status!=1) return status;
        kind=fx_combine_result_kinds(kind,result.kind);
        uint8_t name[2]={(uint8_t)('A'+n),0};
        if (!append_text(banner,&banner_length,512,name,1)) return 0;
        size_t relation_length=relation_text(render,(uint8_t)(n+1),solution,relation);
        if (!append_text(banner,&banner_length,512,relation,relation_length)) return 0;
        if (recursive) {
            if (!append_text(expression,&expression_length,512,formatted,result.length)
                || !append_text(expression,&expression_length,512,relation,relation_length)) return 0;
        } else {
            uint8_t prefix[2]={name[0],'='}; size_t row_length;
            if (!padded_text(prefix,2,formatted,result.length,row,&row_length)) return 0;
            if (natural) {
                for (size_t index=0;index<=row_length;++index) put_byte(render,(uint16_t)(persistent+index),row[index]);
            }
            draw_text(render,row,row_length,0,(uint8_t)(8+7*n));
        }
    }
    draw_text(render,banner,banner_length,0,1);
    render->memory[0x8100]=(uint8_t)((render->memory[0x8100]&15)|(kind<<4));
    if (recursive) {
        for (size_t index=0;index<=expression_length;++index) put_byte(render,(uint16_t)(persistent+index),expression[index]);
        return viewport(render,persistent,box);
    }
    if (box) { box->width=(uint16_t)(banner_length*6); box->height=7; box->depth=3; }
    return 1;
}
