/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_distribution_menu_controller.h"
#include "../platform/fx_boot.h"
#include "../platform/fx_persistent.h"
#include "../stats/fx_stats_editor.h"
#include <string.h>

enum { DISTRIBUTION_MENU=1, DISTRIBUTION_COMPLETE, DISTRIBUTION_RESET };
static uint8_t get(fx_platform *p,uint16_t address)
{ return fx_data_read(p,0,address); }
static void put(fx_platform *p,uint16_t address,uint8_t value)
{ fx_data_write(p,0,address,value); }
static fx_menu_status complete(fx_distribution_menu_controller *s,uint8_t byte)
{
    s->returned=byte; s->phase=DISTRIBUTION_COMPLETE;
    return FX_MENU_DONE;
}

/*1DFB0: do not substitute the STAT-only clear, which also clears812A. */
static void clear_distribution_data(fx_platform *p)
{
    if(get(p,0x80f9)!=12)return;
    put(p,0x80de,0); put(p,0x80df,0);
    fx_result_reset_layout(p);
    for(unsigned i=0;i<800;++i)put(p,(uint16_t)(0x82eeu+i),0);
}

static fx_menu_status menu_status(fx_platform *,
    fx_distribution_menu_controller *,fx_menu_status);
static fx_menu_status open_menu(fx_platform *p,
    fx_distribution_menu_controller *s,uint8_t page)
{
    s->phase=DISTRIBUTION_MENU;
    return menu_status(p,s,fx_menu_navigator_begin(p,&s->menu,page,0));
}

static fx_menu_status menu_status(fx_platform *p,
    fx_distribution_menu_controller *s,fx_menu_status status)
{
    if(status==FX_MENU_RESET) {
        s->phase=DISTRIBUTION_RESET;
        return status;
    }
    if(status!=FX_MENU_DONE)return status;
    uint8_t selection,action;
    if(fx_menu_navigator_finish(&s->menu,&selection,&action)!=FX_MENU_DONE)
        return FX_MENU_INVALID;
    if(action==1) {
        if(selection==255)return open_menu(p,s,s->initial_page);
        return complete(s,0);
    }
    if(action!=3)return complete(s,0);

    if(selection==33) {
        fx_result_clear_flags(p);
        uint8_t row=(uint8_t)(get(p,0x811c)+get(p,0x811d)-1u);
        (void)fx_stats_editor_insert(p,row);
        put(p,0x811e,1);
        return complete(s,255);
    }
    if(selection==34) {
        fx_result_clear_flags(p);
        clear_distribution_data(p);
        return complete(s,255);
    }
    if(selection>=1 && selection<=3) {
        s->kind=selection;
        put(p,0x8137,0);
    } else if(selection>=4 && selection<=7) {
        s->kind=selection;
        return open_menu(p,s,62);
    } else if(selection==16)put(p,0x8137,0);
    else if(selection==17)put(p,0x8137,1);
    /* Other action3 selections also commit the retained kind/live flag. */
    put(p,0x80fa,s->kind);
    fx_boot_clear_exported_input(p);
    fx_boot_initialize_mode12(p);
    return complete(s,255);
}

fx_menu_status fx_distribution_menu_controller_begin(fx_platform *p,
    fx_distribution_menu_controller *s,uint8_t page)
{
    if(!p || !p->ram || !s)return FX_MENU_INVALID;
    memset(s,0,sizeof *s); s->active=1; s->initial_page=page; s->kind=1;
    return open_menu(p,s,page);
}
fx_menu_status fx_distribution_menu_controller_tick(fx_platform *p,
    fx_distribution_menu_controller *s)
{
    if(!p || !p->ram || !s || !s->active)return FX_MENU_INVALID;
    if(s->phase==DISTRIBUTION_COMPLETE)return FX_MENU_DONE;
    if(s->phase==DISTRIBUTION_RESET)return FX_MENU_RESET;
    if(s->phase!=DISTRIBUTION_MENU)return FX_MENU_INVALID;
    return menu_status(p,s,fx_menu_navigator_tick(p,&s->menu));
}
fx_menu_status fx_distribution_menu_controller_resume_timer(fx_platform *p,
    fx_distribution_menu_controller *s)
{
    if(!p || !p->ram || !s || !s->active || s->phase!=DISTRIBUTION_MENU)
        return FX_MENU_INVALID;
    return menu_status(p,s,fx_menu_navigator_resume_timer(p,&s->menu));
}
fx_menu_status fx_distribution_menu_controller_finish(
    fx_distribution_menu_controller *s,uint8_t *returned)
{
    if(!s || !s->active ||
        (s->phase!=DISTRIBUTION_COMPLETE && s->phase!=DISTRIBUTION_RESET))
        return FX_MENU_INVALID;
    if(returned)*returned=s->returned;
    s->active=0;
    return s->phase==DISTRIBUTION_RESET?FX_MENU_RESET:FX_MENU_DONE;
}
uint8_t fx_distribution_menu_controller_export_mask(
    const fx_distribution_menu_controller *s)
{ return s && s->active?s->menu.keys.export_mask:0; }
uint16_t fx_distribution_menu_controller_timer_period(
    const fx_distribution_menu_controller *s)
{ return s && s->active?s->menu.timer_period:0; }

static fx_parameter_menu_status service_begin(fx_platform *p,void *context,
    const fx_parameter_menu_request *request)
{
    fx_distribution_menu_controller *s=context;
    if(!s || !request)return FX_PARAMETER_MENU_INVALID;
    if(request->kind!=FX_PARAMETER_MENU_DISTRIBUTION) {
        memset(s,0,sizeof *s);
        return FX_PARAMETER_MENU_REQUEST;
    }
    return (fx_parameter_menu_status)fx_distribution_menu_controller_begin(p,s,request->page);
}
static fx_parameter_menu_status service_tick(fx_platform *p,void *context)
{
    fx_distribution_menu_controller *s=context;
    return s && s->active?(fx_parameter_menu_status)
        fx_distribution_menu_controller_tick(p,s):FX_PARAMETER_MENU_REQUEST;
}
static fx_parameter_menu_status service_timer(fx_platform *p,void *context)
{
    fx_distribution_menu_controller *s=context;
    return s && s->active?(fx_parameter_menu_status)
        fx_distribution_menu_controller_resume_timer(p,s):FX_PARAMETER_MENU_REQUEST;
}
static fx_parameter_menu_status service_finish(void *context,uint8_t *returned)
{ return (fx_parameter_menu_status)fx_distribution_menu_controller_finish(context,returned); }
static uint8_t service_export(const void *context)
{ return fx_distribution_menu_controller_export_mask(context); }
static uint16_t service_period(const void *context)
{ return fx_distribution_menu_controller_timer_period(context); }
void fx_distribution_menu_controller_services(fx_parameter_menu_services *services,
    fx_distribution_menu_controller *s)
{
    if(!services)return;
    *services=(fx_parameter_menu_services){s,service_begin,service_tick,
        service_timer,service_finish,service_export,service_period};
}
