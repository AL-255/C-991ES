/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_input_controller.h"
#include "fx_equation_controller.h"
#include "../parse/fx_eval_transport.h"
#include "fx_error_boundary.h"
#include "fx_input_prepare.h"
#include "fx_input_recover.h"
#include "fx_input_codec.h"
#include "fx_input_display.h"
#include "fx_editor.h"
#include "fx_linalg_controller.h"
#include "../platform/fx_persistent.h"
#include "../platform/fx_result_classify.h"
#include "../platform/fx_boot_events.h"
#include "../render/fx_render.h"
#include "../render/fx_result_complex.h"
#include "../render/fx_result_pair.h"
#include "../trig/fx_math_context.h"
#include <string.h>

enum { INPUT_PREPARED = 1, INPUT_ERROR_WAIT, INPUT_DONE, INPUT_RESET };
static uint8_t byte_at(fx_platform *p, uint16_t a) { return fx_data_read(p, 0, a); }
static void put_byte(fx_platform *p, uint16_t a, uint8_t v) { fx_data_write(p, 0, a, v); }
static uint16_t word_at(fx_platform *p, uint16_t a)
{ return (uint16_t)(byte_at(p,a) | (uint16_t)byte_at(p,(uint16_t)(a+1)) << 8); }
static void put_word(fx_platform *p, uint16_t a, uint16_t v)
{ put_byte(p,a,(uint8_t)v); put_byte(p,(uint16_t)(a+1),(uint8_t)(v>>8)); }
static void load_records(fx_platform *p, uint16_t a, fx_number values[2])
{ for (unsigned n=0;n<20;++n) values[n/10].bytes[n%10]=byte_at(p,(uint16_t)(a+n)); }
static void write_records(fx_platform *p, uint16_t a, const fx_number values[2])
{ for (unsigned n=0;n<20;++n) put_byte(p,(uint16_t)(a+n),values[n/10].bytes[n%10]); }
static void zero_imaginary(fx_platform *p, uint16_t result)
{ for (unsigned n=10;n<20;++n) put_byte(p,(uint16_t)(result+n),0); }
static void select_initial_format(fx_platform *p)
{ fx_result_set_format(p,byte_at(p,0x80f5)==0xf0 ? 13 : 0); }
static fx_input_status complete(fx_input_controller *s, uint8_t action)
{ s->handler_action=action; s->phase=INPUT_DONE; return FX_INPUT_COMPLETE; }

fx_input_context fx_input_context_capture(fx_platform *p, uint16_t display,
                                          uint16_t result)
{
    fx_input_context c;
    memset(&c,0,sizeof c);
    c.return_value=1;
    c.display_address=display; c.result_address=result;
    if (!p) return c;
    c.calculation_mode=byte_at(p,0x80f9);
    c.saved_math_result=(uint8_t)((byte_at(p,0x80fc)&16) && byte_at(p,0x80fe)==1);
    c.natural_input=fx_editor_has_natural_input(p);
    c.natural_result=fx_editor_has_natural_result(p);
    c.special_view=fx_editor_is_special_view(p);
    return c;
}

