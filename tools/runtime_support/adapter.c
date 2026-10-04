/* Test-only named runtime ABI; SPDX-License-Identifier: GPL-3.0-only. */
#include "platform/fx_runtime.h"
#include <stddef.h>
size_t runtime_size(void) { return sizeof(fx_runtime); }
size_t runtime_transport_abi(unsigned n)
{
    const size_t fields[]={sizeof(fx_platform),offsetof(fx_platform,rom),
        offsetof(fx_platform,rom_size),offsetof(fx_platform,ram),
        offsetof(fx_platform,callback_pending),offsetof(fx_platform,status),
        sizeof(fx_key_state),offsetof(fx_key_state,columns),offsetof(fx_key_state,rows)};
    return n<sizeof fields/sizeof fields[0] ? fields[n] : 0;
}
unsigned runtime_field(const fx_runtime *s,unsigned n)
{
    const unsigned fields[]={s->phase,s->event,s->main.pending_request,
        s->main.wait_required,s->main.last_menu_result,s->timer_pending,
        s->timer_period,s->export_mask,s->returned,s->request.kind,
        s->request.operation,s->request.argument,s->input.context.return_value,
        s->input.handler_action,s->mode.menu.page,s->bank.page,s->mode.request,
        s->steps,s->input.input.unsupported_token,s->mode.result,s->bank.result,
        s->request.expression_address,s->request.result_address,
        s->request.prepared_source,s->request.current_source};
    return n<sizeof fields/sizeof fields[0] ? fields[n] : 0;
}
