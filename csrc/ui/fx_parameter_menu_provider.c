/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_parameter_menu_provider.h"
#include <string.h>

static fx_parameter_menu_status begin(fx_platform *p,void *context,
    const fx_parameter_menu_request *request)
{
    fx_parameter_menu_provider *s=context;
    if(!s || !request)return FX_PARAMETER_MENU_INVALID;
    memset(&s->selected,0,sizeof s->selected);
    s->active_kind=FX_PARAMETER_MENU_CHILD_NONE;
    switch(request->kind) {
    case FX_PARAMETER_MENU_STATISTICS:
        if(!s->statistics)return FX_PARAMETER_MENU_INVALID;
        fx_statistics_menu_controller_services(&s->selected,s->statistics);break;
    case FX_PARAMETER_MENU_DISTRIBUTION:
        if(!s->distribution)return FX_PARAMETER_MENU_INVALID;
        fx_distribution_menu_controller_services(&s->selected,s->distribution);break;
    case FX_PARAMETER_MENU_RECALL:
    case FX_PARAMETER_MENU_STORE:
        if(!s->constant)return FX_PARAMETER_MENU_INVALID;
        fx_constant_menu_controller_services(&s->selected,s->constant);break;
    case FX_PARAMETER_MENU_CLEAR:
        if(!s->clear)return FX_PARAMETER_MENU_REQUEST;
        fx_clear_controller_services(&s->selected,s->clear);break;
    default:return FX_PARAMETER_MENU_REQUEST;
    }
    s->active_kind=request->kind;
    return s->selected.begin(p,s->selected.context,request);
}
static fx_parameter_menu_status tick(fx_platform *p,void *context)
{
    fx_parameter_menu_provider *s=context;
    if(!s)return FX_PARAMETER_MENU_INVALID;
    return s->selected.tick?s->selected.tick(p,s->selected.context):FX_PARAMETER_MENU_REQUEST;
}
static fx_parameter_menu_status timer(fx_platform *p,void *context)
{
    fx_parameter_menu_provider *s=context;
    if(!s)return FX_PARAMETER_MENU_INVALID;
    return s->selected.resume_timer?s->selected.resume_timer(p,s->selected.context):FX_PARAMETER_MENU_REQUEST;
}
static fx_parameter_menu_status finish(void *context,uint8_t *returned)
{
    fx_parameter_menu_provider *s=context;
    if(!s || !s->selected.finish)return FX_PARAMETER_MENU_INVALID;
    return s->selected.finish(s->selected.context,returned);
}
static uint8_t export_mask(const void *context)
{
    const fx_parameter_menu_provider *s=context;
    return s && s->selected.export_mask?s->selected.export_mask(s->selected.context):0;
}
static uint16_t timer_period(const void *context)
{
    const fx_parameter_menu_provider *s=context;
    return s && s->selected.timer_period?s->selected.timer_period(s->selected.context):0;
}
void fx_parameter_menu_provider_services_with_clear(fx_parameter_menu_services *services,
    fx_parameter_menu_provider *s,fx_statistics_menu_controller *statistics,
    fx_distribution_menu_controller *distribution,fx_constant_menu_controller *constant,
    fx_clear_controller *clear)
{
    if(!services || !s)return;
    memset(s,0,sizeof *s);
    s->statistics=statistics;s->distribution=distribution;s->constant=constant;s->clear=clear;
    *services=(fx_parameter_menu_services){s,begin,tick,timer,finish,export_mask,timer_period};
}
void fx_parameter_menu_provider_services(fx_parameter_menu_services *services,
    fx_parameter_menu_provider *s,fx_statistics_menu_controller *statistics,
    fx_distribution_menu_controller *distribution,fx_constant_menu_controller *constant)
{
    fx_parameter_menu_provider_services_with_clear(services,s,statistics,distribution,constant,NULL);
}