fx_input_status fx_input_controller_begin(fx_platform *p, fx_input_controller *s,
    const fx_input_context *context, const fx_calculus_control *cancellation)
{
    if (!p || !s || !context) return FX_INPUT_INVALID;
    memset(s,0,sizeof *s); s->context=*context; s->active=1;
    if (cancellation) s->cancellation=*cancellation;
    s->continuation=(uint8_t)(byte_at(p,0x80fe)&64);
    /* DEF8/DF66/DF28 history/result gates precede evaluator dispatch. */
    uint8_t mode=byte_at(p,0x80f9), screen=byte_at(p,0x80fc);
    int replay_mode=(mode==0x45 || mode==12) && screen==1;
    int inequality=mode==0x4b && screen==1;
    if ((mode==0x45 && screen==1 && byte_at(p,0x80fd)==3) || inequality) {
        if (fx_result_format_kind(p)) {
            fx_input_recovery_context recovery={context->display_address,
                context->result_address,context->calculation_mode,
                context->saved_math_result,context->return_value};
            if (fx_input_reset_context(p,&recovery)<0) return FX_INPUT_UNIMPLEMENTED;
            s->context.return_value=recovery.return_value;
            return complete(s,0);
        }
        put_byte(p,0x80fe,3); select_initial_format(p); return complete(s,2);
    }
    if (replay_mode) {
        uint8_t count;
        if (fx_replay_count(p,&count)) return FX_INPUT_RESOURCE_LIMIT;
        uint8_t index=(uint8_t)(byte_at(p,0x8113)+1); put_byte(p,0x8113,index);
        if (index>count) {
            fx_input_recovery_context recovery={context->display_address,
                context->result_address,context->calculation_mode,
                context->saved_math_result,context->return_value};
            if (fx_input_reset_context(p,&recovery)<0) return FX_INPUT_UNIMPLEMENTED;
            s->context.return_value=recovery.return_value;
            return complete(s,0);
        }
        if (fx_replay_recall(p)) return FX_INPUT_UNIMPLEMENTED;
        select_initial_format(p); return complete(s,2);
    }
    if (context->calculation_mode!=0xc1 && context->calculation_mode!=0xc4 &&
        context->calculation_mode!=6 && context->calculation_mode!=7 &&
        (context->calculation_mode!=0x45 || byte_at(p,0x80fa)<1 || byte_at(p,0x80fa)>2))
        return FX_INPUT_UNIMPLEMENTED;
    if (!byte_at(p,context->display_address)) return complete(s,0);
    if (screen!=1 && screen!=0xa0 && !(context->calculation_mode==0x45 && screen==21) &&
        !((context->calculation_mode==6 || context->calculation_mode==7) &&
          (screen==19 || screen==20))) return FX_INPUT_UNIMPLEMENTED;
    if (context->special_view && !(screen==0xa0 && byte_at(p,0x80fd)==2))
        return FX_INPUT_UNIMPLEMENTED;
    put_word(p,0x812c,context->display_address);
    int ready=fx_input_needs_export(p) ? fx_input_prepare_exported(p,&s->prepared_source) :
                                       fx_input_prepare_direct(p,&s->prepared_source);
    if (ready<0) return FX_INPUT_RESOURCE_LIMIT;
    s->preparation_ok=(uint8_t)ready;
    s->current_source=s->continuation ? word_at(p,0x812e) : s->prepared_source;
    load_records(p,context->result_address,s->saved_result);
    s->phase=INPUT_PREPARED;
    return FX_INPUT_PREPARED;
}

static void load_variables(fx_platform *p, fx_input_controller *s)
{
    for (unsigned slot=0;slot<FX_VARIABLE_COUNT;++slot)
        for (unsigned n=0;n<10;++n) {
            s->variables.values[slot][0].bytes[n]=byte_at(p,(uint16_t)(0x8226+10*slot+n));
            s->variables.values[slot][1].bytes[n]=byte_at(p,(uint16_t)(0x8408+10*slot+n));
        }
    s->original_variables=s->variables;
}
static void commit_variables(fx_platform *p, fx_input_controller *s)
{
    for (unsigned slot=0;slot<FX_VARIABLE_COUNT;++slot) {
        int changed=0;
        unsigned parts=byte_at(p,0x80f9)==0xc4 ? 2 : 1;
        for (unsigned part=0;part<parts;++part)
            for (unsigned n=0;n<10;++n)
                if (s->variables.values[slot][part].bytes[n]!=
                    byte_at(p,(uint16_t)((part ? 0x8408 : 0x8226)+10*slot+n))) changed=1;
        if (changed)
            fx_store_variable_records(p,(uint8_t)slot,s->variables.values[slot]);
    }
}
typedef struct { fx_platform *platform; fx_input_controller *state; } cancellation_context;
static int cancelled(void *userdata)
{
    cancellation_context *c=userdata;
    /* The prepared-storage calculus driver publishes X and owns5550.
     * This callback only notifies the supplied cancellation observer. */
    return c->state->cancellation.cancelled &&
           c->state->cancellation.cancelled(c->state->cancellation.userdata);
}

static fx_input_status start_error(fx_platform *p, fx_input_controller *s)
{
    put_byte(p,0x80fe,0x80);
    fx_key_controller_status result=fx_error_event_begin(p,&s->error,s->evaluator_status);
    if (result<0) return FX_INPUT_UNIMPLEMENTED;
    s->phase=INPUT_ERROR_WAIT; return FX_INPUT_WAIT;
}

