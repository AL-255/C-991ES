/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_solve_outer.h"
#include "ui/fx_input_display.h"
#include "ui/fx_editor.h"
#include "ui/fx_input_recover.h"
#include "fx_error_boundary.h"
#include "trig/fx_math_context.h"
#include "ui/fx_calc_scan.h"
#include "ui/fx_input_prepare.h"
#include "platform/fx_boot.h"
#include "platform/fx_persistent.h"
#include "render/fx_render.h"
#include "render/fx_render_context.h"
#include "render/fx_result_pair.h"
#include "render/fx_result_complex.h"
#include "render/fx_result_special.h"
#include "render/fx_result_format_state.h"
#include "format/fx_format.h"
#include "numeric/fx_raw_fraction_convert.h"
#include <string.h>

static uint8_t read_byte(fx_platform *p, uint16_t address)
{ return fx_data_read(p,0,address); }
static void write_byte(fx_platform *p, uint16_t address, uint8_t value)
{ fx_data_write(p,0,address,value); }

void fx_solve_outer_begin(fx_solve_outer *s,
    fx_solve_expression_callback expression, void *userdata,
    const fx_calculus_control *cancellation)
{
    if (!s) return;
    memset(s,0,sizeof *s);
    s->active=1; s->expression=expression; s->expression_userdata=userdata;
    if (cancellation) s->cancellation=*cancellation;
}

fx_solve_outer_status fx_solve_outer_adopt(fx_platform *p, fx_solve_outer *s)
{
    if (!p || !p->ram || !s || !s->active) return FX_SOLVE_OUTER_INVALID;
    if (s->pending_owner || s->scanner_error_pending) return FX_SOLVE_OUTER_INVALID;
    if (read_byte(p,0x80f9)!=0xc1 || read_byte(p,0x80fc)!=0xc0)
        return FX_SOLVE_OUTER_UNIMPLEMENTED;
    if (s->solve.active && s->solve.phase!=FX_SOLVE_UI_DONE)
        return FX_SOLVE_OUTER_INVALID;
    memset(&s->solve,0,sizeof s->solve);
    s->solve.active=1; s->solve.phase=FX_SOLVE_UI_VARIABLES;
    s->solve.handler_action=1;
    s->solve.expression=s->expression;
    s->solve.expression_userdata=s->expression_userdata;
    s->solve.cancellation=s->cancellation;
    return FX_SOLVE_OUTER_COMPLETE;
}

fx_solve_outer_status fx_solve_outer_restore(fx_platform *p, fx_solve_outer *s)
{
    unsigned length;
    if (!p || !p->ram || !s || !s->active) return FX_SOLVE_OUTER_INVALID;
    if (!((read_byte(p,0x80fc)==0xc0 && read_byte(p,0x80fd)==4) ||
          (read_byte(p,0x80fc)==0xa0 && read_byte(p,0x80fd)==3)))
        return FX_SOLVE_OUTER_UNIMPLEMENTED;
    if (s->pending_owner || s->scanner_error_pending) return FX_SOLVE_OUTER_INVALID;
    /* Check the host bound before writes; no native return frame is used. */
    for (length=0;length<100 && read_byte(p,(uint16_t)(0x81b8+length));++length) {}
    if (length==100) return FX_SOLVE_OUTER_RESOURCE_LIMIT;
    if (read_byte(p,0x80fd)==4) {
        write_byte(p,0x80f5,0xed); write_byte(p,0x80f7,1);
    }
    for (unsigned n=0;n<=length;++n)
        write_byte(p,(uint16_t)(0x8154+n),read_byte(p,(uint16_t)(0x81b8+n)));
    write_byte(p,0x80fe,1);
    s->handler_action=0; s->context_return=0;
    return FX_SOLVE_OUTER_COMPLETE;
}

/* Prompt presentation follows the controller boundary with physical
 * CALC/SOLVE screen state and the existing renderer policies. */
