/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_table_body.h"
#include "fx_table_presentation.h"
#include <string.h>
enum { BODY_CONTROLLER=1,BODY_INPUT,BODY_DONE,BODY_RESET };
static fx_ui_status controller_status(fx_table_body *s,fx_table_controller_status status)
{
    if(status==FX_TABLE_CONTROLLER_REQUEST){s->phase=BODY_CONTROLLER;return FX_UI_PREPARED;}
    if(status==FX_TABLE_CONTROLLER_WAIT)return FX_UI_WAIT;
    if(status==FX_TABLE_CONTROLLER_EXPORT)return FX_UI_EXPORT;
    if(status==FX_TABLE_CONTROLLER_RESET){s->phase=BODY_RESET;return FX_UI_RESET;}
    if(status<0)return status==FX_TABLE_CONTROLLER_RESOURCE_LIMIT ? FX_UI_RESOURCE_LIMIT : FX_UI_UNIMPLEMENTED;
    if(status!=FX_TABLE_CONTROLLER_COMPLETE)return FX_UI_INVALID;
    if(fx_table_controller_finish(&s->table,&s->returned)!=FX_TABLE_CONTROLLER_COMPLETE)return FX_UI_INVALID;
    s->phase=BODY_DONE;return FX_UI_COMPLETE;
}
fx_ui_status fx_table_body_begin(fx_platform *p,fx_table_body *s,
    fx_main_request operation,const fx_calculus_control *control)
{
    if(!p||!p->ram||!s)return FX_UI_INVALID;
    memset(s,0,sizeof *s);s->active=1;s->operation=operation;
    if(control)s->cancellation=*control;
    if(p->ram[0x80f9]!=0x88)return FX_UI_UNIMPLEMENTED;
    if(operation==FX_MAIN_SCREEN18_ADMISSION && p->ram[0x80fc]==18){
        /* F02C initializes a false admission result. Its only body requires
         * actual STAT12; TABLE88 therefore returns that result unchanged. */
        s->phase=BODY_DONE;return FX_UI_COMPLETE;
    }
    fx_table_controller_status status;
    if(operation==FX_MAIN_SCREEN6 && p->ram[0x80fc]==6)
        status=fx_table_controller_range_key(p,&s->table,p->ram[0x80f5]);
    else if(operation==FX_MAIN_SCREEN18 && p->ram[0x80fc]==18)
        status=fx_table_controller_navigate(p,&s->table,p->ram[0x80f5]);
    else return FX_UI_UNIMPLEMENTED;
    return controller_status(s,status);
}
fx_ui_status fx_table_body_tick(fx_platform *p,fx_table_body *s)
{
    if(!p||!s||!s->active)return FX_UI_INVALID;
    if(s->phase==BODY_DONE)return FX_UI_COMPLETE;
    if(s->phase==BODY_RESET)return FX_UI_RESET;
    if(s->phase==BODY_INPUT){
        fx_ui_status status=fx_ui_controller_tick(p,&s->input);
        if(status==FX_UI_RESET){s->phase=BODY_RESET;return status;}
        if(status!=FX_UI_COMPLETE)return status;
        uint8_t returned;
        if(fx_ui_controller_finish(&s->input,&returned)!=FX_UI_COMPLETE)return FX_UI_INVALID;
        return controller_status(s,fx_table_controller_accept_handler(p,&s->table,returned));
    }
    if(s->phase!=BODY_CONTROLLER)return FX_UI_INVALID;
    uint8_t refresh=0;
    switch(s->table.request){
    case FX_TABLE_REQUEST_RANGE_PROMPT:
        if(fx_table_prepare_range_prompt(p,s->table.argument,&refresh))return FX_UI_UNIMPLEMENTED;
        /* DF34 and E1D2 invoke whole INPUT. */
        /* fall through */
    case FX_TABLE_REQUEST_INPUT_ACTION: {
        fx_ui_status status=fx_ui_controller_begin(p,&s->input,refresh,&s->cancellation);
        if(status==FX_UI_PREPARED)s->phase=BODY_INPUT;
        return status;
    }
    case FX_TABLE_REQUEST_GRID_PAINT:
    case FX_TABLE_REQUEST_SELECTED_RESULT:
        if(fx_table_present_request(p,&s->table))return FX_UI_UNIMPLEMENTED;
        return controller_status(s,fx_table_controller_accept_handler(p,&s->table,0));
    case FX_TABLE_REQUEST_NONE:
        return controller_status(s,fx_table_controller_tick(p,&s->table));
    default:return FX_UI_UNIMPLEMENTED;
    }
}
uint8_t fx_table_body_export_mask(const fx_table_body *s)
{
    if(!s)return 0;
    return s->phase==BODY_INPUT ? fx_ui_controller_export_mask(&s->input) : s->table.error.key.export_mask;
}
