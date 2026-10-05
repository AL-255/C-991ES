/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_constant_menu_controller.h"
#include "render/fx_render.h"
#include <string.h>

enum { SELECTOR_KEYS=1,SELECTOR_TIMER,SELECTOR_COMPLETE,SELECTOR_RESET };
static uint8_t get(fx_platform *p,uint16_t address)
{ return fx_data_read(p,0,address); }
static void put(fx_platform *p,uint16_t address,uint8_t byte)
{ fx_data_write(p,0,address,byte); }

/*15870/1588C: numeric index and inserted expression token are distinct. */
static uint8_t mapped_token(fx_platform *p,uint8_t kind,uint8_t index)
{
    if(!index || index>40)return 0;
    if(kind==FX_CONVERSION_MENU)return (uint8_t)(214u+index);
    return index<16?index:get(p,(uint16_t)(0x2440u+index-16u));
}
static fx_menu_status complete(fx_platform *p,fx_constant_menu_controller *s)
{
    put(p,0x8121,1);
    if(s->kind==FX_CONSTANT_SELECTOR)s->returned=s->value;
    else {
        put(p,0x80f5,mapped_token(p,s->kind,s->value));
        s->returned=s->value!=0;
    }
    s->phase=SELECTOR_COMPLETE;
    return FX_MENU_DONE;
}
static fx_menu_status draw_and_wait(fx_platform *p,fx_constant_menu_controller *s)
{
    put(p,0x811f,10);put(p,0x8121,0);
    fx_render r={p->rom,p->rom_size,p->ram};
    for(unsigned i=0;s->prompt[i];++i)
        fx_draw_glyph(&r,(uint8_t)(72u+6u*i),21,s->prompt[i]);
    if(s->cursor==3) {
        fx_timer_start(p,0x129a);s->phase=SELECTOR_TIMER;
        return FX_MENU_TIMER;
    }
    s->phase=SELECTOR_KEYS;
    return fx_key_controller_begin(p,&s->keys)==FX_KEY_CONTROLLER_WAIT?
        FX_MENU_WAIT:FX_MENU_UNIMPLEMENTED;
}
fx_menu_status fx_constant_menu_controller_begin(fx_platform *p,
    fx_constant_menu_controller *s,fx_constant_menu_kind kind,uint8_t trigger)
{
    if(!p || !p->ram || !s || kind>FX_CONVERSION_MENU || kind<0)
        return FX_MENU_INVALID;
    memset(s,0,sizeof *s);s->active=1;s->kind=(uint8_t)kind;
    if((kind==FX_CONSTANT_MENU && get(p,0x80f9)==0x88 && get(p,0x80fc)==18) ||
       (kind==FX_CONVERSION_MENU && get(p,0x80f9)==0x88)) {
        s->phase=SELECTOR_COMPLETE;return FX_MENU_DONE;
    }
    if(kind!=FX_CONSTANT_SELECTOR) {
        uint16_t text=kind==FX_CONSTANT_MENU?0x11fe:0x1218,lines[4];
        for(unsigned i=0;i<4;++i) {
            lines[i]=text;
            while(get(p,text))++text;
            ++text;
        }
        fx_menu_paint_lines(p,lines);
        trigger=kind==FX_CONSTANT_MENU?6:7;
    }
    for(unsigned i=0;i<5;++i)s->prompt[i]=get(p,(uint16_t)(0x11f9u+i));
    s->cursor=1;s->lower=48;s->upper=52;s->weight=10;s->trigger=trigger;
    return draw_and_wait(p,s);
}
fx_menu_status fx_constant_menu_controller_tick(fx_platform *p,
    fx_constant_menu_controller *s)
{
    if(!p || !p->ram || !s || !s->active)return FX_MENU_INVALID;
    if(s->phase==SELECTOR_COMPLETE)return FX_MENU_DONE;
    if(s->phase==SELECTOR_TIMER)return FX_MENU_TIMER;
    if(s->phase==SELECTOR_RESET)return FX_MENU_RESET;
    if(s->phase!=SELECTOR_KEYS)return FX_MENU_INVALID;
    fx_key_controller_status status=fx_key_controller_tick(p,&s->keys);
    if(status==FX_KEY_CONTROLLER_RESET) {
        s->phase=SELECTOR_RESET;return FX_MENU_RESET;
    }
    if(status!=FX_KEY_CONTROLLER_TOKEN)return (fx_menu_status)status;
    uint8_t token;
    if(fx_key_controller_finish(&s->keys,&token)!=FX_KEY_CONTROLLER_TOKEN)
        return FX_MENU_INVALID;
    if(token>=s->lower && token<=s->upper) {
        s->prompt[s->cursor++]=token;
        s->value=(uint8_t)(s->value+(token&15u)*s->weight);
        s->weight=1;s->upper=57;
        if(token==52)s->upper=48;
        else if(token==48)s->lower=49;
    } else if(token==230 || token==s->trigger) {
        s->value=0;return complete(p,s);
    }
    return draw_and_wait(p,s);
}
fx_menu_status fx_constant_menu_controller_resume_timer(fx_platform *p,
    fx_constant_menu_controller *s)
{
    if(!p || !p->ram || !s || !s->active || s->phase!=SELECTOR_TIMER)
        return FX_MENU_INVALID;
    return complete(p,s);
}
fx_menu_status fx_constant_menu_controller_finish(fx_constant_menu_controller *s,
    uint8_t *returned)
{
    if(!s || !s->active || (s->phase!=SELECTOR_COMPLETE && s->phase!=SELECTOR_RESET))
        return FX_MENU_INVALID;
    if(returned)*returned=s->returned;
    s->active=0;
    return s->phase==SELECTOR_RESET?FX_MENU_RESET:FX_MENU_DONE;
}
uint8_t fx_constant_menu_controller_export_mask(const fx_constant_menu_controller *s)
{ return s && s->active?s->keys.export_mask:0; }
uint16_t fx_constant_menu_controller_timer_period(const fx_constant_menu_controller *s)
{ return s && s->active && s->phase==SELECTOR_TIMER?0x129a:0; }