static fx_solve_ui_status present_prompt(fx_platform *p)
{
    fx_render render={p->rom,p->rom_size,p->ram};
    uint16_t label=0x11a1, text=0x8154;
    uint8_t count;
    int marked_fraction=(read_byte(p,0x8140)&0xf0)==0x60;
    if (!(read_byte(p,0x80fe)&96)) write_byte(p,0x8129,0);
    write_byte(p,0x811f,10); write_byte(p,0x8126,0); write_byte(p,0x8114,0);
    /*37A0 draws presentation bytes directly, rather than decoding the
     * coefficient name or the words 'Solve for' as evaluator tokens. */
    fx_draw_text(&render,0,2,&label);
    fx_draw_text(&render,0,1,&text);
    /* CALC retains its actual A0/item2 complex display policy. */
    if (read_byte(p,0x80fc)==0xa0) {
        if (fx_display_complex_result(&render,0x8140,NULL)!=1)
            return FX_SOLVE_UI_UNIMPLEMENTED;
        if (!(read_byte(p,0x80fe)&32)) {
            if (fx_replay_count(p,&count)) return FX_SOLVE_UI_RESOURCE_LIMIT;
            if (count) write_byte(p,0x8129,1);
        }
        return FX_SOLVE_UI_PROMPT;
    }
    if (marked_fraction) {
        fx_number value, assessment;
        uint8_t selection=read_byte(p,0x8100);
        unsigned i;
        for (i=0;i<10;++i) value.bytes[i]=read_byte(p,(uint16_t)(0x8140+i));
        /* C060 assesses a marked fraction numerically, then passes the
         * original 6x record to its decimal serializer. That serializer
         * admits only decimal records and leaves its initialized text
         * empty. The coefficient prompt retains the raw record. */
        if (fx_display_special_real_number(&render,NULL,NULL)!=1)
            return FX_SOLVE_UI_UNIMPLEMENTED;
        if (fx_raw_fraction_convert(&assessment,&value)!=FX_NUMERIC_OK)
            return FX_SOLVE_UI_UNIMPLEMENTED;
        fx_apply_result_format_state(&render,&assessment,selection,10);
        /* A missing/zero denominator produces Math3 during AB8E's
         * assessment. Its classifier is consequently nonzero and takes
         * the same display-port sleep branch before the empty fallback. */
        if (fx_number_kind(&assessment)==FX_NUMBER_ERROR) fx_display_port_sleep(p);
    } else if (fx_display_special_real_result(&render,0x8140,NULL)!=1)
        return FX_SOLVE_UI_UNIMPLEMENTED;
    {
        /* B070 also publishes its host display packet on the plain prompt
         * branch. This packet is distinct from the calculator replay bank. */
        fx_number value;
        fx_format_options options=fx_format_default_options();
        fx_format_result result;
        uint8_t formatted[512];
        unsigned i, packet_length;
        static const unsigned bits[5]={7,3,2,1,0}, offsets[5]={10,11,12,14,15};
        static const uint8_t hexadecimal[]="0123456789ABCDEF";
        for (i=0;i<10;++i) value.bytes[i]=read_byte(p,(uint16_t)(0x8140+i));
        options.selection=read_byte(p,0x8100); options.math_output=0;
        options.mixed_fraction=read_byte(p,0x8107);
        options.display_mode=read_byte(p,0x8102); options.digits=read_byte(p,0x8103);
        options.decimal_dot=read_byte(p,0x8104);
        if (marked_fraction) {
            formatted[0]=0; result.length=0; result.kind=10; result.recognized=0;
        } else if (fx_format_number(&value,&options,formatted,sizeof formatted,&result)!=FX_FORMAT_OK)
            return FX_SOLVE_UI_UNIMPLEMENTED;
        for (i=0;i<=result.length;++i) write_byte(p,(uint16_t)(0x9838+i),formatted[i]);
        for (i=0;i<48;++i) write_byte(p,(uint16_t)(0x9804+i),0);
        write_byte(p,0x9804,17); write_byte(p,0x9805,255); write_byte(p,0x9807,48);
        for (i=0;i<4;++i) write_byte(p,(uint16_t)(0x9808+i),255);
        write_byte(p,0x980d,read_byte(p,0x8105)>=4 && read_byte(p,0x8105)<=6 ?
                   (uint8_t)(read_byte(p,0x8105)-3) : 0);
        for (i=0;i<5;++i) write_byte(p,(uint16_t)(0x9804+offsets[i]),
                                    (uint8_t)((read_byte(p,0x80f8)>>bits[i])&1));
        packet_length=(unsigned)result.length+1;
        if (result.length) {
            packet_length+=4; write_byte(p,0x9834,34); write_byte(p,0x9835,255);
            write_byte(p,0x9836,(uint8_t)(packet_length>>8));
            write_byte(p,0x9837,(uint8_t)packet_length);
        } else write_byte(p,0x9834,0);
        packet_length+=48;
        for (i=0;i<4;++i) write_byte(p,(uint16_t)(0x9800+i),hexadecimal[(packet_length>>(12-4*i))&15]);
    }
    if (!(read_byte(p,0x80fe)&32)) {
        if (fx_replay_count(p,&count)) return FX_SOLVE_UI_RESOURCE_LIMIT;
        if (count) write_byte(p,0x8129,1);
    }
    return FX_SOLVE_UI_PROMPT;
}

