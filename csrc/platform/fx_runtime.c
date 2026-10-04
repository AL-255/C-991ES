/* SPDX-License-Identifier: GPL-3.0-only. */
#include "fx_runtime.h"
#include <string.h>

static fx_runtime_status body(fx_runtime *s, fx_runtime_body_kind kind,
    unsigned operation, uint8_t argument, int status)
{
    memset(&s->request,0,sizeof s->request);
    s->request.kind=kind; s->request.operation=operation;
    s->request.argument=argument; s->request.status=status;
    const fx_ui_controller *input=NULL;
    if(kind==FX_RUNTIME_INPUT_BODY || kind==FX_RUNTIME_INPUT_GAP)input=&s->input;
    else if(kind==FX_RUNTIME_EQUATION_GAP && s->equation.input.active)input=&s->equation.input;
    else if(kind==FX_RUNTIME_TABLE_GAP && s->table.input.active)input=&s->table.input;
    if(input) {
        s->request.context_return=input->context.return_value;
        s->request.action=input->handler_action;
        s->request.expression_address=input->context.display_address;
        s->request.result_address=input->context.result_address;
        s->request.prepared_source=input->input.prepared_source;
        s->request.current_source=input->input.current_source;
    }
    s->phase=FX_RUNTIME_BODY; s->event=FX_RUNTIME_EVENT_BODY;
    return FX_RUNTIME_REQUEST;
}
static fx_runtime_status main_request(fx_platform *p,fx_runtime *s,
    fx_main_status status)
{
    unsigned operation=s->main.pending_request;
    s->event=FX_RUNTIME_EVENT_MAIN_HANDLER;
    if(operation==FX_MAIN_INPUT)s->phase=FX_RUNTIME_START_INPUT;
    else if(operation==FX_MAIN_MODE_MENU || operation==FX_MAIN_SETUP_MENU)
        s->phase=FX_RUNTIME_START_MENU;
    else if(operation==FX_MAIN_PARAMETER_MENU)
        s->phase=FX_RUNTIME_START_PARAMETER;
    else if(operation==FX_MAIN_SCREEN21 && p->ram[0x80f9]==0x45 &&
            p->ram[0x80fa]>=1 && p->ram[0x80fa]<=2)
        s->phase=FX_RUNTIME_START_EQUATION;
    else if(p->ram[0x80f9]==0x88 && (operation==FX_MAIN_SCREEN6 ||
            operation==FX_MAIN_SCREEN18_ADMISSION || operation==FX_MAIN_SCREEN18))
        s->phase=FX_RUNTIME_START_TABLE;
    else return body(s,FX_RUNTIME_MAIN_BODY,operation,s->main.argument,status);
    memset(&s->request,0,sizeof s->request);
    return FX_RUNTIME_ADVANCED;
}
static fx_runtime_status ready(fx_runtime *s)
{
    fx_main_loop_begin(&s->main); s->phase=FX_RUNTIME_MAIN;
    s->event=FX_RUNTIME_EVENT_BOOT_READY; return FX_RUNTIME_ADVANCED;
}
void fx_runtime_submit_pair(fx_platform *p, fx_key_state key)
{
    if (!p || !p->ram) return;
    fx_data_write(p,0,0x8e01,key.columns);
    fx_data_write(p,0,0x8e02,key.rows);
}
fx_runtime_status fx_runtime_reset(fx_platform *p,fx_runtime *s,
    const fx_calculus_control *control)
{
    if (!p || !p->ram || !s) return FX_RUNTIME_INVALID;
    /* Preserve a caller-supplied control even if it points into this object. */
    fx_calculus_control saved; memset(&saved,0,sizeof saved);
    if (control) saved=*control;
    memset(s,0,sizeof *s); s->active=1; s->cancellation=saved;
    fx_boot_status status=fx_boot_reset(p);
    if (status==FX_BOOT_READY) return ready(s);
    if (status==FX_BOOT_WELCOME || status==FX_BOOT_DIAGNOSTIC) {
        fx_boot_event_status event=fx_boot_events_begin(p,&s->boot,status);
        if (event==FX_BOOT_EVENT_READY) return ready(s);
        if (event==FX_BOOT_EVENT_WAIT) {
            s->phase=FX_RUNTIME_BOOT; return FX_RUNTIME_WAIT;
        }
        return body(s,FX_RUNTIME_BOOT_GAP,0,0,event);
    }
    return body(s,FX_RUNTIME_BOOT_GAP,0,0,status);
}
static fx_runtime_status reset_event(fx_platform *p,fx_runtime *s)
{
    fx_calculus_control control=s->cancellation;
    fx_runtime_status status=fx_runtime_reset(p,s,&control);
    if (status<0 || status==FX_RUNTIME_REQUEST) return status;
    s->event=FX_RUNTIME_EVENT_RESET; return FX_RUNTIME_RESET;
}
static fx_runtime_status export_event(fx_runtime *s,uint8_t mask)
{
    s->export_mask=mask; s->event=FX_RUNTIME_EVENT_EXPORT;
    return FX_RUNTIME_EXPORT;
}
static fx_runtime_status input_status(fx_platform *p,fx_runtime *s,
    fx_ui_status status)
{
    switch (status) {
    case FX_UI_COMPLETE:
        s->phase=FX_RUNTIME_RETURN_INPUT;
        s->event=FX_RUNTIME_EVENT_HANDLER_RETURN; return FX_RUNTIME_ADVANCED;
    case FX_UI_PREPARED:
        s->event=FX_RUNTIME_EVENT_INPUT_PREPARED; return FX_RUNTIME_ADVANCED;
    case FX_UI_WAIT:
        s->event=FX_RUNTIME_EVENT_WAIT_ITERATION; return FX_RUNTIME_WAIT;
    case FX_UI_EXPORT: return export_event(s,fx_ui_controller_export_mask(&s->input));
    case FX_UI_RESET: return reset_event(p,s);
    case FX_UI_HANDLER_REQUEST:
        return body(s,FX_RUNTIME_INPUT_BODY,s->input.request,0,status);
    default:
        return body(s,FX_RUNTIME_INPUT_GAP,s->input.request,
                    s->input.input.unsupported_token,status);
    }
}
static fx_runtime_status menu_status(fx_platform *p,fx_runtime *s,
    fx_mode_setup_status status,uint8_t entering)
{
    switch (status) {
    case FX_MODE_SETUP_WAIT:
        s->event=entering ? FX_RUNTIME_EVENT_WAIT_ENTER : FX_RUNTIME_EVENT_WAIT_ITERATION;
        return FX_RUNTIME_WAIT;
    case FX_MODE_SETUP_DONE:
        s->phase=FX_RUNTIME_RETURN_MENU; s->event=FX_RUNTIME_EVENT_HANDLER_RETURN;
        return FX_RUNTIME_ADVANCED;
    case FX_MODE_SETUP_EXPORT:
        return export_event(s,s->mode.phase<=5 ? s->mode.menu.keys.export_mask :
                                                   s->mode.keys.export_mask);
    case FX_MODE_SETUP_RESET: return reset_event(p,s);
    case FX_MODE_SETUP_TIMER:
        s->timer_pending=1; s->timer_period=s->mode.menu.timer_period;
        s->event=FX_RUNTIME_EVENT_TIMER; return FX_RUNTIME_TIMER;
    case FX_MODE_SETUP_REQUEST:
        s->phase=FX_RUNTIME_START_BANK; s->event=FX_RUNTIME_EVENT_BANK_ENTRY;
        return FX_RUNTIME_ADVANCED;
    default: return body(s,FX_RUNTIME_MENU_GAP,s->main.pending_request,0,status);
    }
}
static fx_runtime_status bank_status(fx_platform *p,fx_runtime *s,
    fx_menu_status status,uint8_t entering)
{
    switch (status) {
    case FX_MENU_WAIT:
        s->event=entering ? FX_RUNTIME_EVENT_WAIT_ENTER : FX_RUNTIME_EVENT_WAIT_ITERATION;
        return FX_RUNTIME_WAIT;
    case FX_MENU_DONE:
        s->phase=FX_RUNTIME_RETURN_BANK; s->event=FX_RUNTIME_EVENT_HANDLER_RETURN;
        return FX_RUNTIME_ADVANCED;
    case FX_MENU_EXPORT: return export_event(s,s->bank.menu.keys.export_mask);
    case FX_MENU_RESET: return reset_event(p,s);
    case FX_MENU_TIMER:
        s->timer_pending=1; s->timer_period=s->bank.menu.timer_period;
        s->event=FX_RUNTIME_EVENT_TIMER; return FX_RUNTIME_TIMER;
    default: return body(s,FX_RUNTIME_MENU_GAP,s->main.pending_request,0,status);
    }
}
static fx_runtime_status equation_status(fx_platform *p,fx_runtime *s,
    fx_ui_status status)
{
    switch(status) {
    case FX_UI_COMPLETE:
        s->phase=FX_RUNTIME_RETURN_EQUATION;
        s->event=FX_RUNTIME_EVENT_HANDLER_RETURN;return FX_RUNTIME_ADVANCED;
    case FX_UI_PREPARED:
        s->event=FX_RUNTIME_EVENT_INPUT_PREPARED;return FX_RUNTIME_ADVANCED;
    case FX_UI_WAIT:
        s->event=FX_RUNTIME_EVENT_WAIT_ITERATION;return FX_RUNTIME_WAIT;
    case FX_UI_EXPORT:
        return export_event(s,fx_equation_controller_export_mask(&s->equation));
    case FX_UI_RESET:return reset_event(p,s);
    default:
        return body(s,FX_RUNTIME_EQUATION_GAP,s->main.pending_request,
                    (uint8_t)s->equation.input.request,status);
    }
}
static fx_runtime_status parameter_status(fx_platform *p,fx_runtime *s,
    fx_parameter_menu_status status,uint8_t entering)
{
    switch(status) {
    case FX_PARAMETER_MENU_WAIT:
        s->event=entering ? FX_RUNTIME_EVENT_WAIT_ENTER : FX_RUNTIME_EVENT_WAIT_ITERATION;
        return FX_RUNTIME_WAIT;
    case FX_PARAMETER_MENU_DONE:
        s->phase=FX_RUNTIME_RETURN_PARAMETER;
        s->event=FX_RUNTIME_EVENT_HANDLER_RETURN;return FX_RUNTIME_ADVANCED;
    case FX_PARAMETER_MENU_EXPORT:
        return export_event(s,fx_parameter_menu_controller_export_mask(&s->parameter));
    case FX_PARAMETER_MENU_RESET:return reset_event(p,s);
    case FX_PARAMETER_MENU_TIMER:
        s->timer_pending=1;
        s->timer_period=fx_parameter_menu_controller_timer_period(&s->parameter);
        s->event=FX_RUNTIME_EVENT_TIMER;return FX_RUNTIME_TIMER;
    default:
        body(s,FX_RUNTIME_PARAMETER_GAP,s->parameter.request.kind,
             s->parameter.request.argument,status);
        s->request.page=s->parameter.request.page;
        return FX_RUNTIME_REQUEST;
    }
}
static fx_runtime_status table_status(fx_platform *p,fx_runtime *s,
    fx_ui_status status)
{
    switch(status) {
    case FX_UI_COMPLETE:
        s->phase=FX_RUNTIME_RETURN_TABLE;
        s->event=FX_RUNTIME_EVENT_HANDLER_RETURN;return FX_RUNTIME_ADVANCED;
    case FX_UI_PREPARED:
        s->event=FX_RUNTIME_EVENT_INPUT_PREPARED;return FX_RUNTIME_ADVANCED;
    case FX_UI_WAIT:
        s->event=FX_RUNTIME_EVENT_WAIT_ITERATION;return FX_RUNTIME_WAIT;
    case FX_UI_EXPORT:return export_event(s,fx_table_body_export_mask(&s->table));
    case FX_UI_RESET:return reset_event(p,s);
    default:
        return body(s,FX_RUNTIME_TABLE_GAP,s->main.pending_request,
                    (uint8_t)s->table.table.request,status);
    }
}
fx_runtime_status fx_runtime_step(fx_platform *p,fx_runtime *s,
    const fx_key_input *physical_input,uint8_t timer_elapsed)
{
    if (!p || !p->ram || !s || !s->active) return FX_RUNTIME_INVALID;
    s->event=FX_RUNTIME_EVENT_NONE; s->export_mask=0; ++s->steps;
    if (s->phase==FX_RUNTIME_BODY) {
        s->event=FX_RUNTIME_EVENT_BODY; return FX_RUNTIME_REQUEST;
    }
    if (s->timer_pending) {
        s->event=FX_RUNTIME_EVENT_TIMER;
        if (!timer_elapsed) return FX_RUNTIME_TIMER;
        s->timer_pending=0; s->timer_period=0;
        if (s->phase==FX_RUNTIME_MENU)
            return menu_status(p,s,fx_mode_setup_resume_timer(p,&s->mode),1);
        if (s->phase==FX_RUNTIME_BANK)
            return bank_status(p,s,fx_mode_bank_menu_resume_timer(p,&s->bank),1);
        if (s->phase==FX_RUNTIME_PARAMETER)
            return parameter_status(p,s,fx_parameter_menu_controller_resume_timer(p,&s->parameter),1);
        return FX_RUNTIME_INVALID;
    }
    switch (s->phase) {
    case FX_RUNTIME_BOOT: {
        fx_boot_event_status status=fx_boot_events_tick(p,&s->boot,physical_input);
        if (status==FX_BOOT_EVENT_READY) return ready(s);
        if (status==FX_BOOT_EVENT_RESET) return reset_event(p,s);
        if (status==FX_BOOT_EVENT_EXPORT) return export_event(s,s->boot.keys.export_mask);
        if (status==FX_BOOT_EVENT_WAIT) return FX_RUNTIME_WAIT;
        return body(s,FX_RUNTIME_BOOT_GAP,0,0,status);
    }
    case FX_RUNTIME_MAIN: {
        uint8_t was_waiting=s->main.phase==FX_MAIN_KEY_WAIT;
        fx_main_status status=fx_main_loop_tick(p,&s->main);
        if (status==FX_MAIN_WAIT) {
            s->event=was_waiting ? FX_RUNTIME_EVENT_WAIT_ITERATION : FX_RUNTIME_EVENT_WAIT_ENTER;
            return FX_RUNTIME_WAIT;
        }
        if (status==FX_MAIN_EXPORT) return export_event(s,s->main.keys.export_mask);
        if (status==FX_MAIN_RESET) return reset_event(p,s);
        if (status==FX_MAIN_ADVANCED) {
            s->event=FX_RUNTIME_EVENT_CYCLE_RETURN; return FX_RUNTIME_ADVANCED;
        }
        if (status!=FX_MAIN_REQUEST) return body(s,FX_RUNTIME_MAIN_GAP,0,0,status);
        return main_request(p,s,status);
    }
    case FX_RUNTIME_START_INPUT:
        s->phase=FX_RUNTIME_INPUT;
        return input_status(p,s,fx_ui_controller_begin(p,&s->input,0,&s->cancellation));
    case FX_RUNTIME_INPUT:
        return input_status(p,s,fx_ui_controller_tick(p,&s->input));
    case FX_RUNTIME_RETURN_INPUT:
        if (fx_ui_controller_finish(&s->input,&s->returned)!=FX_UI_COMPLETE)
            return FX_RUNTIME_INVALID;
        if (fx_main_loop_accept_handler(p,&s->main,s->returned)!=FX_MAIN_ADVANCED)
            return FX_RUNTIME_INVALID;
        s->phase=FX_RUNTIME_MAIN; s->event=FX_RUNTIME_EVENT_CYCLE_RETURN;
        return FX_RUNTIME_ADVANCED;
    case FX_RUNTIME_START_MENU:
        s->phase=FX_RUNTIME_MENU; s->menu_kind=s->main.pending_request;
        return menu_status(p,s,s->menu_kind==FX_MAIN_MODE_MENU ?
            fx_mode_menu_begin(p,&s->mode) : fx_setup_menu_begin(p,&s->mode),1);
    case FX_RUNTIME_MENU: return menu_status(p,s,fx_mode_setup_tick(p,&s->mode),0);
    case FX_RUNTIME_RETURN_MENU:
        if (fx_mode_setup_finish(&s->mode,&s->returned)!=FX_MODE_SETUP_DONE)
            return FX_RUNTIME_INVALID;
        if (fx_main_loop_accept_handler(p,&s->main,s->returned)!=FX_MAIN_ADVANCED)
            return FX_RUNTIME_INVALID;
        s->phase=FX_RUNTIME_MAIN; s->event=FX_RUNTIME_EVENT_CYCLE_RETURN;
        return FX_RUNTIME_ADVANCED;
    case FX_RUNTIME_START_PARAMETER:
        s->phase=FX_RUNTIME_PARAMETER;
        return parameter_status(p,s,fx_parameter_menu_controller_begin(p,&s->parameter,NULL),1);
    case FX_RUNTIME_PARAMETER:
        return parameter_status(p,s,fx_parameter_menu_controller_tick(p,&s->parameter),0);
    case FX_RUNTIME_RETURN_PARAMETER:
        if(fx_parameter_menu_controller_finish(&s->parameter,&s->returned)!=FX_PARAMETER_MENU_DONE)
            return FX_RUNTIME_INVALID;
        if(fx_main_loop_accept_handler(p,&s->main,s->returned)!=FX_MAIN_ADVANCED)
            return FX_RUNTIME_INVALID;
        s->phase=FX_RUNTIME_MAIN;s->event=FX_RUNTIME_EVENT_CYCLE_RETURN;
        return FX_RUNTIME_ADVANCED;
    case FX_RUNTIME_START_BANK:
        s->phase=FX_RUNTIME_BANK;
        return bank_status(p,s,fx_mode_bank_menu_begin(p,&s->bank,
            s->mode.request==FX_MODE_REQUEST_MATRIX ? 44 : 45,1),1);
    case FX_RUNTIME_BANK: return bank_status(p,s,fx_mode_bank_menu_tick(p,&s->bank),0);
    case FX_RUNTIME_RETURN_BANK:
        if (fx_mode_bank_menu_finish(&s->bank,&s->returned)!=FX_MENU_DONE)
            return FX_RUNTIME_INVALID;
        s->phase=FX_RUNTIME_MENU;
        return menu_status(p,s,fx_mode_setup_accept_handler(p,&s->mode,s->returned),0);
    case FX_RUNTIME_START_EQUATION:
        s->phase=FX_RUNTIME_EQUATION;
        return equation_status(p,s,fx_equation_controller_begin(p,&s->equation,&s->cancellation));
    case FX_RUNTIME_EQUATION:
        return equation_status(p,s,fx_equation_controller_tick(p,&s->equation));
    case FX_RUNTIME_RETURN_EQUATION:
        if(fx_equation_controller_finish(&s->equation,&s->returned)!=FX_UI_COMPLETE)
            return FX_RUNTIME_INVALID;
        if(fx_main_loop_accept_handler(p,&s->main,s->returned)!=FX_MAIN_ADVANCED)
            return FX_RUNTIME_INVALID;
        s->phase=FX_RUNTIME_MAIN;s->event=FX_RUNTIME_EVENT_CYCLE_RETURN;
        return FX_RUNTIME_ADVANCED;
    case FX_RUNTIME_START_TABLE:
        s->phase=FX_RUNTIME_TABLE;
        return table_status(p,s,fx_table_body_begin(p,&s->table,
            (fx_main_request)s->main.pending_request,&s->cancellation));
    case FX_RUNTIME_TABLE:
        return table_status(p,s,fx_table_body_tick(p,&s->table));
    case FX_RUNTIME_RETURN_TABLE: {
        s->returned=s->table.returned;
        fx_main_status status=fx_main_loop_accept_handler(p,&s->main,s->returned);
        if(status!=FX_MAIN_ADVANCED && status!=FX_MAIN_REQUEST)return FX_RUNTIME_INVALID;
        s->table.active=0;
        if(status==FX_MAIN_REQUEST)return main_request(p,s,status);
        s->phase=FX_RUNTIME_MAIN;s->event=FX_RUNTIME_EVENT_CYCLE_RETURN;
        return FX_RUNTIME_ADVANCED;
    }
    default: return FX_RUNTIME_INVALID;
    }
}
fx_runtime_status fx_runtime_accept_body(fx_platform *p,fx_runtime *s,
    uint8_t action,uint8_t context_return)
{
    if (!p || !p->ram || !s || !s->active || s->phase!=FX_RUNTIME_BODY)
        return FX_RUNTIME_INVALID;
    if (s->request.kind==FX_RUNTIME_MAIN_BODY) {
        fx_main_status status=fx_main_loop_accept_handler(p,&s->main,context_return);
        if (status==FX_MAIN_REQUEST)return main_request(p,s,status);
        if (status!=FX_MAIN_ADVANCED) return FX_RUNTIME_INVALID;
        memset(&s->request,0,sizeof s->request); s->phase=FX_RUNTIME_MAIN;
        s->event=FX_RUNTIME_EVENT_CYCLE_RETURN; return FX_RUNTIME_ADVANCED;
    }
    if (s->request.kind==FX_RUNTIME_INPUT_BODY) {
        fx_ui_status status=fx_ui_controller_resume(p,&s->input,action,context_return);
        if (status==FX_UI_INVALID) return FX_RUNTIME_INVALID;
        memset(&s->request,0,sizeof s->request); s->phase=FX_RUNTIME_INPUT;
        return input_status(p,s,status);
    }
    return FX_RUNTIME_INVALID;
}
