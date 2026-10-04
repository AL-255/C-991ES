/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_table_presentation.h"
#include "../render/fx_render.h"
#include "../render/fx_result_linalg.h"
#include "../render/fx_result_special.h"
#include "fx_table_controller.h"
#include <string.h>

static void row_label(uint8_t raw, uint8_t text[8])
{
    int signed_row=(int8_t)raw;
    unsigned value=(unsigned)(signed_row<0 ? -signed_row : signed_row),n=0;
    if(signed_row<0)text[n++]=0xdb;
    if(value>=100)text[n++]=(uint8_t)(0xd0+value/100);
    if(value>=10)text[n++]=(uint8_t)(0xd0+(value/10)%10);
    text[n++]=(uint8_t)(0xd0+value%10);text[n]=0;
    /*3F3A's short row-number field pads then retains its first character.
     * Signed negative byte rows consequently show only their sign. */
    if(signed_row<=9){text[1]=text[0];text[0]=0xec;text[2]=0;}
}

int fx_table_paint_grid(fx_platform *p, uint8_t columns)
{
    if(!p||!p->ram||!p->rom||p->ram[0x80f9]!=0x88||columns<2||columns>3||p->ram[0x811c]>=253)return -1;
    fx_render r={p->rom,p->rom_size,p->ram};fx_clear_framebuffer(&r);p->ram[0x811f]=6;
    for(unsigned i=0;i<3;i++){
        uint8_t text[8];row_label((uint8_t)(p->ram[0x811c]+i),text);
        for(unsigned n=0;text[n];n++)fx_draw_glyph(&r,(uint8_t)(1+4*n),(int8_t)(7+6*i),text[n]);
    }
    uint16_t label=0x117c;fx_draw_text(&r,12,1,&label);
    label=0x118f;fx_draw_text(&r,40,1,&label);
    if(p->ram[0x810e]==1 && !(p->ram[0x8138]&0x80)){label=0x1195;fx_draw_text(&r,68,1,&label);}
    for(unsigned row=0;row<3;row++)for(unsigned col=0;col<columns;col++){
        uint8_t physical_row=(uint8_t)(p->ram[0x811c]+row);fx_number n,*cell=NULL;
        if(physical_row<=p->ram[0x80de]){
            uint16_t a=(uint16_t)(0x82ee + 10*(columns*(unsigned)(uint8_t)(physical_row-1)+col));
            memcpy(n.bytes,p->ram+a,10);cell=&n;
        }
        if(fx_display_linalg_cell(&r,cell,(uint8_t)(row+1),(uint8_t)(col+1),row+1==p->ram[0x811d] && col+1==p->ram[0x811e])!=1)return -1;
    }
    for(unsigned col=0;col<=columns;col++)fx_draw_vertical(&r,(uint8_t)(10+28*col),1,24,0);
    return 0;
}

int fx_table_present_request(fx_platform *p,fx_table_controller *state)
{
    if(!p||!state)return -1;
    if(state->request==FX_TABLE_REQUEST_GRID_PAINT)return fx_table_paint_grid(p,state->columns);
    if(state->request==FX_TABLE_REQUEST_SELECTED_RESULT){fx_render r={p->rom,p->rom_size,p->ram};return fx_display_special_real_result(&r,state->selected_address,NULL)==1 ? 0 : -1;}
    return -1;
}