static fx_solve_outer_status present_equation(fx_platform *p, fx_solve_outer *s)
{
    fx_render render={p->rom,p->rom_size,p->ram};
    int editing=read_byte(p,0x80fe)==1;
    if (s->ui.context.special_view && !editing) {
        fx_solve_ui_status status=present_prompt(p);
        return status<0 ? (fx_solve_outer_status)status : FX_SOLVE_OUTER_COMPLETE;
    }
    write_byte(p,0x8126,(uint8_t)editing);
    if (!editing) write_byte(p,0x8114,0);
    if (fx_editor_has_natural_input(p)) {
        uint8_t modifiers=read_byte(p,0x80f8);
        if (modifiers&128) write_byte(p,0x80f8,(uint8_t)((modifiers+128)&~8u));
        if (!fx_render_viewport(&render,NULL)) return FX_SOLVE_OUTER_UNIMPLEMENTED;
    } else if (fx_input_draw_linear_expression(p)) return FX_SOLVE_OUTER_UNIMPLEMENTED;
    if (!editing) {
        int displayed=read_byte(p,0x80ff)&16 ?
            fx_display_pair_result(&render,0x8140,NULL) :
            fx_display_complex_result(&render,0x8140,NULL);
        if (displayed!=1)
            return FX_SOLVE_OUTER_UNIMPLEMENTED;
    }
    if (!(read_byte(p,0x80fe)&32)) {
        uint8_t count;
        if (fx_replay_count(p,&count)) return FX_SOLVE_OUTER_RESOURCE_LIMIT;
        if (count) write_byte(p,0x8129,1);
    }
    return FX_SOLVE_OUTER_COMPLETE;
}

/* DCA4 delegation1DE1E differs from the main routing policy1DDE4. */
static int special_delegates(fx_platform *p, uint8_t token)
{
    int decoded=read_byte(p,0x80f7)!=0;
    return (decoded && (token==0xf1 || (token>=0xf6 && token<=0xfb) ||
        (token>=0xe0 && token<=0xe3) || (token>=23 && token<=31))) ||
        token==0xe5 || token==0xee || token==0xef || token==0xfe;
}

fx_solve_outer_status fx_solve_outer_load_variable(fx_platform *p, uint8_t id,
                                                  uint16_t destination)
{
    if (!p || !p->ram || id>=10 || destination<0x8000 || destination>0xffec)
        return FX_SOLVE_OUTER_INVALID;
    int exact=fx_exact_output_allowed(p->ram);
    for (unsigned part=0;part<2;++part) {
        fx_number value={{0}};
        if (!part || read_byte(p,0x80f9)==0xc4) {
            uint16_t base=(uint16_t)((part?0x8408:0x8226)+10*id);
            for (unsigned n=0;n<10;++n) value.bytes[n]=read_byte(p,(uint16_t)(base+n));
            if (!exact && fx_number_kind(&value)==FX_NUMBER_SURD &&
                fx_number_to_decimal(&value,&value)!=FX_NUMERIC_OK)
                return FX_SOLVE_OUTER_UNIMPLEMENTED;
        }
        for (unsigned n=0;n<10;++n)
            write_byte(p,(uint16_t)(destination+10*part+n),value.bytes[n]);
    }
    return FX_SOLVE_OUTER_COMPLETE;
}

static fx_solve_outer_status calc_prompt(fx_platform *p, fx_solve_outer *s, uint8_t id)
{
    if (id>=10 || id==1) return FX_SOLVE_OUTER_INVALID;
    if (fx_solve_outer_load_variable(p,id,0x8140)<0) return FX_SOLVE_OUTER_UNIMPLEMENTED;
    fx_render render={p->rom,p->rom_size,p->ram};fx_clear_framebuffer(&render);
    write_byte(p,0x8154,read_byte(p,(uint16_t)(0x1056+id)));
    write_byte(p,0x8155,'?');write_byte(p,0x8156,0);
    write_byte(p,0x811f,10);write_byte(p,0x80fe,4);
    if (fx_ui_controller_begin(p,&s->ui,1,&s->cancellation)!=FX_UI_PREPARED)
        return FX_SOLVE_OUTER_UNIMPLEMENTED;
    if (present_prompt(p)<0) return FX_SOLVE_OUTER_UNIMPLEMENTED;
    s->handler_action=1;s->context_return=1;
    return FX_SOLVE_OUTER_COMPLETE;
}

