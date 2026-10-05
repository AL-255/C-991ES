/* SPDX-License-Identifier: GPL-3.0-only */
/* Test-only opaque transport. Authored inputs only; no expected states feed C. */
#include "ui/fx_clear_controller.h"
#include "platform/fx_runtime.h"
#include <stddef.h>
#include <string.h>
typedef struct {
    fx_runtime runtime;
    fx_clear_controller child;
    uint8_t parent, finished;
} clear_test_state;
static fx_clear_controller *child(clear_test_state *s)
{ return s->parent ? &s->runtime.clear : &s->child; }
static int translated(fx_runtime_status status)
{
    switch(status) {
    case FX_RUNTIME_WAIT:return FX_MENU_WAIT;
    case FX_RUNTIME_ADVANCED:return FX_MENU_DONE;
    case FX_RUNTIME_EXPORT:return FX_MENU_EXPORT;
    case FX_RUNTIME_TIMER:return FX_MENU_TIMER;
    case FX_RUNTIME_REQUEST:return FX_PARAMETER_MENU_REQUEST;
    case FX_RUNTIME_RESET:return FX_MENU_RESET;
    default:return FX_MENU_INVALID;
    }
}
size_t clear_test_size(void) { return sizeof(clear_test_state); }
size_t clear_test_child_size(void) { return sizeof(fx_clear_controller); }
void *clear_test_child(clear_test_state *s) { return child(s); }
void clear_test_main_begin(clear_test_state *s)
{
    memset(s,0,sizeof *s);fx_main_loop_begin(&s->runtime.main);
    s->runtime.main.wait_required=1;s->runtime.active=1;s->runtime.phase=FX_RUNTIME_MAIN;
}
int clear_test_main_tick(fx_platform *p,clear_test_state *s)
{
    fx_runtime_status status=fx_runtime_step(p,&s->runtime,NULL,0);
    if(status==FX_RUNTIME_ADVANCED && s->runtime.phase==FX_RUNTIME_START_PARAMETER)
        return FX_MAIN_REQUEST;
    return (int)status;
}
int clear_test_begin(fx_platform *p,clear_test_state *s,int parent)
{
    s->parent=(uint8_t)parent;s->finished=0;
    if(!parent)return fx_clear_controller_begin(p,&s->child);
    if(s->runtime.phase!=FX_RUNTIME_START_PARAMETER)return FX_MENU_INVALID;
    return translated(fx_runtime_step(p,&s->runtime,NULL,0));
}
int clear_test_tick(fx_platform *p,clear_test_state *s)
{
    return s->parent ? translated(fx_runtime_step(p,&s->runtime,NULL,0)) :
        fx_clear_controller_tick(p,&s->child);
}
int clear_test_timer(fx_platform *p,clear_test_state *s)
{
    return s->parent ? translated(fx_runtime_step(p,&s->runtime,NULL,1)) :
        fx_clear_controller_resume_timer(p,&s->child);
}
int clear_test_finish(clear_test_state *s,uint8_t *value)
{
    if(!s || !value || s->finished)return FX_MENU_INVALID;
    if(!s->parent) {
        int status=fx_clear_controller_finish(&s->child,value);
        if(status>=0)s->finished=1;
        return status;
    }
    /* Observe the genuine child return; runtime owns parent finish on next step. */
    if(s->runtime.phase!=FX_RUNTIME_RETURN_PARAMETER)return FX_MENU_INVALID;
    *value=s->runtime.parameter.returned;s->finished=1;return FX_MENU_DONE;
}
int clear_test_main_return(fx_platform *p,clear_test_state *s,uint8_t value)
{
    if(!s->parent || !s->finished || value!=s->runtime.parameter.returned)
        return FX_RUNTIME_INVALID;
    return fx_runtime_step(p,&s->runtime,NULL,0);
}
int clear_test_service(fx_platform *p,clear_test_state *s,unsigned operation,unsigned kind)
{
    fx_parameter_menu_services services;
    fx_clear_controller_services(&services,child(s));
    fx_parameter_menu_request request={(fx_parameter_menu_child)kind,1,0};
    if(operation==0)return services.begin(p,services.context,&request);
    if(operation==1)return services.tick(p,services.context);
    if(operation==2)return services.resume_timer(p,services.context);
    if(operation==3)return services.finish(services.context,NULL);
    if(operation==4)return services.begin(p,services.context,NULL);
    return -99;
}
unsigned clear_test_field(const clear_test_state *s,unsigned n)
{
    const fx_clear_controller *c=s->parent?&s->runtime.clear:&s->child;
    const unsigned a[]={c->selection,c->send_ac,c->returned,c->phase,c->active,c->menu.page,
        fx_clear_controller_export_mask(c),fx_clear_controller_timer_period(c),
        s->runtime.main.wait_required,s->runtime.main.last_menu_result,s->runtime.main.pending_request,
        s->runtime.phase,s->runtime.event,s->runtime.steps,s->runtime.parameter.returned,
        s->runtime.parameter_provider.active_kind};
    return n<sizeof a/sizeof a[0]?a[n]:0xffffffffu;
}
int clear_test_custody(const clear_test_state *s)
{
    const fx_runtime *r=&s->runtime;
    if(!s->parent)return 1;
    return r->parameter_provider.clear==&r->clear &&
        r->parameter_provider.selected.context==&r->clear &&
        r->parameter_provider.active_kind==FX_PARAMETER_MENU_CLEAR &&
        (const char *)&r->clear>=(const char *)&r->polynomial+sizeof r->polynomial &&
        (const char *)&r->clear>=(const char *)&r->parameter+sizeof r->parameter;
}
int clear_test_legacy_provider(fx_platform *p)
{
    fx_parameter_menu_provider provider;
    fx_parameter_menu_services services;
    fx_parameter_menu_request request={FX_PARAMETER_MENU_CLEAR,1,0};
    fx_parameter_menu_provider_services(&services,&provider,NULL,NULL,NULL);
    int status=services.begin(p,services.context,&request);
    return status==FX_PARAMETER_MENU_REQUEST && provider.clear==NULL &&
        provider.active_kind==FX_PARAMETER_MENU_CHILD_NONE;
}
size_t clear_test_abi(unsigned n)
{
    const size_t a[]={sizeof(fx_platform),offsetof(fx_platform,rom),offsetof(fx_platform,rom_size),
        offsetof(fx_platform,ram),offsetof(fx_platform,callback_pending),offsetof(fx_platform,status),
        FX_MENU_WAIT,FX_MENU_DONE,FX_MENU_RESET,FX_MENU_EXPORT,FX_MENU_TIMER,FX_MENU_INVALID,
        FX_MENU_UNIMPLEMENTED,FX_MAIN_REQUEST,FX_MAIN_PARAMETER_MENU,
        sizeof(fx_clear_controller),offsetof(fx_clear_controller,menu),offsetof(fx_clear_controller,confirmation),
        offsetof(fx_clear_controller,selection),offsetof(fx_clear_controller,send_ac),offsetof(fx_clear_controller,returned),
        offsetof(fx_clear_controller,phase),offsetof(fx_clear_controller,reset_source),offsetof(fx_clear_controller,active),
        offsetof(fx_runtime,polynomial),offsetof(fx_runtime,clear),sizeof(fx_polynomial_equation_controller),
        offsetof(fx_parameter_menu_provider,active_kind),offsetof(fx_parameter_menu_provider,clear)};
    return n<sizeof a/sizeof a[0]?a[n]:0;
}