static fx_input_status commit_result(fx_platform *p, fx_input_controller *s)
{
    fx_result_clear_flags(p); select_initial_format(p); put_byte(p,0x80fe,3);
    uint8_t tag=byte_at(p,s->context.result_address)&0xf0;
    if (tag==0x60 || tag==0x90) {
        /* F414: retain the numerical reference/imaginary bytes. Only the
         * bank answer, screen and cursor are committed here. */
        fx_eval_storage storage={p->ram,65536u,p->rom,p->rom_size};
        put_byte(p,0x80fc,tag==0x60 ? 19 : 20);
        uint8_t header=byte_at(p,s->context.result_address);
        if (fx_eval_storage_copy_slot(&storage,3,header)!=FX_NUMERIC_OK)
            return FX_INPUT_UNIMPLEMENTED;
        put_byte(p,0x80fa,3); fx_result_reset_layout(p);
        s->context.return_value=0;
        return complete(s,0);
    }
    if (s->evaluator_status==0 || s->evaluator_status==36) {
        if (s->context.calculation_mode!=0xc4) zero_imaginary(p,s->context.result_address);
    } else if (s->evaluator_status==34) {
        if (s->context.calculation_mode==0xc4) put_byte(p,0x8101,2);
        else put_byte(p,0x80ff,18);
    } else if (s->evaluator_status==35) {
        if (s->context.calculation_mode==0xc4) put_byte(p,0x8101,1);
        else put_byte(p,0x80ff,17);
    }
    else if (s->evaluator_status==37) {
        if (byte_at(p,(uint16_t)(s->context.result_address+10))==0x70)
            zero_imaginary(p,s->context.result_address);
        else put_byte(p,0x80ff,20);
    }
    if(s->context.calculation_mode==0x45 && byte_at(p,0x80fc)==21) {
        put_byte(p,0x80ff,0);fx_result_clear_display_state(p);
        if(fx_equation_commit_coefficient(p,s->context.result_address))return FX_INPUT_UNIMPLEMENTED;
        s->context.return_value=0;return complete(s,0);
    }
    /* E680/E75E: bank coefficient editing is a physical cell route,
     * distinct from the83FD variable-list coefficient views below. */
    if (byte_at(p,0x80fc)==19 || byte_at(p,0x80fc)==20) {
        if (byte_at(p,0x80ff)&16) zero_imaginary(p,s->context.result_address);
        put_byte(p,0x80ff,0); fx_result_clear_display_state(p);
        uint8_t native_status;
        if (fx_linalg_ui_store_cell(p,s->context.result_address,
                byte_at(p,0x80fa),byte_at(p,0x811d),byte_at(p,0x811e),
                &native_status)!=FX_NUMERIC_OK) return FX_INPUT_UNIMPLEMENTED;
        fx_render render={p->rom,p->rom_size,p->ram};
        uint16_t dims=(uint16_t)(0x80e0+2u*byte_at(p,0x80fa));
        if (fx_linalg_selection_event(&render,byte_at(p,dims),
                byte_at(p,(uint16_t)(dims+1)),0xed)<0)
            return FX_INPUT_UNIMPLEMENTED;
        s->context.return_value=0; return complete(s,0);
    }
    /* F4D2..F506: special coefficient views commit one list cell without
     * touching Ans, PreAns or replay, and clear the named D9EE return. */
    if (s->context.special_view) {
        uint8_t index=byte_at(p,0x83fd);
        if (index>=10) return FX_INPUT_RESOURCE_LIMIT;
        uint8_t id=byte_at(p,(uint16_t)(0x83fe + index));
        if (id>=10) return FX_INPUT_INVALID;
        if (byte_at(p,0x80ff)&16) zero_imaginary(p,s->context.result_address);
        put_byte(p,0x80ff,0); fx_result_clear_display_state(p);
        fx_store_variable_address(p,id,s->context.result_address);
        put_byte(p,0x83fd,(uint8_t)(index+1));
        s->context.return_value=0;
        return complete(s,0);
    }
    if (s->context.calculation_mode==0xc1)
        for (unsigned n=0;n<10;++n) put_byte(p,(uint16_t)(0x828a+n),byte_at(p,(uint16_t)(0x8230+n)));
    if (byte_at(p,0x80ff)&16) {
        fx_number answer[2]; load_records(p,s->context.result_address,answer);
        fx_number_zero(&answer[1]); fx_store_ans_records(p,answer);
    } else fx_store_ans_address(p,s->context.result_address);
    if (byte_at(p,(uint16_t)(s->current_source-1))==':') {
        s->continuation=1; put_byte(p,0x80fe,(uint8_t)(byte_at(p,0x80fe)|64));
        put_word(p,0x812e,s->current_source);
    } else s->continuation=0;
    /* F576..F58A: a finished CALC item3 expression advances to result16
     * only after continuation has been resolved. */
    if (!s->continuation && byte_at(p,0x80fc)==0xa0 && byte_at(p,0x80fd)==3)
        put_byte(p,0x80fd,16);
    /* The native Ans copy leaves its remaining count at zero. EA0C uses
     * that value as the classifier companion; no CPU local is needed. */
    fx_result_classification classification;
    if (fx_result_classify_address(p,0x814a,0,&classification)!=FX_NUMERIC_OK ||
        fx_replay_append_prepared(p,classification.classification))
        return FX_INPUT_UNIMPLEMENTED;
    return complete(s,2);
}