static fx_solve_outer_status input_completion(fx_platform *p, fx_solve_outer *s,
                                             fx_input_status status)
{
    if (status<0) return (fx_solve_outer_status)status;
    if (status==FX_INPUT_WAIT) { s->pending_owner=2; return FX_SOLVE_OUTER_WAIT; }
    if (status==FX_INPUT_EXPORT) return FX_SOLVE_OUTER_EXPORT;
    if (status==FX_INPUT_RESET) return FX_SOLVE_OUTER_RESET;
    if (status!=FX_INPUT_COMPLETE) return FX_SOLVE_OUTER_UNIMPLEMENTED;
    s->pending_owner=0;
    s->handler_action=s->ui.input.handler_action;
    s->ui.context=s->ui.input.context;s->context_return=s->ui.context.return_value;
    if (fx_input_controller_finish(&s->ui.input,NULL)!=FX_INPUT_COMPLETE)
        return FX_SOLVE_OUTER_INVALID;
    return s->handler_action ? present_equation(p,s) : FX_SOLVE_OUTER_COMPLETE;
}

static fx_solve_outer_status calc_evaluate(fx_platform *p, fx_solve_outer *s)
{
    fx_input_status status=fx_input_controller_begin(p,&s->ui.input,&s->ui.context,
                                                    &s->cancellation);
    if (status==FX_INPUT_PREPARED) {
        s->pending_owner=2;
        status=fx_input_controller_tick(p,&s->ui.input);
    }
    return input_completion(p,s,status);
}

/* The prepared CALC editor uses the same public editor primitives as D9EE;
 * coefficient delimiters and C4's raw forbidden-token table are admitted
 * before inserting data. Menu/result-format requests remain explicit. */
static fx_solve_outer_status calc_input(fx_platform *p, fx_solve_outer *s, uint8_t refresh)
{
    if (fx_ui_controller_begin(p,&s->ui,refresh,&s->cancellation)!=FX_UI_PREPARED)
        return FX_SOLVE_OUTER_UNIMPLEMENTED;
    s->handler_action=0;s->context_return=s->ui.context.return_value;
    if (refresh) return present_equation(p,s);
    uint8_t token=read_byte(p,0x80f5),item=read_byte(p,0x80fd);
    if (token==0xf0 || token==0xed) return calc_evaluate(p,s);
    if (item!=2) {
        for (unsigned n=0;n<8;++n) {
            fx_ui_status status=fx_ui_controller_tick(p,&s->ui);
            if (status==FX_UI_PREPARED) continue;
            if (status==FX_UI_WAIT) { s->pending_owner=2; return FX_SOLVE_OUTER_WAIT; }
            if (status==FX_UI_RESET) return FX_SOLVE_OUTER_RESET;
            if (status==FX_UI_EXPORT) return FX_SOLVE_OUTER_EXPORT;
            if (status==FX_UI_HANDLER_REQUEST && s->ui.request==FX_UI_REQUEST_SPECIAL_CONTEXT) {
                s->handler_action=s->ui.handler_action;s->context_return=s->ui.context.return_value;
                return present_equation(p,s);
            }
            if (status==FX_UI_COMPLETE) {
                s->handler_action=s->ui.handler_action;s->context_return=s->ui.context.return_value;
                return FX_SOLVE_OUTER_COMPLETE;
            }
            return status<0 ? (fx_solve_outer_status)status : FX_SOLVE_OUTER_UNIMPLEMENTED;
        }
        return FX_SOLVE_OUTER_UNIMPLEMENTED;
    }
    if (token==':' || token=='=' || token==0xa4) {
        write_byte(p,0x80f5,0);return FX_SOLVE_OUTER_COMPLETE;
    }
    int edited;
    if (fx_key_is_data_token(p,token)) {
        if (read_byte(p,0x80fe)&64) return FX_SOLVE_OUTER_COMPLETE;
        if (read_byte(p,0x80f9)==0xc4) {
            for (uint16_t a=0x1077;a<0x1081;++a) {
                uint8_t forbidden=read_byte(p,a);if (!forbidden) break;
                if (forbidden==token) { write_byte(p,0x80f5,0);return FX_SOLVE_OUTER_COMPLETE; }
            }
        }
        if (read_byte(p,0x80fe)!=1 && fx_boot_initialize_editor(p,0)!=FX_BOOT_READY)
            return FX_SOLVE_OUTER_UNIMPLEMENTED;
        edited=fx_editor_insert_byte(p,token);
    } else if ((token>=0xe0 && token<=0xe3) || token==0xfe) {
        if (read_byte(p,0x80fe)!=1) return FX_SOLVE_OUTER_COMPLETE;
        edited=fx_editor_text_action(p,token);
    } else return FX_SOLVE_OUTER_UNIMPLEMENTED;
    if (edited<0) return FX_SOLVE_OUTER_RESOURCE_LIMIT;
    write_byte(p,0x8126,1);
    if (fx_input_draw_linear_expression(p)) return FX_SOLVE_OUTER_UNIMPLEMENTED;
    s->handler_action=1;return FX_SOLVE_OUTER_COMPLETE;
}

