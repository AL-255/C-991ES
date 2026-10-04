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
        s->distribution.active,s->distribution.phase};
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
size_t parameter_runtime_abi(unsigned n)
{
    const size_t a[]={sizeof(fx_platform),offsetof(fx_platform,rom),
        offsetof(fx_platform,rom_size),offsetof(fx_platform,ram),
        offsetof(fx_platform,callback_pending),offsetof(fx_platform,status),
        sizeof(fx_key_state),offsetof(fx_key_state,columns),offsetof(fx_key_state,rows)};
    return n<sizeof a/sizeof a[0]?a[n]:0;
}
