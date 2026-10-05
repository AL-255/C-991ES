/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_input_display.h"
#include "fx_editor.h"
#include "../render/fx_render.h"
#include <string.h>

static uint8_t byte_at(fx_platform *p, uint16_t a) { return fx_data_read(p,0,a); }
static uint16_t word_at(fx_platform *p, uint16_t a)
{ return (uint16_t)(byte_at(p,a)|(uint16_t)byte_at(p,(uint16_t)(a+1))<<8); }
static int terminal(fx_platform *p, uint8_t token)
{ return !token || ((byte_at(p,0x80fe)&64) && token==':'); }

/*36F0's character labels are ROM data. A high descriptor nibble15 appends
 * an implicit opening parenthesis; other high nibbles skip a label prefix. */
static int token_text(fx_platform *p, uint8_t token, uint8_t text[34])
{
    if (!token) { text[0]=0; return 0; }
    uint16_t table=0x1ade, descriptors=0x1cde;
    unsigned index=token;
    if (token>=0xc8 && token<0xcb && byte_at(p,0x80f9)==0xc1) {
        index=(uint8_t)(token+56); table=0x201e; descriptors=0x202c;
    }
    uint16_t source=word_at(p,(uint16_t)(table+2*index));
    uint8_t descriptor=byte_at(p,(uint16_t)(descriptors+index));
    unsigned length=descriptor&15,skip=descriptor>>4;
    /* Zero-length nonzero labels make native36F0 overrun its CPU local.
     * They are not a well-formed expression representation. */
    if (!length) return -1;
    if (skip!=15) source=(uint16_t)(source+skip);
    for (unsigned n=0;n<length;++n) text[n]=byte_at(p,source++);
    if (skip==15) text[length++]='(';
    text[length]=0; return (int)length;
}

static int label_width(fx_platform *p, uint8_t token)
{
    uint8_t text[34];
    if (terminal(p,token)) return 1;
    return token_text(p,token,text);
}

/*81B0: prefer the beginning when the expanded prefix through the cursor
 * fits; otherwise scan backwards from the cursor within the90-pixel row. */
static int first_visible(fx_platform *p, uint16_t source, uint8_t origin,
                          uint8_t cursor)
{
    unsigned available=(uint8_t)(90-origin);
    if (6u*(cursor+1u)<=available) {
        uint8_t labels=0;
        for (unsigned n=0;n<=cursor;++n) {
            uint8_t token=byte_at(p,(uint16_t)(source+n));
            int width=label_width(p,token);
            if (width<0) return -1;
            labels=(uint8_t)(labels+width);
            if (terminal(p,token)) break;
        }
        if (6u*labels<=available) return 0;
    }
    uint8_t index=cursor,remaining=(uint8_t)available;
    for (unsigned n=0;n<256;++n) {
        if (!remaining) return (uint8_t)(index+1);
        int labels=label_width(p,byte_at(p,(uint16_t)(source+index)));
        if (labels<0) return -1;
        unsigned width=(unsigned)labels*6;
        if (remaining<width) return (uint8_t)(index+1);
        remaining=(uint8_t)(remaining-width);
        if (!index) return 0;
        --index;
    }
    return -1;
}

static void draw_bytes(fx_render *r, uint8_t x, uint8_t y,
                        const uint8_t *text, size_t length)
{
    unsigned advance=r->memory[0x811f]==6 ? 4 : 6;
    unsigned maximum=r->memory[0x811f]==6 ? 24 : 16;
    for (unsigned n=0;n<length && text[n] && x<=96-advance && n<maximum;
         ++n,x=(uint8_t)(x+advance)) fx_draw_glyph(r,x,(int8_t)y,text[n]);
}

int fx_input_draw_linear_expression(fx_platform *p)
{
    if (!p || !p->ram || !p->rom) return -1;
    uint8_t mode=byte_at(p,0x80f9);
    if (mode!=0xc1 && mode!=0xc4 && mode!=6 && mode!=7 && mode!=0x45 && mode!=0x89) return -1;
    uint16_t source=word_at(p,0x812c);
    uint8_t origin=byte_at(p,0x8116),row=byte_at(p,0x8117);
    int first=first_visible(p,source,origin,byte_at(p,0x8114));
    if (first<0) return -1;
    uint8_t x=origin,index=(uint8_t)first,last=0;
    uint8_t text[256]; size_t length=0;
    for (unsigned n=0;n<256 && x<=96;++n) {
        if (index==byte_at(p,0x8114) && fx_editor_place_cursor(p,x,row)) return -1;
        last=byte_at(p,(uint16_t)(source+index));
        if (terminal(p,last)) break;
        uint8_t label[34]; int labels=token_text(p,last,label);
        if (labels<0 || length+(unsigned)labels>=sizeof text) return -1;
        if (!labels) break;
        memcpy(text+length,label,(unsigned)labels); length+=(unsigned)labels;
        x=(uint8_t)(x+labels*6); ++index;
    }
    uint8_t truncated=(uint8_t)!terminal(p,last);
    size_t actual_length=0;
    while (actual_length<length && text[actual_length]) ++actual_length;
    x=(uint8_t)(origin+actual_length*6);
    while (x<96) {
        if (length+1>=sizeof text) return -1;
        text[length++]=' '; x=(uint8_t)(x+6); truncated=0;
    }
    text[length]=0;
    fx_render r={p->rom,p->rom_size,p->ram};
    draw_bytes(&r,origin,row,text,length);
    if (first) { uint8_t marker=0x9f; draw_bytes(&r,origin,row,&marker,1); }
    if (truncated) {
        uint8_t marker=byte_at(p,0x8126) ? 0x9e : 0xbf;
        draw_bytes(&r,90,row,&marker,1);
    }
    fx_data_write(p,0,0x8116,0);
    return 0;
}
