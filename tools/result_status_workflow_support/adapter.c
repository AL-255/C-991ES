/* SPDX-License-Identifier: GPL-3.0-only */
#include "../../csrc/render/fx_result_status_workflow.h"
#include <stddef.h>
#pragma GCC visibility push(default)
int workflow_display(fx_render*r,uint16_t a,fx_box*b){return fx_display_status_workflow(r,a,b);}
int workflow_query(fx_render*r,int which,uint8_t*out){return which?fx_result_equation_rectangular(r,out):fx_result_equation_is_vertex(r,out);}
int workflow_format(fx_render*r,const fx_number*n,uint8_t ctx,uint8_t*out,fx_format_result*f){return fx_format_status_component(r,n,ctx,out,f);}
void workflow_flush(fx_render*r){fx_flush_framebuffer(r);}
size_t workflow_abi(unsigned field)
{
    switch(field) {
    case 0:return sizeof(fx_number);
    case 1:return sizeof(fx_render);
    case 2:return offsetof(fx_render,memory);
    case 3:return sizeof(fx_format_result);
    case 4:return offsetof(fx_format_result,kind);
    case 5:return sizeof(fx_box);
    default:return (size_t)-1;
    }
}
#pragma GCC visibility pop
