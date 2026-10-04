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
#include "ui/fx_equation_controller.h"
#include <string.h>
size_t runtime_equation_size(void) { return sizeof(fx_equation_controller); }
unsigned runtime_equation_field(const fx_equation_controller *s,unsigned n)
{
 const unsigned fields[]={s->returned,s->phase,s->input.context.return_value,
  s->input.handler_action,s->input.request};
 return n<5?fields[n]:0;
}
unsigned equation_timer_calls;
uint16_t equation_timer_periods[1024];
unsigned equation_c_polls;
uint8_t equation_c_poll_ram[256][65536];
void equation_timer_reset(void) { equation_timer_calls=equation_c_polls=0; }
void __real_fx_timer_start(fx_platform *,uint16_t);
void __wrap_fx_timer_start(fx_platform *p,uint16_t frequency)
{
 if(equation_timer_calls<1024)equation_timer_periods[equation_timer_calls]=frequency;
 ++equation_timer_calls;__real_fx_timer_start(p,frequency);
 if(frequency==0x129a) {
  if(equation_c_polls<256)memcpy(equation_c_poll_ram[equation_c_polls],p->ram,65536);
  ++equation_c_polls;
 }
}

unsigned equation_cancel_at,equation_cancel_count;
void equation_control_reset(unsigned cancel_at)
{ equation_cancel_at=cancel_at;equation_cancel_count=0; }
static int equation_control_cancelled(void *userdata)
{ (void)userdata;return ++equation_cancel_count==equation_cancel_at; }
int equation_begin_controlled(fx_platform *p,fx_equation_controller *s)
{
 fx_calculus_control control={equation_control_cancelled,NULL};
 return fx_equation_controller_begin(p,s,&control);
}

#include "ui/fx_equation_result.h"
size_t runtime_equation_result_size(void) { return sizeof(fx_solver_result); }
