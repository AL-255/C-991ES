/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_ui_controller.h"
#include "fx_input_display.h"
#include "fx_input_recover.h"
#include "fx_editor.h"
#include "../platform/fx_boot.h"
#include "../platform/fx_persistent.h"
#include "../platform/fx_result_classify.h"
#include "../render/fx_render.h"
#include "../render/fx_result_complex.h"
#include "../render/fx_result_pair.h"
#include "../render/fx_result_special.h"
#include "../parse/fx_tokens.h"
#include "../complex/fx_complex.h"
#include "../trig/fx_math_context.h"
#include <string.h>

enum { UI_READY=1, UI_INPUT, UI_DONE, UI_RESET, UI_REQUEST, UI_ERROR };
static uint8_t read_byte(fx_platform *p,uint16_t a) { return fx_data_read(p,0,a); }
static void write_byte(fx_platform *p,uint16_t a,uint8_t v) { fx_data_write(p,0,a,v); }
static int editing(fx_platform *p) { return (read_byte(p,0x80fe)&15)==1; }
static int result_state(fx_platform *p)
{ unsigned state=read_byte(p,0x80fe)&15; return state==3 || state==5; }
/*382E returns true for ordinary scalar contexts. CMPLX uses the polar
 * setting except when coordinate-result metadata explicitly overrides it. */
static int polar_result_policy(fx_platform *p)
{
    if (read_byte(p,0x80f9)!=0xc4) return 1;
    uint8_t metadata=read_byte(p,0x8101);
    return metadata==1 ? 1 : metadata==2 ? 0 : read_byte(p,0x8108)!=0;
}
static int decoded_command(fx_platform *p,uint8_t token,unsigned first,unsigned last)
{ return read_byte(p,0x80f7) && token>=first && token<=last; }
static void accept_token(fx_platform *p,uint8_t token,uint8_t decoded)
{ write_byte(p,0x80f5,token); write_byte(p,0x80f7,decoded); }
static int insert(fx_platform *p,uint8_t token,uint8_t structured)
{ return structured ? fx_editor_insert_construct(p,token) : fx_editor_insert_byte(p,token); }
static int expression_length(fx_platform *p,unsigned *length)
{
    for (*length=0;*length<65536;++*length)
        if (!read_byte(p,(uint16_t)(0x8154+*length))) return 0;
    return -1;
}
static fx_ui_status request(fx_ui_controller *s,fx_ui_request_kind kind)
{ s->request=kind; s->phase=UI_REQUEST; return FX_UI_HANDLER_REQUEST; }
static fx_ui_status finish_action(fx_platform *p,fx_ui_controller *s,uint8_t action);
/*13C66's persistent factor table is needed by the address-based UI even
 * though the supplied-record formatter keeps its trial division host-local. */
static int prime_workspace(fx_platform *p)
{
    fx_number remaining;
    for (unsigned n=0;n<10;++n) remaining.bytes[n]=read_byte(p,(uint16_t)(0x8140+n));
    remaining.bytes[0]&=(uint8_t)~64u;
    if (fx_number_kind(&remaining)!=FX_NUMBER_DECIMAL) return -1;
    uint16_t factor_address=0x847a,exponent_address=0x846d;
    write_byte(p,0x846c,0); write_byte(p,exponent_address,0);
    for (unsigned candidate=2;candidate<=997;++candidate) {
        int prime=1;
        for (unsigned d=2;d*d<=candidate;++d)
            if (candidate%d==0) { prime=0; break; }
        if (!prime) continue;
        fx_number divisor,remainder,quotient;
        (void)fx_decimal_from_integer(&divisor,candidate);
        for (;;) {
            if (fx_number_divmod(&remainder,&quotient,&remaining,&divisor)!=FX_NUMERIC_OK) return -1;
            if (remainder.bytes[0]) {
                if (!quotient.bytes[0]) return 0;
                break;
            }
            if (!read_byte(p,exponent_address)) {
                for (unsigned n=0;n<10;++n) write_byte(p,(uint16_t)(factor_address+n),divisor.bytes[n]);
                write_byte(p,0x846c,(uint8_t)(read_byte(p,0x846c)+1));
            }
            write_byte(p,exponent_address,(uint8_t)(read_byte(p,exponent_address)+1));
            remaining=quotient;
            if (!quotient.bytes[0]) return 0;
        }
        if (read_byte(p,exponent_address)) {
            factor_address=(uint16_t)(factor_address+10); ++exponent_address;
            write_byte(p,exponent_address,0);
        }
    }
    for (unsigned n=0;n<10;++n) write_byte(p,(uint16_t)(factor_address+n),remaining.bytes[n]);
    write_byte(p,exponent_address,(uint8_t)(read_byte(p,exponent_address)+1));
    write_byte(p,0x846c,(uint8_t)(read_byte(p,0x846c)+1));
    return 0;
}
static fx_ui_status start_result_error(fx_platform *p,fx_ui_controller *s)
{
    s->saved_result_state=read_byte(p,0x80fe);
    write_byte(p,0x80fe,128);
    if (fx_error_event_begin(p,&s->input.error,3)<0) return FX_UI_UNIMPLEMENTED;
    s->phase=UI_ERROR; return FX_UI_WAIT;
}

