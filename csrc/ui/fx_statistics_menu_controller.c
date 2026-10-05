/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_statistics_menu_controller.h"
#include "../platform/fx_boot.h"
#include "../platform/fx_persistent.h"
#include "../stats/fx_stats_editor.h"
#include <string.h>

enum { STAT_MENU=1,STAT_CONFIRM,STAT_COMPLETE,STAT_RESET };
static uint8_t get(fx_platform *p,uint16_t address)
{ return fx_data_read(p,0,address); }
static void put(fx_platform *p,uint16_t address,uint8_t value)
{ fx_data_write(p,0,address,value); }
static fx_menu_status complete(fx_statistics_menu_controller *s,uint8_t byte)
{
    s->returned=byte;s->phase=STAT_COMPLETE;
    return FX_MENU_DONE;
}
static fx_menu_status menu_status(fx_platform *,fx_statistics_menu_controller *,fx_menu_status);
static fx_menu_status open_menu(fx_platform *p,fx_statistics_menu_controller *s,uint8_t page)
{
    s->page=page;s->phase=STAT_MENU;
    return menu_status(p,s,fx_menu_navigator_begin(p,&s->menu,page,0));
}
static fx_menu_status commit_kind(fx_platform *p,fx_statistics_menu_controller *s)
{
    put(p,0x80fa,s->selected_kind);
    put(p,0x812a,0);
    fx_boot_clear_exported_input(p);
    put(p,0x80fc,18);
    fx_result_reset_layout_and_flags(p);
    return complete(s,255);
}
static fx_menu_status confirmation_wait(fx_platform *p,fx_statistics_menu_controller *s)
{
    s->phase=STAT_CONFIRM;
    return fx_key_controller_begin(p,&s->confirmation)==FX_KEY_CONTROLLER_WAIT?
        FX_MENU_WAIT:FX_MENU_UNIMPLEMENTED;
}
static fx_menu_status select_kind(fx_platform *p,fx_statistics_menu_controller *s,uint8_t kind)
{
    if(s->constraint)return complete(s,kind);
    s->selected_kind=kind;
    if((get(p,0x80fa)==1)==(kind==1))return commit_kind(p,s);
    static const uint16_t lines[4]={0x1261,0x11a1,0x1287,0x1292};
    fx_menu_paint_lines(p,lines);
    return confirmation_wait(p,s);
}
static fx_menu_status menu_status(fx_platform *p,fx_statistics_menu_controller *s,fx_menu_status status)
{
    if(status==FX_MENU_RESET) {
        s->reset_source=STAT_MENU;s->phase=STAT_RESET;return status;
    }
    if(status!=FX_MENU_DONE)return status;
    uint8_t selection,action;
    if(fx_menu_navigator_finish(&s->menu,&selection,&action)!=FX_MENU_DONE)
        return FX_MENU_INVALID;
    if(action==1)return selection==255?open_menu(p,s,s->initial_page):complete(s,0);
    if(action==2) {
        put(p,0x80f5,selection);
        return complete(s,1);
    }
    if(action!=3)return complete(s,0);
    if(selection>=1 && selection<=8)return select_kind(p,s,selection);
    switch(selection) {
    case 20:
        put(p,0x80fc,18);fx_result_reset_layout_and_flags(p);
        return complete(s,255);
    case 21:
        if(get(p,0x80fc)!=18)return complete(s,0);
        fx_result_clear_flags(p);
        (void)fx_stats_editor_insert(p,(uint8_t)(get(p,0x811c)+get(p,0x811d)-1u));
        put(p,0x812a,0);
        return complete(s,255);
    case 22:
        if(get(p,0x80fc)!=18)return complete(s,0);
        fx_result_clear_flags(p);(void)fx_stats_editor_clear(p);
        return complete(s,255);
    case 23:return open_menu(p,s,get(p,0x80fa)==3?42:41);
    default:return open_menu(p,s,s->page);
    }
}
static fx_menu_status confirmation_tick(fx_platform *p,fx_statistics_menu_controller *s)
{
    fx_key_controller_status status=fx_key_controller_tick(p,&s->confirmation);
    if(status==FX_KEY_CONTROLLER_WAIT)return FX_MENU_WAIT;
    if(status==FX_KEY_CONTROLLER_EXPORT)return FX_MENU_EXPORT;
    if(status==FX_KEY_CONTROLLER_RESET) {
        (void)fx_key_controller_finish(&s->confirmation,NULL);
        s->reset_source=STAT_CONFIRM;s->phase=STAT_RESET;return FX_MENU_RESET;
    }
    if(status!=FX_KEY_CONTROLLER_TOKEN)return FX_MENU_UNIMPLEMENTED;
    uint8_t token;
    if(fx_key_controller_finish(&s->confirmation,&token)!=FX_KEY_CONTROLLER_TOKEN)
        return FX_MENU_INVALID;
    if(token==0xed || token==0xf0) {
        /* CE54 clears STAT data before clearing result flags; the later
         * CEB0 commit has its own second layout/flags reset. */
        (void)fx_stats_editor_clear(p);fx_result_clear_flags(p);
        return commit_kind(p,s);
    }
    if(token==0xe6)return complete(s,255);
    return confirmation_wait(p,s);
}
fx_menu_status fx_statistics_menu_controller_begin(fx_platform *p,
    fx_statistics_menu_controller *s,uint8_t page,uint8_t constraint)
{
    if(!p || !p->ram || !s)return FX_MENU_INVALID;
    memset(s,0,sizeof *s);s->active=1;s->initial_page=page;s->constraint=constraint;
    return open_menu(p,s,page);
}
fx_menu_status fx_statistics_menu_controller_tick(fx_platform *p,fx_statistics_menu_controller *s)
{
    if(!p || !p->ram || !s || !s->active)return FX_MENU_INVALID;
    if(s->phase==STAT_COMPLETE)return FX_MENU_DONE;
    if(s->phase==STAT_RESET)return FX_MENU_RESET;
    if(s->phase==STAT_CONFIRM)return confirmation_tick(p,s);
    if(s->phase==STAT_MENU)return menu_status(p,s,fx_menu_navigator_tick(p,&s->menu));
    return FX_MENU_INVALID;
}
fx_menu_status fx_statistics_menu_controller_resume_timer(fx_platform *p,fx_statistics_menu_controller *s)
{
    if(!p || !p->ram || !s || !s->active || s->phase!=STAT_MENU)return FX_MENU_INVALID;
    return menu_status(p,s,fx_menu_navigator_resume_timer(p,&s->menu));
}
fx_menu_status fx_statistics_menu_controller_finish(fx_statistics_menu_controller *s,uint8_t *byte)
{
    if(!s || !s->active || (s->phase!=STAT_COMPLETE && s->phase!=STAT_RESET))return FX_MENU_INVALID;
    if(byte)*byte=s->returned;
    s->active=0;
    return s->phase==STAT_RESET?FX_MENU_RESET:FX_MENU_DONE;
}
uint8_t fx_statistics_menu_controller_export_mask(const fx_statistics_menu_controller *s)
{
    if(!s || !s->active)return 0;
    uint8_t phase=s->phase==STAT_RESET?s->reset_source:s->phase;
    return phase==STAT_CONFIRM?s->confirmation.export_mask:phase==STAT_MENU?s->menu.keys.export_mask:0;
}
uint16_t fx_statistics_menu_controller_timer_period(const fx_statistics_menu_controller *s)
{ return s && s->active && s->phase==STAT_MENU?s->menu.timer_period:0; }
static fx_parameter_menu_status service_begin(fx_platform *p,void *context,const fx_parameter_menu_request *request)
{
    fx_statistics_menu_controller *s=context;
    if(!s || !request)return FX_PARAMETER_MENU_INVALID;
    if(request->kind!=FX_PARAMETER_MENU_STATISTICS) {
        memset(s,0,sizeof *s);return FX_PARAMETER_MENU_REQUEST;
    }
    return (fx_parameter_menu_status)fx_statistics_menu_controller_begin(p,s,request->page,request->argument);
}
static fx_parameter_menu_status service_tick(fx_platform *p,void *context)
{
    fx_statistics_menu_controller *s=context;
    return s && s->active?(fx_parameter_menu_status)fx_statistics_menu_controller_tick(p,s):FX_PARAMETER_MENU_REQUEST;
}
static fx_parameter_menu_status service_timer(fx_platform *p,void *context)
{
    fx_statistics_menu_controller *s=context;
    return s && s->active?(fx_parameter_menu_status)fx_statistics_menu_controller_resume_timer(p,s):FX_PARAMETER_MENU_REQUEST;
}
static fx_parameter_menu_status service_finish(void *context,uint8_t *byte)
{ return (fx_parameter_menu_status)fx_statistics_menu_controller_finish(context,byte); }
static uint8_t service_export(const void *context)
{ return fx_statistics_menu_controller_export_mask(context); }
static uint16_t service_period(const void *context)
{ return fx_statistics_menu_controller_timer_period(context); }
void fx_statistics_menu_controller_services(fx_parameter_menu_services *services,fx_statistics_menu_controller *s)
{
    if(services)*services=(fx_parameter_menu_services){s,service_begin,service_tick,service_timer,service_finish,service_export,service_period};
}
