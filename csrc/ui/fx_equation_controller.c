/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_equation_controller.h"
#include "fx_mode_setup.h"
#include "fx_equation_result.h"
#include <string.h>
#include "../platform/fx_persistent.h"
#include "../render/fx_result_linalg.h"
#include "../render/fx_result_special.h"
static uint8_t get(fx_platform *p,uint16_t a) {return fx_data_read(p,0,a);}
static void put(fx_platform *p,uint16_t a,uint8_t b) {fx_data_write(p,0,a,b);}
static uint16_t word(fx_platform *p,uint16_t a)
{return (uint16_t)(get(p,a)|(uint16_t)get(p,(uint16_t)(a+1))<<8);}
static int domain(fx_platform *p)
{return p&&p->ram&&p->rom&&get(p,0x80f9)==0x45&&
 get(p,0x80fa)>=1&&get(p,0x80fa)<=2&&get(p,0x80fc)==21;}
static uint16_t selected(fx_platform *p)
{return word(p,(uint16_t)(0xfde + 18u*get(p,0x811c)+6u*get(p,0x811d)+2u*get(p,0x811e)));}
int fx_equation_move_selection(fx_platform *p,uint8_t token)
{
 if (!domain(p))return -1;
 uint8_t kind=get(p,0x80fa),page=get(p,0x811c),row=get(p,0x811d),column=get(p,0x811e);
 uint8_t rows=(uint8_t)(kind+1),columns=(uint8_t)(kind+2),pages=(uint8_t)(kind==2?2:1);
 if (!page||page>pages||!row||row>rows||!column||column>3)return -1;
 int moved=0;
 switch(token){
 case 0xe0:if(row>1){--row;moved=1;}break;
 case 0xe1:if(row<rows){++row;moved=1;}break;
 case 0xe2:case 0xed:
  if(column<3){++column;moved=1;}
  else if(page==1&&column+page<columns+1){++page;moved=1;}
  else if(row<rows){++row;page=column=1;moved=1;}
  break;
 case 0xe3:
  if(column>1){--column;moved=1;}
  else if(page>1){--page;moved=1;}
  else if(row>1){--row;column=3;page=pages;moved=1;}
  break;
 default:break;
 }
 if(moved){put(p,0x811c,page);put(p,0x811d,row);put(p,0x811e,column);fx_result_clear_display_state(p);}
 return moved?0:1;
}
int fx_equation_commit_coefficient(fx_platform *p,uint16_t source)
{
 if(!domain(p)||source<0x8000||source>65526)return -1;
 uint8_t page=get(p,0x811c),row=get(p,0x811d),column=get(p,0x811e);
 uint8_t kind=get(p,0x80fa);
 if(!page||page>(kind==2?2:1)||!row||row>kind+1||!column||column>3)return -1;
 uint16_t destination=selected(p);
 if(destination<0x829e||destination>0x8352)return -1;
 /* 5166/D142 first loads a word and then eight bytes into registers.
  * EA postincrement aligns the second read; all loads precede stores. */
 uint8_t value[10];
 value[0]=get(p,source);value[1]=get(p,(uint16_t)(source+1));
 uint16_t tail=(uint16_t)((source+2u)&0xfffeu);
 for(unsigned n=0;n<8;++n)value[n+2]=get(p,(uint16_t)(tail+n));
 for(unsigned n=0;n<10;++n)put(p,(uint16_t)(destination+n),value[n]);
 if(fx_equation_move_selection(p,0xed)<0)return -1;
 put(p,0x80fd,1);put(p,0x80fe,3);return 0;
}
static void draw_host(fx_render *r,uint8_t x,uint8_t y,const uint8_t *text)
{
 unsigned advance=r->memory[0x811f]==6?4:6;
 for(unsigned n=0;text[n]&&n<24&&x<=96-advance;++n,x=(uint8_t)(x+advance))
  fx_draw_glyph(r,x,(int8_t)y,text[n]);
}
int fx_equation_present_coefficients(fx_platform *p)
{
 if(!domain(p))return -1;
 uint8_t kind=get(p,0x80fa),page=get(p,0x811c),row=get(p,0x811d),column=get(p,0x811e);
 if(!page||page>(kind==2?2:1)||!row||row>kind+1||!column||column>3)return -1;
 uint16_t current=selected(p);
 for(unsigned n=0;n<10;++n)put(p,(uint16_t)(0x814a+n),0);
 fx_number number;
 if(current)for(unsigned n=0;n<10;++n)number.bytes[n]=get(p,(uint16_t)(current+n));
 else fx_number_error(&number,13);
 for(unsigned n=0;n<10;++n)put(p,(uint16_t)(0x8140+n),number.bytes[n]);
 if(fx_key_is_menu_token(p,get(p,0x80f5)))return -2;
 fx_render r={p->rom,p->rom_size,p->ram};fx_clear_framebuffer(&r);
 uint8_t caption[6];for(unsigned n=0;n<6;++n)caption[n]=get(p,(uint16_t)(0x119b+n));
 caption[2]=(uint8_t)(caption[2]+page-1);put(p,0x811f,6);
 for(unsigned n=0;n<3;++n){draw_host(&r,(uint8_t)(12+28*n),1,caption);++caption[2];}
 uint8_t label[6];for(unsigned n=0;n<6;++n)label[n]=get(p,(uint16_t)(0x119f+n));
 for(unsigned n=0;n<kind+1u;++n){draw_host(&r,5,(uint8_t)(7+6*n),label);++label[0];}
 uint16_t a=(uint16_t)(0x102e + 4u*kind);
 fx_draw_vertical(&r,get(p,a),get(p,(uint16_t)(a+1)),get(p,(uint16_t)(a+2)),page==1?get(p,(uint16_t)(a+3)):0);
 if(page!=1||kind!=2){a=(uint16_t)(0x103e + 4u*kind);fx_draw_vertical(&r,get(p,a),get(p,(uint16_t)(a+1)),get(p,(uint16_t)(a+2)),get(p,(uint16_t)(a+3)));}
 fx_linalg_value value;value.rows=(uint8_t)(kind+1);value.columns=3;
 for(unsigned i=0;i<9;++i)fx_number_zero(&value.cells[i]);
 for(unsigned i=0;i<value.rows*3u;++i){uint16_t ptr=word(p,(uint16_t)(0xff8+18u*(page-1)+2u*i));
  for(unsigned n=0;n<10;++n)value.cells[i].bytes[n]=get(p,(uint16_t)(ptr+n));}
 if(fx_display_linalg_grid(&r,&value,row,column)!=1)return -1;
 put(p,0x811f,7);return fx_display_special_real_number(&r,&number,NULL)==1?0:-1;
}