fx_ui_status fx_ui_controller_begin(fx_platform *p,fx_ui_controller *s,
    uint8_t refresh_only,const fx_calculus_control *control)
{
    if (!p || !p->ram || !s) return FX_UI_INVALID;
    memset(s,0,sizeof *s); s->active=1; s->refresh_only=refresh_only;
    if (control) s->cancellation=*control;
    fx_key_normalize_action(p);
    write_byte(p,0x811f,(read_byte(p,0x80fc)&16) ? 7 : 10);
    s->context=fx_input_context_capture(p,0x8154,0x8140);
    if (!(read_byte(p,0x80fe)&96)) write_byte(p,0x8129,0);
    s->phase=UI_READY; return FX_UI_PREPARED;
}

/* DE64's ordinary new-input policy. Operators that require a left operand
 * insert Ans after initialization; natural fraction/root constructs suppress
 * that insertion exactly where E760 sets its temporary token to zero. */
static int prepare_edit(fx_platform *p)
{
    if (read_byte(p,0x80fe)==1 || (read_byte(p,0x80fe)&64)) return 0;
    if (fx_boot_initialize_editor(p,0)!=FX_BOOT_READY) return -1;
    uint8_t token=read_byte(p,0x80f5);
    if (fx_editor_has_natural_input(p) && (token==0xae || token==0x9f)) token=0;
    uint8_t kind=fx_decode_evaluator_token(token,read_byte(p,0x80f9)).kind;
    if ((kind==2 || kind==3 || kind==8) && insert(p,0x8b,0)<0) return -1;
    return 0;
}

static fx_ui_status admit_complex_result(fx_platform *p,fx_ui_controller *s)
{
    if (polar_result_policy(p) || fx_result_format_kind(p) || read_byte(p,0x8130))
        return FX_UI_COMPLETE;
    fx_result_classification classification;
    if (fx_result_classify_address(p,0x814a,0,&classification)!=FX_NUMERIC_OK)
        return FX_UI_UNIMPLEMENTED;
    if (classification.classification==1) return FX_UI_COMPLETE;
    fx_complex value,magnitude;
    for (unsigned n=0;n<10;++n) {
        value.real.bytes[n]=read_byte(p,(uint16_t)(0x8140+n));
        value.imaginary.bytes[n]=read_byte(p,(uint16_t)(0x814a+n));
    }
    if (fx_complex_magnitude(&magnitude,&value,fx_exact_output_allowed(p->ram))!=FX_NUMERIC_OK)
        return request(s,FX_UI_REQUEST_COMPLEX_ADMISSION);
    uint8_t status;
    if (fx_complex_firmware_status(&status,FX_COMPLEX_MAGNITUDE_RETURN,&value,&magnitude)!=FX_NUMERIC_OK)
        return request(s,FX_UI_REQUEST_COMPLEX_ADMISSION);
    return status ? start_result_error(p,s) : FX_UI_COMPLETE;
}