static fx_parameter_menu_status service_begin(fx_platform *p,void *context,
    const fx_parameter_menu_request *request)
{
    fx_constant_menu_controller *s=context;
    if(!s || !request)return FX_PARAMETER_MENU_INVALID;
    if(request->kind!=FX_PARAMETER_MENU_RECALL && request->kind!=FX_PARAMETER_MENU_STORE) {
        memset(s,0,sizeof *s);return FX_PARAMETER_MENU_REQUEST;
    }
    return (fx_parameter_menu_status)fx_constant_menu_controller_begin(p,s,
        request->kind==FX_PARAMETER_MENU_RECALL?FX_CONSTANT_MENU:FX_CONVERSION_MENU,0);
}
static fx_parameter_menu_status service_tick(fx_platform *p,void *context)
{
    fx_constant_menu_controller *s=context;
    return s && s->active?(fx_parameter_menu_status)
        fx_constant_menu_controller_tick(p,s):FX_PARAMETER_MENU_REQUEST;
}
static fx_parameter_menu_status service_timer(fx_platform *p,void *context)
{
    fx_constant_menu_controller *s=context;
    return s && s->active?(fx_parameter_menu_status)
        fx_constant_menu_controller_resume_timer(p,s):FX_PARAMETER_MENU_REQUEST;
}
static fx_parameter_menu_status service_finish(void *context,uint8_t *returned)
{ return (fx_parameter_menu_status)fx_constant_menu_controller_finish(context,returned); }
static uint8_t service_export(const void *context)
{ return fx_constant_menu_controller_export_mask(context); }
static uint16_t service_period(const void *context)
{ return fx_constant_menu_controller_timer_period(context); }
void fx_constant_menu_controller_services(fx_parameter_menu_services *services,
    fx_constant_menu_controller *s)
{
    if(services)*services=(fx_parameter_menu_services){s,service_begin,service_tick,
        service_timer,service_finish,service_export,service_period};
}