/* E862/E906 retain their outer return1 even when nested whole INPUT returns0. */
fx_ui_status fx_equation_controller_begin(fx_platform *p,fx_equation_controller *s,
    const fx_calculus_control *control)
{
    if (!domain(p)||!s) return FX_UI_INVALID;
    fx_calculus_control saved={0};
    if(control)saved=*control;
    memset(s,0,sizeof *s);s->cancellation=saved;s->active=1;s->returned=1;
    uint8_t token=get(p,0x80f5);
    if((token==0xed||token==0xf0)&&!get(p,0x80fd)) {
        fx_solver_result numerical;
        if(fx_equation_solve_linear_controlled(p,&s->returned,&numerical,&s->cancellation))return FX_UI_UNIMPLEMENTED;
        s->phase=3;return FX_UI_COMPLETE;
    }
    put(p,0x8129,0);put(p,0x80fd,0);
    if(fx_key_is_direction_token(p,token)) {
        (void)fx_acquire_busy(p);
        int moved=fx_equation_move_selection(p,token);
        if(moved<0)return FX_UI_UNIMPLEMENTED;
        if(moved){fx_clear_busy(p);s->phase=3;return FX_UI_COMPLETE;}
    } else if(token==0xe6) {
        fx_result_clear_flags(p);fx_mode_initialize_equation(p,21);
    }
    int shown=fx_equation_present_coefficients(p);
    if(shown==-2) {
        s->phase=2;
        return fx_ui_controller_begin(p,&s->input,0,&s->cancellation);
    }
    if(shown)return FX_UI_UNIMPLEMENTED;
    s->phase=3;return FX_UI_COMPLETE;
}
fx_ui_status fx_equation_controller_tick(fx_platform *p,fx_equation_controller *s)
{
    if(!p||!s||!s->active)return FX_UI_INVALID;
    if(s->phase==3)return FX_UI_COMPLETE;
    if(s->phase!=2)return FX_UI_UNIMPLEMENTED;
    fx_ui_status status=fx_ui_controller_tick(p,&s->input);
    if(status==FX_UI_COMPLETE) {
        uint8_t returned;
        if(fx_ui_controller_finish(&s->input,&returned)!=FX_UI_COMPLETE)return FX_UI_INVALID;
        s->phase=3;
    }
    return status;
}
fx_ui_status fx_equation_controller_finish(fx_equation_controller *s,uint8_t *returned)
{
    if(!s||!s->active||s->phase!=3)return FX_UI_INVALID;
    if(returned)*returned=s->returned;
    s->active=0;return FX_UI_COMPLETE;
}