static fx_ui_status redraw(fx_platform *p,fx_ui_controller *s,int expression)
{
    if (s->context.special_view || read_byte(p,0x80fc)!=1)
        return request(s,FX_UI_REQUEST_SPECIAL_CONTEXT);
    fx_render r={p->rom,p->rom_size,p->ram};
    if (expression) {
        int edit=read_byte(p,0x80fe)==1;
        write_byte(p,0x8126,(uint8_t)edit);
        if (!edit) write_byte(p,0x8114,0);
        if (fx_editor_has_natural_input(p)) {
            uint8_t modifiers=read_byte(p,0x80f8);
            if (modifiers&128) write_byte(p,0x80f8,(uint8_t)((modifiers+128)&~8u));
            if (!fx_render_viewport(&r,NULL)) return FX_UI_UNIMPLEMENTED;
        } else if (fx_input_draw_linear_expression(p)) return FX_UI_UNIMPLEMENTED;
    }
    if (read_byte(p,0x80fe)!=1) {
        if (s->context.calculation_mode==2 && read_byte(p,0x80fa)==1)
            return request(s,FX_UI_REQUEST_BASE_RESULT);
        /* EFC0 computes magnitude only as a domain check on host copies.
         * Its temporary result never replaces the persistent result pair. */
        fx_ui_status admitted=admit_complex_result(p,s);
        if (admitted!=FX_UI_COMPLETE) return admitted;
        int displayed=read_byte(p,0x80ff)&16 ? fx_display_pair_result(&r,0x8140,NULL) :
                                             fx_display_complex_result(&r,0x8140,NULL);
        if (displayed!=1) return FX_UI_UNIMPLEMENTED;
        if (fx_result_format_kind(p)==15 && prime_workspace(p))
            return request(s,FX_UI_REQUEST_RESULT_FORMAT);
    }
    if (!(read_byte(p,0x80fe)&32)) {
        uint8_t count;
        if (fx_replay_count(p,&count)) return FX_UI_RESOURCE_LIMIT;
        if (count) write_byte(p,0x8129,1);
    }
    s->phase=UI_DONE; return FX_UI_COMPLETE;
}

static fx_ui_status finish_action(fx_platform *p,fx_ui_controller *s,uint8_t action)
{
    s->handler_action=action;
    if (action==1) write_byte(p,0x80fe,1);
    if (action==1 || action==2) return redraw(p,s,1);
    if (action==3) return redraw(p,s,0);
    if (!(read_byte(p,0x80fe)&32)) {
        uint8_t count;
        if (fx_replay_count(p,&count)) return FX_UI_RESOURCE_LIMIT;
        if (count) write_byte(p,0x8129,1);
    }
    s->phase=UI_DONE; return FX_UI_COMPLETE;
}

static fx_ui_status input_action(fx_platform *p,fx_ui_controller *s)
{
    uint8_t token=read_byte(p,0x80f5);
    int needs_left=decoded_command(p,token,14,22);
    if (!needs_left && (s->context.saved_math_result || s->context.special_view))
        return finish_action(p,s,0);
    token=token==0xee ? 0x99 : token==0xef ? 0xa9 : read_byte(p,(uint16_t)(0x31ae + token));
    accept_token(p,token,0);
    if (prepare_edit(p)) return FX_UI_UNIMPLEMENTED;
    if (!editing(p)) return finish_action(p,s,0);
    s->context.saved_math_result=(uint8_t)((read_byte(p,0x80fc)&16) && read_byte(p,0x80fe)==1);
    unsigned length;
    if (expression_length(p,&length)) return FX_UI_RESOURCE_LIMIT;
    int was_nonempty=needs_left && length!=0;
    if (!needs_left) {
        if (!length || (uint8_t)length>=99) return finish_action(p,s,0);
        write_byte(p,0x8114,(uint8_t)length);
    }
    if (insert(p,read_byte(p,0x80f5),s->structured_input)<0) return FX_UI_UNIMPLEMENTED;
    if (needs_left && (was_nonempty || s->context.saved_math_result || s->context.special_view))
        return finish_action(p,s,1);
    accept_token(p,fx_key_can_math_input(p) ? 0xf0 : 0xed,1);
    fx_input_status status=fx_input_controller_begin(p,&s->input,&s->context,&s->cancellation);
    if (status<0) return status==FX_INPUT_RESOURCE_LIMIT ? FX_UI_RESOURCE_LIMIT : FX_UI_UNIMPLEMENTED;
    if (status==FX_INPUT_PREPARED) { s->phase=UI_INPUT; return FX_UI_PREPARED; }
    s->context=s->input.context;
    return finish_action(p,s,s->input.handler_action);
}