static fx_input_status evaluate(fx_platform *p, fx_input_controller *s)
{
    if (!s->preparation_ok) { s->evaluator_status=2; return start_error(p,s); }
    fx_display_port_sleep(p);
    size_t length;
    for (length=0;length<sizeof s->input;++length) {
        uint8_t token=byte_at(p,(uint16_t)(s->current_source+length));
        /* Colon ends this transaction but remains on the original bus. */
        s->input[length]=token==':' ? 0 : token;
        if (!s->input[length]) break;
    }
    if (length==sizeof s->input) return FX_INPUT_RESOURCE_LIMIT;
    load_variables(p,s);
    put_byte(p,0x8125,0); /* Ordinary evaluator scratch policy,171F4. */
    fx_eval_options options={s->context.calculation_mode,
        byte_at(p,0x8106),byte_at(p,0x8105)};
    fx_eval_environment environment={byte_at(p,0x80fc),byte_at(p,0x80f5),
        byte_at(p,0x810c),byte_at(p,0x8124),byte_at(p,0x8102),
        byte_at(p,0x8103),byte_at(p,0x80fa)};
    fx_eval_state evaluator_state={&s->variables,NULL};
    fx_number prior_answer;
    for (unsigned n=0;n<10;++n) prior_answer.bytes[n]=byte_at(p,(uint16_t)(0x828a+n));
    fx_eval_result result={0};
    cancellation_context cancellation={p,s};
    fx_calculus_control control={cancelled,&cancellation};
    fx_eval_storage storage={p->ram,65536u,p->rom,p->rom_size};
    fx_eval_source source={s->current_source,s->context.result_address,NULL,NULL};
    uint16_t returned_source=s->current_source;
    fx_eval_status status=fx_evaluate_prepared_source(length+1,&options,
        &environment,&evaluator_state,&control,&prior_answer,
        &storage,&source,&returned_source,NULL,&result);
    put_byte(p,0x8124,(uint8_t)(byte_at(p,0x8124)&~1u));
    s->unsupported_token=result.unsupported_token;
    if (status<0) return status==FX_EVAL_RESOURCE_LIMIT ? FX_INPUT_RESOURCE_LIMIT : FX_INPUT_UNIMPLEMENTED;
    s->evaluator_status=(uint8_t)status;
    s->current_source=returned_source;
    /* The addressed parser has published the actual result buffer. Retain
     * its current physical secondary bytes and operand/workspace aliases. */
    commit_variables(p,s);
    if (status>0 && status<32) {
        uint8_t cursor=(uint8_t)((uint8_t)s->current_source-(uint8_t)s->prepared_source);
        if (s->context.natural_input) {
            if (fx_editor_export_input(p,s->context.display_address,s->prepared_source,cursor,0))
                return FX_INPUT_RESOURCE_LIMIT;
        } else put_byte(p,0x8114,cursor);
        return start_error(p,s);
    }
    return commit_result(p,s);
}