static fx_solve_outer_status calc_screen(fx_platform *p, fx_solve_outer *s)
{
    uint8_t token=read_byte(p,0x80f5);
    s->handler_action=1;s->context_return=1;
    if (!token) return FX_SOLVE_OUTER_COMPLETE;
    if (special_delegates(p,token)) return calc_input(p,s,0);
    if ((token==0xf0 || token==0xed) && read_byte(p,0x80fe)==4) {
        write_byte(p,0x83fd,(uint8_t)(read_byte(p,0x83fd)+1));
        fx_result_clear_display_state(p);
    }
    uint8_t item=read_byte(p,0x80fd);
    if (item==1) {
        uint16_t source;
        write_byte(p,0x812c,0x54);write_byte(p,0x812d,0x81);
        int ready=fx_input_prepare_exported(p,&source);
        if (ready<0) return FX_SOLVE_OUTER_RESOURCE_LIMIT;
        if (!ready) {
            write_byte(p,0x80fe,128);
            if (fx_error_event_begin(p,&s->scanner_error,2)<0)
                return FX_SOLVE_OUTER_UNIMPLEMENTED;
            s->scanner_error_pending=1;
            return FX_SOLVE_OUTER_WAIT;
        }
        int scan=fx_calc_scan_variables(p);
        if (scan<0) return scan==-3?FX_SOLVE_OUTER_RESOURCE_LIMIT:FX_SOLVE_OUTER_UNIMPLEMENTED;
        if (read_byte(p,0x83fe)==255) {
            write_byte(p,0x80fc,1);write_byte(p,0x80fd,0);
            /* D652 preserves the equation and selects ordinary editing;
             * DCB6 then chooses the synthetic ED/F0 token. */
            write_byte(p,0x80fe,1);write_byte(p,0x80ff,0);
            write_byte(p,0x80f5,fx_exact_output_allowed(p->ram)?0xf0:0xed);
            write_byte(p,0x80f7,1);
            s->handler_action=s->context_return=0;
            return FX_SOLVE_OUTER_COMPLETE;
        }
        item=16;
    }
    if (item==16 || item==32) {
        write_byte(p,0x80fd,2);write_byte(p,0x83fd,0);
        if (fx_boot_initialize_editor(p,1)!=FX_BOOT_READY)
            return FX_SOLVE_OUTER_UNIMPLEMENTED;
        write_byte(p,0x80fe,4);item=2;
    }
    if (item==2) {
        uint8_t index=read_byte(p,0x83fd);
        if (index>=10) return FX_SOLVE_OUTER_RESOURCE_LIMIT;
        uint8_t id=read_byte(p,(uint16_t)(0x83fe + index));
        if (id!=255) return calc_prompt(p,s,id);
        write_byte(p,0x80fd,3);s->handler_action=s->context_return=0;
        return FX_SOLVE_OUTER_COMPLETE;
    }
    if (item==3) return fx_solve_outer_restore(p,s);
    return FX_SOLVE_OUTER_UNIMPLEMENTED;
}