static fx_ui_status evaluate_action(fx_platform *p,fx_ui_controller *s)
{
    fx_input_status status=fx_input_controller_begin(p,&s->input,&s->context,&s->cancellation);
    if (status<0) return status==FX_INPUT_RESOURCE_LIMIT ? FX_UI_RESOURCE_LIMIT : FX_UI_UNIMPLEMENTED;
    if (status==FX_INPUT_PREPARED) { s->phase=UI_INPUT; return FX_UI_PREPARED; }
    s->context=s->input.context;
    return finish_action(p,s,s->input.handler_action);
}

static fx_ui_status command(fx_platform *p,fx_ui_controller *s,unsigned index)
{
    s->command_index=(uint8_t)index; s->command_token=read_byte(p,0x80f5);
    switch (index) {
    case 6: { /* F01A reset/AC policy. */
        fx_input_recovery_context c={s->context.display_address,s->context.result_address,
            s->context.calculation_mode,s->context.saved_math_result,s->context.return_value};
        int result=fx_input_recover_after_error(p,&c);
        if (result<0) return FX_UI_UNIMPLEMENTED;
        s->context.return_value=c.return_value;
        return finish_action(p,s,(uint8_t)(result!=0));
    }
    case 7:case 8:case 9:case 12:case 28:case 29:
        return finish_action(p,s,0);
    case 10:case 11:case 14:case 15:
        return input_action(p,s);
    case 13:case 16:
        return evaluate_action(p,s);
    case 4: {
        if (!fx_editor_has_natural_input(p)) {
            fx_render r={p->rom,p->rom_size,p->ram};
            const fx_number zero={{0}};
            if (fx_display_special_real_number(&r,&zero,NULL)!=1) return FX_UI_UNIMPLEMENTED;
        }
        return finish_action(p,s,2);
    }
    case 5: {
        if (fx_editor_has_natural_result(p))
            fx_result_set_format(p,fx_key_can_math_input(p) ? 13 : 0);
        if (editing(p)) {
            if (s->context.natural_input) return finish_action(p,s,1);
            fx_ui_status admitted=admit_complex_result(p,s);
            if (admitted!=FX_UI_COMPLETE) return admitted;
            if (!s->context.saved_math_result) {
                if (s->context.calculation_mode!=0xc4)
                    for (unsigned n=0;n<10;++n) write_byte(p,(uint16_t)(0x814a+n),0);
                uint8_t cursor=read_byte(p,0x8114);
                fx_render r={p->rom,p->rom_size,p->ram};
                if (fx_display_complex_result(&r,0x8140,NULL)!=1) return FX_UI_UNIMPLEMENTED;
                write_byte(p,0x8114,cursor);
            }
        }
        return finish_action(p,s,2);
    }
    case 17: { /* F6C8 prime-factor result admission. */
        if (s->context.calculation_mode!=0xc1 || s->context.special_view ||
            (read_byte(p,0x80ff)&16)) return finish_action(p,s,0);
        fx_number number;
        for (unsigned n=0;n<10;++n) number.bytes[n]=read_byte(p,(uint16_t)(0x8140+n));
        number.bytes[0]&=(uint8_t)~64u;
        fx_decimal decimal;int64_t integer;
        if (fx_decimal_decode(&decimal,&number)!=FX_NUMERIC_OK || decimal.exponent>9 ||
            fx_decimal_to_integer(&integer,&number)!=FX_NUMERIC_OK || integer<2)
            return start_result_error(p,s);
        uint8_t kind=fx_result_format_kind(p),selection=fx_result_selection(p);
        if (kind!=15 && selection==15) return finish_action(p,s,0);
        fx_result_set_selection(p,kind==15 ? 10 : 15);
        return finish_action(p,s,2);
    }
    case 18:case 19:case 20:case 21: {
        write_byte(p,0x80fa,read_byte(p,(uint16_t)(0x0f60+s->command_token)));
        if (editing(p)) {
            fx_render r={p->rom,p->rom_size,p->ram};
            if (fx_display_special_real_result(&r,0x8140,NULL)!=1) return FX_UI_UNIMPLEMENTED;
        }
        return finish_action(p,s,2);
    }
    case 30:
        if (!editing(p)) return finish_action(p,s,0);
        if (fx_editor_text_action(p,read_byte(p,0x80f5))) return FX_UI_UNIMPLEMENTED;
        return finish_action(p,s,1);
    case 2:case 3: {
        /* Result overflow navigation ED16 is an independent redraw action. */
        if (s->context.natural_result && result_state(p) && read_byte(p,0x8130)) {
            (void)fx_acquire_busy(p);
            uint8_t cursor=read_byte(p,0x8114);
            if (s->command_token==0xe2) write_byte(p,0x8114,(uint8_t)(cursor+1));
            else if (cursor) write_byte(p,0x8114,(uint8_t)(cursor-1));
            else fx_clear_busy(p);
            return finish_action(p,s,3);
        }
        if (read_byte(p,0x80fe)&64) return finish_action(p,s,0);
        fx_error_context c={s->context.display_address,s->context.calculation_mode};
        int restored=fx_error_cursor_restore(p,&c);
        if (restored<0) return FX_UI_UNIMPLEMENTED;
        if (restored==1) return finish_action(p,s,1);
        if (!editing(p)) return finish_action(p,s,0);
        if (fx_editor_text_action(p,s->command_token)) return FX_UI_UNIMPLEMENTED;
        return finish_action(p,s,1);
    }
    case 0:case 1:
        if (read_byte(p,0x80fe)&64) return finish_action(p,s,0);
        if (!s->context.special_view && (result_state(p) || !read_byte(p,0x8154))) {
            uint8_t count,index=read_byte(p,0x8113);
            if (fx_replay_count(p,&count)) return FX_UI_RESOURCE_LIMIT;
            if (count) {
                int recall=0;
                if (!(read_byte(p,0x80fe)&32)) {
                    if (s->command_token==0xe0) {
                        index=count;
                        if (result_state(p) && count>1) --index;
                        recall=1;
                    } else if (!result_state(p)) { index=1; recall=1; }
                } else if (s->command_token==0xe0) {
                    index=(uint8_t)(index-1);
                    if (index>=1) recall=1;
                    else index=1;
                } else {
                    index=(uint8_t)(index+1);
                    if (index<=count) recall=1;
                    else index=count;
                }
                write_byte(p,0x8113,index);
                if (recall) {
                    if (fx_replay_recall(p)) return FX_UI_UNIMPLEMENTED;
                    return finish_action(p,s,2);
                }
            }
        }
        if (!editing(p)) return finish_action(p,s,0);
        if (fx_editor_text_action(p,s->command_token)) return FX_UI_UNIMPLEMENTED;
        return finish_action(p,s,1);
    case 22:case 23: { /* Decimal/DMS toggle F676. */
        if (read_byte(p,0x80ff)&16) return finish_action(p,s,0);
        fx_result_classification classification;
        if (fx_result_classify_address(p,0x814a,0,&classification)!=FX_NUMERIC_OK)
            return FX_UI_UNIMPLEMENTED;
        if (classification.classification!=1) return finish_action(p,s,0);
        if (!polar_result_policy(p)) {
            if (fx_result_classify_address(p,0x8140,classification.continuation,&classification)!=FX_NUMERIC_OK)
                return FX_UI_UNIMPLEMENTED;
            if (classification.classification==2) return finish_action(p,s,0);
        }
        fx_result_set_selection(p,fx_result_format_kind(p)==1 ? 10 : 1);
        return finish_action(p,s,2);
    }
    case 24:case 25: { /* Engineering exponent stepping. */
        if (s->context.calculation_mode==0xc4 || (read_byte(p,0x80ff)&16))
            return finish_action(p,s,0);
        uint8_t kind=fx_result_format_kind(p),next=index==24 ? 5 : 6;
        if (kind>=2 && kind<=9) {
            if (index==24) next=kind<=2 ? 2 : (uint8_t)(kind-1);
            else next=kind>=9 ? 9 : (uint8_t)(kind+1);
        }
        fx_result_set_selection(p,next); return finish_action(p,s,2);
    }
    case 26: { /* Exact/decimal display toggle F5C6. */
        if (read_byte(p,0x80ff)&16) return finish_action(p,s,0);
        uint8_t kind=fx_result_format_kind(p),selection=fx_result_selection(p),next=10;
        if (kind<=9) next=13;
        else if (kind==10) {
            if (selection>=13 && !s->context.natural_result) return finish_action(p,s,0);
            if (selection<13) next=13;
        } else {
            if (kind==15) return finish_action(p,s,0);
            if (s->context.calculation_mode==0xc1 && !s->context.special_view &&
                !(read_byte(p,0x80ff)&16) && read_byte(p,0x810a) && (kind==11 || kind==12)) next=14;
        }
        fx_result_set_selection(p,next); return finish_action(p,s,2);
    }
    case 27: { /* Improper/mixed fraction toggle F626. */
        uint8_t kind=fx_result_format_kind(p),selection=fx_result_selection(p);
        uint8_t next=12;
        if (kind<=10) {
            if (kind!=1 && selection>10 && selection<=13) return finish_action(p,s,0);
            if (read_byte(p,0x8107)) next=11;
        } else if (kind==12) next=11;
        else if (kind==13 || kind==15) return finish_action(p,s,0);
        fx_result_set_selection(p,next); return finish_action(p,s,2);
    }
    default:
        return request(s,FX_UI_REQUEST_RESULT_FORMAT);
    }
}