fx_input_status fx_input_controller_tick(fx_platform *p, fx_input_controller *s)
{
    if (!p || !s || !s->active) return FX_INPUT_INVALID;
    if (s->phase==INPUT_PREPARED) return evaluate(p,s);
    if (s->phase==INPUT_DONE) return FX_INPUT_COMPLETE;
    if (s->phase==INPUT_RESET) return FX_INPUT_RESET;
    if (s->phase!=INPUT_ERROR_WAIT) return FX_INPUT_INVALID;
    /* Preserve the ordinary public error API's existing restart boundary.
     * CALC outer composition exposes the earlier completed-export phase. */
    fx_key_controller_status event=byte_at(p,0x80fc)==0xa0 ?
        fx_error_event_tick_export_boundary(p,&s->error) : fx_error_event_tick(p,&s->error);
    if (event==FX_KEY_CONTROLLER_WAIT) return FX_INPUT_WAIT;
    if (event==FX_KEY_CONTROLLER_EXPORT) return FX_INPUT_EXPORT;
    if (event<0) return FX_INPUT_UNIMPLEMENTED;
    uint8_t token;
    (void)fx_error_event_finish(&s->error,&token);
    if (event==FX_KEY_CONTROLLER_RESET) { s->phase=INPUT_RESET; return FX_INPUT_RESET; }
    put_byte(p,0x80f5,token); put_byte(p,0x80f7,1);
    fx_result_clear(p);
    if (s->context.saved_math_result) write_records(p,s->context.result_address,s->saved_result);
    fx_error_context error={s->context.display_address,s->context.calculation_mode};
    int handled=fx_error_cursor_restore(p,&error);
    if (handled<0) return FX_INPUT_UNIMPLEMENTED;
    if (handled==1) return complete(s,1);
    fx_input_recovery_context recovery={s->context.display_address,s->context.result_address,
        s->context.calculation_mode,s->context.saved_math_result,s->context.return_value};
    handled=fx_input_recover_after_error(p,&recovery);
    if (handled<0) return FX_INPUT_UNIMPLEMENTED;
    s->context.return_value=recovery.return_value;
    return complete(s,(uint8_t)(handled!=0));
}

fx_input_status fx_input_controller_finish(fx_input_controller *s, uint8_t *action)
{
    if (!s || !s->active || (s->phase!=INPUT_DONE && s->phase!=INPUT_RESET)) return FX_INPUT_INVALID;
    if (action) *action=s->handler_action;
    s->active=0;
    return s->phase==INPUT_RESET ? FX_INPUT_RESET : FX_INPUT_COMPLETE;
}

fx_input_status fx_input_controller_present(fx_platform *p, fx_input_controller *s)
{
    if (!p || !s || s->phase!=INPUT_DONE || (s->handler_action!=1 && s->handler_action!=2))
        return FX_INPUT_INVALID;
    if (s->context.special_view || byte_at(p,0x80fc)!=1)
        return FX_INPUT_UNIMPLEMENTED;
    int editing=byte_at(p,0x80fe)==1;
    put_byte(p,0x8126,(uint8_t)editing);
    if (!editing) put_byte(p,0x8114,0);
    fx_render render={p->rom,p->rom_size,p->ram};
    if (fx_editor_has_natural_input(p)) {
        uint8_t modifiers=byte_at(p,0x80f8);
        if (modifiers&128) put_byte(p,0x80f8,(uint8_t)((modifiers+128)&~8u));
        if (!fx_render_viewport(&render,NULL)) return FX_INPUT_UNIMPLEMENTED;
    } else if (fx_input_draw_linear_expression(p)) return FX_INPUT_UNIMPLEMENTED;
    if (!editing) {
        int displayed=byte_at(p,0x80ff)&16 ?
            fx_display_pair_result(&render,s->context.result_address,NULL) :
            fx_display_complex_result(&render,s->context.result_address,NULL);
        if (displayed!=1) return FX_INPUT_UNIMPLEMENTED;
    }
    if (!(byte_at(p,0x80fe)&32)) {
        uint8_t count;
        if (fx_replay_count(p,&count)) return FX_INPUT_RESOURCE_LIMIT;
        if (count) put_byte(p,0x8129,1);
    }
    return FX_INPUT_COMPLETE;
}
