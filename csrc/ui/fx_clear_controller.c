/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_clear_controller.h"
#include "platform/fx_boot.h"
#include "platform/fx_persistent.h"
#include "render/fx_render_memory.h"
#include <string.h>

enum { CLEAR_MENU=1, CLEAR_CONFIRM, CLEAR_SUCCESS, CLEAR_COMPLETE,
       CLEAR_RESET, CLEAR_GAP };
static uint8_t get(fx_platform *p,uint16_t a) { return fx_data_read(p,0,a); }
static void put(fx_platform *p,uint16_t a,uint8_t v) { fx_data_write(p,0,a,v); }
static void fill(fx_platform *p,uint16_t a,unsigned n)
{ for(unsigned i=0;i<n;++i)put(p,(uint16_t)(a+i),0); }
static fx_menu_status complete(fx_clear_controller *s,uint8_t value)
{ s->returned=value;s->phase=CLEAR_COMPLETE;return FX_MENU_DONE; }
static fx_menu_status wait_confirmation(fx_platform *p,fx_clear_controller *s)
{
    return fx_key_controller_begin(p,&s->confirmation)==FX_KEY_CONTROLLER_WAIT?
        FX_MENU_WAIT:FX_MENU_UNIMPLEMENTED;
}
static fx_menu_status success_screen(fx_platform *p,fx_clear_controller *s)
{
    uint16_t lines[4]={0x11a1,s->selection==3?0x127a:0x12a0,0x11a1,0x12ad};
    fx_menu_paint_lines(p,lines);s->phase=CLEAR_SUCCESS;
    return wait_confirmation(p,s);
}
static void clear_memory(fx_platform *p,fx_clear_controller *s)
{
    /* 1D74A clears real variables, then tests the live mode for imaginary
     * storage. CF40 inspects only the result's F header, not its payload. */
    fill(p,0x8226,110);
    if(get(p,0x80f9)==0xc4)fill(p,0x8408,100);
    uint8_t result=get(p,0x8140);
    if(result<0xf0 || (result&15)!=13)fx_result_clear(p);
    uint8_t mode=get(p,0x80f9);
    if(mode==0x45 || mode==0x4b) {
        put(p,0x80fc,mode==0x45?21:24);
        fx_result_reset_layout_and_flags(p);put(p,0x80fd,0);s->send_ac=0;
    } else if(mode==0x88) {
        put(p,0x80fc,6);put(p,0x80fd,1);put(p,0x8138,0);
    } else if(mode==12) {
        fx_boot_initialize_mode12(p);
        fx_render render={p->rom,p->rom_size,p->ram};fx_clear_framebuffer(&render);
    } else if(get(p,0x80fc)&16) {
        fx_result_clear_flags(p);s->send_ac=0;
    }
}
static fx_menu_status apply_clear(fx_platform *p,fx_clear_controller *s)
{
    fx_boot_status status=FX_BOOT_READY;
    if(s->selection==1)status=fx_boot_reset_settings(p);
    else if(s->selection==2)clear_memory(p,s);
    else if(s->selection==3) {
        uint8_t first=get(p,0x80f2),second=get(p,0x80f3);
        status=fx_boot_cold_reset(p);
        put(p,0x80f2,first);put(p,0x80f3,second);
    }
    if(status!=FX_BOOT_READY) {s->phase=CLEAR_GAP;return FX_MENU_UNIMPLEMENTED;}
    return success_screen(p,s);
}
static fx_menu_status menu_status(fx_platform *p,fx_clear_controller *s,fx_menu_status status)
{
    if(status==FX_MENU_RESET) {s->reset_source=CLEAR_MENU;s->phase=CLEAR_RESET;return status;}
    if(status!=FX_MENU_DONE)return status;
    uint8_t action;
    if(fx_menu_navigator_finish(&s->menu,&s->selection,&action)!=FX_MENU_DONE)
        return FX_MENU_INVALID;
    if(action!=3)return complete(s,0);
    uint16_t title=s->selection==1?0x1254:s->selection==2?0x1261:0x126f;
    uint16_t lines[4]={title,0x11a1,0x1287,0x1292};
    fx_menu_paint_lines(p,lines);s->phase=CLEAR_CONFIRM;
    return wait_confirmation(p,s);
}
static fx_menu_status confirmation_tick(fx_platform *p,fx_clear_controller *s)
{
    fx_key_controller_status status=fx_key_controller_tick(p,&s->confirmation);
    if(status==FX_KEY_CONTROLLER_WAIT)return FX_MENU_WAIT;
    if(status==FX_KEY_CONTROLLER_EXPORT)return FX_MENU_EXPORT;
    if(status==FX_KEY_CONTROLLER_RESET) {
        (void)fx_key_controller_finish(&s->confirmation,NULL);
        s->reset_source=s->phase;s->phase=CLEAR_RESET;return FX_MENU_RESET;
    }
    if(status!=FX_KEY_CONTROLLER_TOKEN)return FX_MENU_UNIMPLEMENTED;
    uint8_t token;
    if(fx_key_controller_finish(&s->confirmation,&token)!=FX_KEY_CONTROLLER_TOKEN)
        return FX_MENU_INVALID;
    if(token!=0xed && token!=0xf0 && token!=0xe6)return wait_confirmation(p,s);
    if(s->phase==CLEAR_CONFIRM)return token==0xe6?complete(s,0):apply_clear(p,s);
    /* The second 1DD62 return is ignored: both EXE and AC dismiss success. */
    if(s->send_ac) {put(p,0x80f5,0xe6);put(p,0x80f7,1);}
    return complete(s,255);
}
fx_menu_status fx_clear_controller_begin(fx_platform *p,fx_clear_controller *s)
{
    if(!p || !p->ram || !s)return FX_MENU_INVALID;
    memset(s,0,sizeof *s);s->active=1;s->send_ac=1;s->returned=255;
    put(p,0x812a,0);s->phase=CLEAR_MENU;
    return menu_status(p,s,fx_menu_navigator_begin(p,&s->menu,1,0));
}
fx_menu_status fx_clear_controller_tick(fx_platform *p,fx_clear_controller *s)
{
    if(!p || !p->ram || !s || !s->active)return FX_MENU_INVALID;
    if(s->phase==CLEAR_COMPLETE)return FX_MENU_DONE;
    if(s->phase==CLEAR_RESET)return FX_MENU_RESET;
    if(s->phase==CLEAR_GAP)return FX_MENU_UNIMPLEMENTED;
    if(s->phase==CLEAR_MENU)return menu_status(p,s,fx_menu_navigator_tick(p,&s->menu));
    if(s->phase==CLEAR_CONFIRM || s->phase==CLEAR_SUCCESS)return confirmation_tick(p,s);
    return FX_MENU_INVALID;
}
fx_menu_status fx_clear_controller_resume_timer(fx_platform *p,fx_clear_controller *s)
{
    if(!p || !p->ram || !s || !s->active || s->phase!=CLEAR_MENU)return FX_MENU_INVALID;
    return menu_status(p,s,fx_menu_navigator_resume_timer(p,&s->menu));
}
fx_menu_status fx_clear_controller_finish(fx_clear_controller *s,uint8_t *value)
{
    if(!s || !s->active || (s->phase!=CLEAR_COMPLETE && s->phase!=CLEAR_RESET))return FX_MENU_INVALID;
    if(value)*value=s->returned;
    s->active=0;
    return s->phase==CLEAR_RESET?FX_MENU_RESET:FX_MENU_DONE;
}
uint8_t fx_clear_controller_export_mask(const fx_clear_controller *s)
{
    if(!s || !s->active)return 0;
    uint8_t phase=s->phase==CLEAR_RESET?s->reset_source:s->phase;
    return phase==CLEAR_MENU?s->menu.keys.export_mask:
        phase==CLEAR_CONFIRM || phase==CLEAR_SUCCESS?s->confirmation.export_mask:0;
}
uint16_t fx_clear_controller_timer_period(const fx_clear_controller *s)
{ return s && s->active && s->phase==CLEAR_MENU?s->menu.timer_period:0; }
static fx_parameter_menu_status service_begin(fx_platform *p,void *context,const fx_parameter_menu_request *request)
{
    fx_clear_controller *s=context;
    if(!s || !request)return FX_PARAMETER_MENU_INVALID;
    if(request->kind!=FX_PARAMETER_MENU_CLEAR) {
        memset(s,0,sizeof *s);return FX_PARAMETER_MENU_REQUEST;
    }
    return (fx_parameter_menu_status)fx_clear_controller_begin(p,s);
}
static fx_parameter_menu_status service_tick(fx_platform *p,void *s)
{
    fx_clear_controller *state=s;
    return state && state->active?(fx_parameter_menu_status)fx_clear_controller_tick(p,state):FX_PARAMETER_MENU_REQUEST;
}
static fx_parameter_menu_status service_timer(fx_platform *p,void *s)
{
    fx_clear_controller *state=s;
    return state && state->active?(fx_parameter_menu_status)fx_clear_controller_resume_timer(p,state):FX_PARAMETER_MENU_REQUEST;
}
static fx_parameter_menu_status service_finish(void *s,uint8_t *v)
{ return (fx_parameter_menu_status)fx_clear_controller_finish(s,v); }
static uint8_t service_export(const void *s)
{ return fx_clear_controller_export_mask(s); }
static uint16_t service_period(const void *s)
{ return fx_clear_controller_timer_period(s); }
void fx_clear_controller_services(fx_parameter_menu_services *services,fx_clear_controller *s)
{
    if(services)*services=(fx_parameter_menu_services){s,service_begin,service_tick,
        service_timer,service_finish,service_export,service_period};
}