static fx_ui_status data_action(fx_platform *p,fx_ui_controller *s)
{
    uint8_t token=read_byte(p,0x80f5);
    if (read_byte(p,0x80f7) && token>=0xce) {
        token=token<=0xdf ? read_byte(p,(uint16_t)(0x3100+token)) : 0;
        accept_token(p,token,0);
        if (s->context.natural_input) s->structured_input=1;
        else if (token==0x7c) write_byte(p,0x80f5,0);
    }
    if (read_byte(p,0x80fe)&64) return finish_action(p,s,0);
    token=read_byte(p,0x80f5);
    if (s->context.calculation_mode==0xc4) {
        for (uint16_t a=0x1077;a<0x1081;++a) {
            uint8_t forbidden=read_byte(p,a);
            if (!forbidden) break;
            if (forbidden==token) { token=0; break; }
        }
        write_byte(p,0x80f5,token);
    }
    if (token==0xa4 && !read_byte(p,0x8106)) { token=0; write_byte(p,0x80f5,0); }
    if (!token) return finish_action(p,s,0);
    if (fx_key_is_data_token(p,token) && prepare_edit(p)) return FX_UI_UNIMPLEMENTED;
    if (read_byte(p,0x80fe)!=1) return finish_action(p,s,0);
    if (insert(p,token,s->structured_input)<0) return FX_UI_UNIMPLEMENTED;
    return finish_action(p,s,1);
}