static fx_solve_outer_status input(fx_platform *p, fx_solve_outer *s, uint8_t refresh)
{
    fx_solve_ui_status status;
    uint8_t token, item;
    if (fx_ui_controller_begin(p,&s->ui,refresh,&s->cancellation)!=FX_UI_PREPARED)
        return FX_SOLVE_OUTER_UNIMPLEMENTED;
    s->context_return=s->ui.context.return_value; s->handler_action=0;
    if (refresh) return present_equation(p,s);
    token=read_byte(p,0x80f5); item=read_byte(p,0x80fd);
    if (item==2) {
        if (token==0xf0 || token==0xed) {
            status=fx_solve_controller_accept(p,&s->solve);
            /* The frozen typed-EXE API suppliesF0; outer retains the actual
             * prepared ED/F0 command after an accepted coefficient. */
            write_byte(p,0x80f5,token);
            if (status<0) return (fx_solve_outer_status)status;
            if (status==FX_SOLVE_UI_ERROR) {
                s->pending_owner=1;
                status=fx_solve_controller_tick(p,&s->solve);
                return status<0 ? (fx_solve_outer_status)status : FX_SOLVE_OUTER_WAIT;
            }
            s->handler_action=s->solve.handler_action;
            s->context_return=0;
            return FX_SOLVE_OUTER_COMPLETE;
        }
        /* Native delete is inactive on an unchanged coefficient prompt. */
        if (token==0xfe && read_byte(p,0x80fe)!=1) return FX_SOLVE_OUTER_COMPLETE;
        status=fx_solve_controller_edit(p,&s->solve,token);
        if (status<0) return (fx_solve_outer_status)status;
        s->handler_action=(uint8_t)(read_byte(p,0x80fe)==1);
        return FX_SOLVE_OUTER_COMPLETE;
    }
    if (item==4 && (token==0xf0 || token==0xed)) {
        status=fx_solve_controller_prepare(p,&s->solve,s->expression,
            s->expression_userdata,&s->cancellation);
        if (status<0) return (fx_solve_outer_status)status;
        if (status!=FX_SOLVE_UI_PREPARED) return FX_SOLVE_OUTER_UNIMPLEMENTED;
        status=fx_solve_controller_tick(p,&s->solve);
        if (status<0) return (fx_solve_outer_status)status;
        if (status==FX_SOLVE_UI_ERROR) {
                s->pending_owner=1;
                status=fx_solve_controller_tick(p,&s->solve);
                return status<0 ? (fx_solve_outer_status)status : FX_SOLVE_OUTER_WAIT;
            }
        if (status!=FX_SOLVE_UI_COMPLETE) return FX_SOLVE_OUTER_UNIMPLEMENTED;
        if (fx_solve_controller_finish(&s->solve,&s->handler_action)!=FX_SOLVE_UI_COMPLETE)
            return FX_SOLVE_OUTER_INVALID;
        s->context_return=s->solve.context.return_value;
        return present_equation(p,s);
    }
    if (item==32 && token>=0xe0 && token<=0xe3) {
        if (token<=0xe1) {
            uint8_t count;
            if (fx_replay_count(p,&count)) return FX_SOLVE_OUTER_RESOURCE_LIMIT;
            return count ? FX_SOLVE_OUTER_UNIMPLEMENTED : FX_SOLVE_OUTER_COMPLETE;
        }
        fx_error_context context={s->ui.context.display_address,
                                  s->ui.context.calculation_mode};
        int restored=fx_error_cursor_restore(p,&context);
        if (restored<0) return FX_SOLVE_OUTER_UNIMPLEMENTED;
        if (restored!=1) return FX_SOLVE_OUTER_UNIMPLEMENTED;
        s->handler_action=1;
        return present_equation(p,s);
    }
    return FX_SOLVE_OUTER_UNIMPLEMENTED;
}

