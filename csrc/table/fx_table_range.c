/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_table_presentation.h"
#include "../platform/fx_platform.h"
#include "../render/fx_render.h"
#include "../render/fx_render_context.h"
#include "../ui/fx_editor.h"
#include "../ui/fx_keys.h"
#include "../ui/fx_key_dispatch.h"
#include <string.h>

/* DE7E's TABLE range prefix ends at its named whole-D9EE call. */
int fx_table_prepare_range_prompt(fx_platform *p,uint8_t item,
                                           uint8_t *refresh)
{
    if(!p||!p->ram||!p->rom||!refresh||p->ram[0x80f9]!=0x88||item<1||item>3)return -1;
    uint16_t label=(uint16_t)(0x1164+8*(item-1));unsigned n;
    for(n=0;n<16;n++){
        uint8_t b=fx_data_read(p,0,(uint16_t)(label+n));p->ram[0x8154+n]=b;
        if(!b)break;
    }
    if(n==16)return -1;
    memset(p->ram+0x814a,0,10);
    memmove(p->ram+0x8140,p->ram+0x829e + 10*(item-1),10);
    fx_render r={p->rom,p->rom_size,p->ram};fx_clear_framebuffer(&r);
    p->ram[0x811f]=10;p->ram[0x80fe]=4;
    *refresh=(uint8_t)!fx_key_is_menu_token(p,p->ram[0x80f5]);
    return 0;
}

/*1EE7C actual88 function/range expression refresh. Result-line publication
 * and outer D9EE context/return handling belong to the main INPUT host. */
int fx_table_refresh_expression(fx_platform *p)
{
    if(!p||!p->ram||!p->rom||p->ram[0x80f9]!=0x88||
       (p->ram[0x80fc]!=1 && p->ram[0x80fc]!=6))return -1;
    fx_render r={p->rom,p->rom_size,p->ram};int editing=p->ram[0x80fe]==1;
    p->ram[0x8126]=(uint8_t)editing;
    if(!editing)p->ram[0x8114]=0;
    if(!editing && fx_display_is_special_view(&r)){
        uint16_t text=(uint16_t)(p->ram[0x812c]|p->ram[0x812d]<<8);
        fx_draw_text(&r,0,1,&text);return 0;
    }
    if(fx_editor_has_natural_input(p)){
        uint8_t flags=p->ram[0x80f8];
        if(flags&128)p->ram[0x80f8]=(uint8_t)((flags+128)&~8u);
        return fx_render_viewport(&r,NULL) ? 0 : -1;
    }
    return fx_table_draw_linear_expression(p);
}