fx_ui_status fx_ui_controller_tick(fx_platform *p,fx_ui_controller *s)
{
    if (!p || !s || !s->active) return FX_UI_INVALID;
    if (s->phase==UI_DONE) return FX_UI_COMPLETE;
    if (s->phase==UI_RESET) return FX_UI_RESET;
    if (s->phase==UI_REQUEST) return FX_UI_HANDLER_REQUEST;
    if (s->phase==UI_ERROR) {
        fx_key_controller_status status=fx_error_event_tick(p,&s->input.error);
        if (status==FX_KEY_CONTROLLER_WAIT) return FX_UI_WAIT;
        if (status==FX_KEY_CONTROLLER_EXPORT) return FX_UI_EXPORT;
        if (status==FX_KEY_CONTROLLER_RESET) { s->phase=UI_RESET; return FX_UI_RESET; }
        if (status<0) return FX_UI_UNIMPLEMENTED;
        uint8_t token;
        (void)fx_error_event_finish(&s->input.error,&token);
        accept_token(p,token,1); fx_result_clear(p);
        fx_error_context error={s->context.display_address,s->context.calculation_mode};
        int restored=fx_error_cursor_restore(p,&error);
        if (restored<0) return FX_UI_UNIMPLEMENTED;
        if (restored!=1) {
            fx_input_recovery_context recovery={s->context.display_address,s->context.result_address,
                s->context.calculation_mode,s->context.saved_math_result,s->context.return_value};
            if (fx_input_recover_after_error(p,&recovery)<0) return FX_UI_UNIMPLEMENTED;
            s->context.return_value=recovery.return_value;
        } else {
            if (s->saved_result_state==4) {
                write_byte(p,0x80fc,1); write_byte(p,0x80fd,0);
                write_byte(p,0x80fe,1); write_byte(p,0x80ff,0);
                for (unsigned n=0;n<100;++n) {
                    uint8_t b=read_byte(p,(uint16_t)(0x81b8+n));
                    write_byte(p,(uint16_t)(s->context.display_address+n),b);
                    if (!b) break;
                }
            }
            unsigned length;
            if (expression_length(p,&length)) return FX_UI_RESOURCE_LIMIT;
            write_byte(p,0x8114,(uint8_t)length);
        }
        return finish_action(p,s,1);
    }
    if (s->phase==UI_INPUT) {
        fx_input_status status=fx_input_controller_tick(p,&s->input);
        if (status==FX_INPUT_WAIT) return FX_UI_WAIT;
        if (status==FX_INPUT_EXPORT) return FX_UI_EXPORT;
        if (status==FX_INPUT_RESET) { s->phase=UI_RESET; return FX_UI_RESET; }
        if (status<0) return status==FX_INPUT_RESOURCE_LIMIT ? FX_UI_RESOURCE_LIMIT : FX_UI_UNIMPLEMENTED;
        s->context=s->input.context;
        return finish_action(p,s,s->input.handler_action);
    }
    if (s->phase!=UI_READY) return FX_UI_INVALID;
    if ((s->context.calculation_mode!=0xc1 && s->context.calculation_mode!=0xc4) ||
        read_byte(p,0x80fc)!=1 || s->context.special_view)
        return request(s,FX_UI_REQUEST_SPECIAL_CONTEXT);
    if (s->refresh_only) return redraw(p,s,1);
    uint8_t token=read_byte(p,0x80f5);
    if (fx_key_is_data_token(p,token)) return data_action(p,s);
    unsigned index=(uint8_t)(token+32);
    if (decoded_command(p,token,14,22)) index=10;
    else if (decoded_command(p,token,23,31)) index=11;
    else if (token<0xe0) return finish_action(p,s,0);
    return command(p,s,index);
}

fx_ui_status fx_ui_controller_resume(fx_platform *p,fx_ui_controller *s,
    uint8_t action,uint8_t context_return)
{
    if (!p || !s || !s->active || s->phase!=UI_REQUEST || action>3) return FX_UI_INVALID;
    s->request=FX_UI_REQUEST_NONE; s->context.return_value=context_return;
    return finish_action(p,s,action);
}

fx_ui_status fx_ui_controller_finish(fx_ui_controller *s,uint8_t *context_return)
{
    if (!s || !s->active || (s->phase!=UI_DONE && s->phase!=UI_RESET)) return FX_UI_INVALID;
    if (context_return) *context_return=s->context.return_value;
    s->active=0;
    return s->phase==UI_RESET ? FX_UI_RESET : FX_UI_COMPLETE;
}