fx_solve_outer_status fx_solve_outer_dispatch(fx_platform *p,
    fx_solve_outer *s, fx_main_request request, uint8_t refresh_only)
{
    fx_solve_ui_status status;
    uint8_t token;
    if (!p || !p->ram || !s || !s->active) return FX_SOLVE_OUTER_INVALID;
    if (request!=FX_MAIN_INPUT && request!=FX_MAIN_SCREEN_A0_C0)
        return FX_SOLVE_OUTER_UNIMPLEMENTED;
    if (s->scanner_error_pending) {
        fx_key_controller_status event=fx_error_event_tick_export_boundary(p,&s->scanner_error);
        if (event==FX_KEY_CONTROLLER_WAIT) return FX_SOLVE_OUTER_WAIT;
        if (event==FX_KEY_CONTROLLER_EXPORT) return FX_SOLVE_OUTER_EXPORT;
        if (event==FX_KEY_CONTROLLER_RESET) return FX_SOLVE_OUTER_RESET;
        if (event<0) return FX_SOLVE_OUTER_UNIMPLEMENTED;
        uint8_t acknowledged;
        (void)fx_error_event_finish(&s->scanner_error,&acknowledged);
        write_byte(p,0x80f5,acknowledged);write_byte(p,0x80f7,1);
        fx_render render={p->rom,p->rom_size,p->ram};fx_clear_framebuffer(&render);
        write_byte(p,0x80fc,1);s->handler_action=s->context_return=0;
        s->scanner_error_pending=0;return FX_SOLVE_OUTER_COMPLETE;
    }
    if (s->pending_owner==2)
        return input_completion(p,s,fx_input_controller_tick(p,&s->ui.input));
    if (s->pending_owner==1 || s->solve.phase==FX_SOLVE_UI_ERROR_PENDING ||
        s->solve.phase==FX_SOLVE_UI_ERROR_WAIT || s->solve.phase==FX_SOLVE_UI_RESET_PENDING ||
        (s->solve.active && s->solve.phase==FX_SOLVE_UI_EVALUATE)) {
        status=fx_solve_controller_tick(p,&s->solve);
        if (status<0) return (fx_solve_outer_status)status;
        if (status==FX_SOLVE_UI_EXPORT) return FX_SOLVE_OUTER_EXPORT;
        if (status==FX_SOLVE_UI_RESET) return FX_SOLVE_OUTER_RESET;
        if (status!=FX_SOLVE_UI_COMPLETE) { s->pending_owner=1; return FX_SOLVE_OUTER_WAIT; }
        s->pending_owner=0;s->handler_action=s->solve.handler_action;
        s->ui.context=s->solve.context;s->context_return=s->solve.context.return_value;
        if (fx_solve_controller_finish(&s->solve,NULL)!=FX_SOLVE_UI_COMPLETE)
            return FX_SOLVE_OUTER_INVALID;
        return s->handler_action ? present_equation(p,s) : FX_SOLVE_OUTER_COMPLETE;
    }
    if (read_byte(p,0x80fc)==0xa0)
        return request==FX_MAIN_INPUT ? calc_input(p,s,refresh_only) : calc_screen(p,s);
    if (read_byte(p,0x80fc)==1 && request==FX_MAIN_INPUT)
        return calc_input(p,s,refresh_only);
    if (read_byte(p,0x80fc)!=0xc0 || read_byte(p,0x80f9)!=0xc1)
        return FX_SOLVE_OUTER_UNIMPLEMENTED;
    if (!s->solve.active || s->solve.phase==FX_SOLVE_UI_DONE) {
        fx_solve_outer_status adopted=fx_solve_outer_adopt(p,s);
        if (adopted<0) return adopted;
    }
    if (request==FX_MAIN_INPUT) return input(p,s,refresh_only);
    token=read_byte(p,0x80f5);
    s->handler_action=1; s->context_return=1;
    if (!token) return FX_SOLVE_OUTER_COMPLETE;
    if (special_delegates(p,token)) return input(p,s,0);
    if (read_byte(p,0x80fd)==4) {
        /* DCA4 accepts an unchanged prompt before its item dispatch, even
         * on the automatic cycle which restores the finished equation. */
        if ((token==0xf0 || token==0xed) && read_byte(p,0x80fe)==4) {
            write_byte(p,0x83fd,(uint8_t)(read_byte(p,0x83fd)+1));
            fx_result_clear_display_state(p);
        }
        return fx_solve_outer_restore(p,s);
    }
    status=fx_solve_controller_advance(p,&s->solve);
    if (status<0) return (fx_solve_outer_status)status;
    if (status==FX_SOLVE_UI_ERROR) {
                s->pending_owner=1;
                status=fx_solve_controller_tick(p,&s->solve);
                return status<0 ? (fx_solve_outer_status)status : FX_SOLVE_OUTER_WAIT;
            }
    s->handler_action=s->solve.handler_action;
    s->context_return=s->solve.handler_action;
    return FX_SOLVE_OUTER_COMPLETE;
}
