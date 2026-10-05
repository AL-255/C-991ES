/* GPL-3.0-only. Opaque test transport, with one explicit authored MAIN entry. */
#include "platform/fx_runtime.h"
#include <stddef.h>
#include <string.h>
size_t parameter_runtime_size(void) { return sizeof(fx_runtime); }
void parameter_runtime_main_entry(fx_runtime *s)
{
    memset(s, 0, sizeof *s);
    s->active=1; s->phase=FX_RUNTIME_MAIN;
    fx_main_loop_begin(&s->main);
    s->main.wait_required=1;
}
unsigned parameter_runtime_field(const fx_runtime *s,unsigned n)
{
    const unsigned a[]={s->phase,s->event,s->main.pending_request,
        s->main.wait_required,s->main.last_menu_result,s->timer_pending,
        s->timer_period,s->export_mask,s->returned,s->request.kind,
        s->request.operation,s->request.argument,s->request.page,
        s->parameter.request.kind,s->parameter.request.argument,
        s->parameter.request.page,s->parameter.returned,
        s->distribution.initial_page,s->distribution.kind,
        s->distribution.menu.page,s->distribution.returned,
        s->distribution.active,s->distribution.phase,
        s->statistics.initial_page,s->statistics.constraint,s->statistics.page,
        s->statistics.selected_kind,s->statistics.returned,s->statistics.active,
        s->constant.kind,s->constant.cursor,s->constant.value,s->constant.returned,
        s->constant.active,s->parameter_provider.active_kind};
    return n<sizeof a/sizeof a[0]?a[n]:0xffffffffu;
}
unsigned parameter_runtime_constant(unsigned n)
{
    const unsigned a[]={FX_RUNTIME_MAIN,FX_RUNTIME_START_PARAMETER,
        FX_RUNTIME_PARAMETER,FX_RUNTIME_RETURN_PARAMETER,FX_RUNTIME_BODY,
        FX_RUNTIME_PARAMETER_GAP,FX_MAIN_PARAMETER_MENU};
    return n<sizeof a/sizeof a[0]?a[n]:0xffffffffu;
}
unsigned parameter_runtime_target(const fx_runtime *s)
{ return ((unsigned)s->parameter.target_segment<<16)|s->parameter.target_offset; }
int parameter_runtime_provider_custody(const fx_runtime *s)
{
    uintptr_t first=(uintptr_t)&s->parameter;
    uintptr_t last=first+sizeof s->parameter;
    const void *children[]={&s->statistics,&s->distribution,&s->constant,
        &s->parameter_provider,&s->clear};
    const size_t sizes[]={sizeof s->statistics,sizeof s->distribution,
        sizeof s->constant,sizeof s->parameter_provider,sizeof s->clear};
    for(unsigned i=0;i<5;++i) {
        uintptr_t start=(uintptr_t)children[i],end=start+sizes[i];
        if(start<last && end>first)return 0;
    }
    if(s->parameter.services.context!=&s->parameter_provider ||
       s->parameter_provider.statistics!=&s->statistics ||
       s->parameter_provider.distribution!=&s->distribution ||
       s->parameter_provider.constant!=&s->constant ||
       s->parameter_provider.clear!=&s->clear)return 0;
    const void *selected=s->parameter_provider.selected.context;
    switch(s->parameter_provider.active_kind) {
    case FX_PARAMETER_MENU_CHILD_NONE:return selected==0;
    case FX_PARAMETER_MENU_STATISTICS:return selected==&s->statistics;
    case FX_PARAMETER_MENU_DISTRIBUTION:return selected==&s->distribution;
    case FX_PARAMETER_MENU_RECALL:
    case FX_PARAMETER_MENU_STORE:return selected==&s->constant;
    case FX_PARAMETER_MENU_CLEAR:return selected==&s->clear;
    default:return 0;
    }
}
size_t parameter_runtime_abi(unsigned n)
{
    const size_t a[]={sizeof(fx_platform),offsetof(fx_platform,rom),
        offsetof(fx_platform,rom_size),offsetof(fx_platform,ram),
        offsetof(fx_platform,callback_pending),offsetof(fx_platform,status),
        sizeof(fx_key_state),offsetof(fx_key_state,columns),offsetof(fx_key_state,rows)};
    return n<sizeof a/sizeof a[0]?a[n]:0;
}
