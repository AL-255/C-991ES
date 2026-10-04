/* Handwritten SOLVE prompt and commit controller. SPDX-License-Identifier: GPL-3.0-only */
#include "fx_solve_controller.h"
#include "fx_input_prepare.h"
#include "fx_input_recover.h"
#include "fx_input_codec.h"
#include "fx_input_display.h"
#include "fx_editor.h"
#include "../parse/fx_tokens.h"
#include "../platform/fx_persistent.h"
#include "../platform/fx_boot_events.h"
#include "../render/fx_result_special.h"
#include "../render/fx_result_format_state.h"
#include "../format/fx_format.h"
#include "../numeric/fx_raw_fraction_convert.h"
#include <string.h>

typedef struct { fx_platform *platform; fx_solve_controller *state; } solve_callback;
static int cancelled(void *userdata);
static int expression_cancelled(void *userdata);

static uint8_t read_byte(fx_platform *p, uint16_t address)
{ return fx_data_read(p, 0, address); }
static void write_byte(fx_platform *p, uint16_t address, uint8_t value)
{ fx_data_write(p, 0, address, value); }
static void write_word(fx_platform *p, uint16_t address, uint16_t value)
{ write_byte(p,address,(uint8_t)value); write_byte(p,(uint16_t)(address+1),(uint8_t)(value>>8)); }
static void load_pair(fx_platform *p, uint16_t address, fx_number pair[2])
{ unsigned i; for (i=0;i<20;++i) pair[i/10].bytes[i%10]=read_byte(p,(uint16_t)(address+i)); }
static void store_pair(fx_platform *p, uint16_t address, const fx_number pair[2])
{ unsigned i; for (i=0;i<20;++i) write_byte(p,(uint16_t)(address+i),pair[i/10].bytes[i%10]); }
static int copy_string(fx_platform *p, uint16_t to, uint16_t from)
{
    unsigned i;
    for (i=0;i<65536;++i) {
        uint8_t value=read_byte(p,from++);
        write_byte(p,to++,value);
        if (!value) return 0;
    }
    return -1;
}

int fx_solve_scan_variables(fx_platform *p, uint16_t source)
{
    uint8_t list[10], count=0, selected=FX_VARIABLE_X;
    unsigned reads=0, i;
    if (!p || !(read_byte(p,0x80fc)&64)) return FX_SOLVE_UI_INVALID;
    memset(list,255,sizeof list);
    for (i=0;i<10;++i) write_byte(p,(uint16_t)(0x83fe + i),255);
    while (reads++<65536) {
        fx_evaluator_token token=fx_decode_evaluator_token(read_byte(p,source++),read_byte(p,0x80f9));
        if (token.kind==9) {
            token=fx_decode_evaluator_token(read_byte(p,source++),read_byte(p,0x80f9));
            ++reads;
            if (token.kind==5 && token.value!=FX_VARIABLE_ANS && token.value!=10) {
                fx_evaluator_token end=fx_decode_evaluator_token(read_byte(p,source++),read_byte(p,0x80f9));
                ++reads;
                if (end.kind==10) {
                    if (end.value==1) return 2;
                    selected=token.value;
                    break;
                }
                /* A nonterminal suffix is still a variable occurrence to this
                 * scanner. The real parser subsequently checks its syntax. */
                --source;
            } else if (token.kind!=10) continue;
        }
        if (token.kind==10) {
            if (token.value==1) continue;
            break;
        }
        if (token.kind!=5 || token.value==FX_VARIABLE_ANS || token.value>=10) continue;
        for (i=0;i<count;++i) if (list[i]==token.value) break;
        if (i==count) {
            if (count>=9) return FX_SOLVE_UI_RESOURCE_LIMIT;
            list[count]=token.value;
            write_byte(p,(uint16_t)(0x83fe + count),token.value);
            ++count;
        }
    }
    if (reads>65536) return FX_SOLVE_UI_RESOURCE_LIMIT;
    for (i=0;i<count;++i) if (list[i]==selected) break;
    if (i==count) return 12;
    for (;i+1<count;++i) list[i]=list[i+1];
    list[count-1]=selected;
    for (i=0;i<10;++i) write_byte(p,(uint16_t)(0x83fe + i),list[i]);
    write_byte(p,0x83fc,selected);
    return 0;
}

static void initialize(fx_solve_controller *s, fx_solve_expression_callback expression,
                       void *userdata, const fx_calculus_control *control)
{
    memset(s,0,sizeof *s);
    s->active=1; s->handler_action=1;
    s->expression=expression; s->expression_userdata=userdata;
    if (control) s->cancellation=*control;
}

fx_solve_ui_status fx_solve_controller_enter(fx_platform *p,
    fx_solve_controller *s, fx_solve_expression_callback expression, void *userdata,
    const fx_calculus_control *control)
{
    uint8_t screen;
    if (!p || !s) return FX_SOLVE_UI_INVALID;
    screen=read_byte(p,0x80fc);
    if (read_byte(p,0x80f9)!=0xc1 || read_byte(p,0x80fe)&64 ||
        ((screen&128) && read_byte(p,0x80fd)==2) || !read_byte(p,0x8154))
        return FX_SOLVE_UI_DECLINED;
    initialize(s,expression,userdata,control);
    /* DE1C restores an existing special screen's saved formula. E852, in
     * the following DCA4 call, saves the ordinary formula before prompting. */
    if ((screen&128) && copy_string(p,0x8154,0x81b8)) return FX_SOLVE_UI_RESOURCE_LIMIT;
    write_byte(p,0x80fc,0xc0); write_byte(p,0x80fd,1); write_byte(p,0x80fe,4);
    fx_result_clear_display_state(p);
    s->phase=FX_SOLVE_UI_VARIABLES;
    return FX_SOLVE_UI_INPUT;
}

static fx_solve_ui_status draw_prompt(fx_platform *p)
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

static fx_solve_ui_status prompt(fx_platform *p, fx_solve_controller *s, uint8_t id)
{
    fx_number pair[2];
    uint8_t text[16];
    unsigned length=0, i;
    if (id>=FX_VARIABLE_COUNT || id==FX_VARIABLE_ANS) return FX_SOLVE_UI_INVALID;
    s->prompt_id=id;
    for (i=0;i<10;++i) pair[0].bytes[i]=read_byte(p,(uint16_t)(0x8226+10*id+i));
    fx_number_zero(&pair[1]);
    if (fx_number_kind(&pair[0])==FX_NUMBER_SURD &&
        fx_number_to_decimal(&pair[0],&pair[0])!=FX_NUMERIC_OK)
        return FX_SOLVE_UI_UNIMPLEMENTED;
    store_pair(p,0x8140,pair);
    if (id==read_byte(p,0x83fc)) {
        for (i=0;i<sizeof text-2;++i) {
            uint8_t value=read_byte(p,(uint16_t)(0x1916+i));
            if (!value) break;
            text[length++]=value;
        }
    }
    text[length++]=read_byte(p,(uint16_t)(0x1056+id));
    if (id!=read_byte(p,0x83fc)) text[length++]='?';
    text[length]=0;
    { fx_render render={p->rom,p->rom_size,p->ram}; fx_clear_framebuffer(&render); }
    for (i=0;i<=length;++i) write_byte(p,(uint16_t)(0x8154+i),text[i]);
    write_byte(p,0x811f,10); write_byte(p,0x80fe,4);
    s->context=fx_input_context_capture(p,0x8154,0x8140);
    return draw_prompt(p);
}

static fx_solve_ui_status error_pending(fx_platform *p, fx_solve_controller *s,
                                       uint8_t status, int scanner)
{
    (void)p;
    s->evaluator_status=status; s->scanner_error=(uint8_t)scanner;
    s->phase=FX_SOLVE_UI_ERROR_PENDING;
    return FX_SOLVE_UI_ERROR;
}

fx_solve_ui_status fx_solve_controller_advance(fx_platform *p, fx_solve_controller *s)
{
    uint8_t item, key, index, id;
    int ready, status;
    if (!p || !s || !s->active || s->phase!=FX_SOLVE_UI_VARIABLES)
        return FX_SOLVE_UI_INVALID;
    key=read_byte(p,0x80f5); item=read_byte(p,0x80fd);
    s->handler_action=1;
    if (!key) return FX_SOLVE_UI_INPUT;
    if ((key==0xf0 || key==0xed) && read_byte(p,0x80fe)==4) {
        write_byte(p,0x83fd,(uint8_t)(read_byte(p,0x83fd)+1));
        fx_result_clear_display_state(p);
    }
    if (item==1) {
        write_word(p,0x812c,0x8154);
        ready=fx_input_prepare_exported(p,&s->prepared_source);
        if (ready<0) return FX_SOLVE_UI_RESOURCE_LIMIT;
        status=ready ? fx_solve_scan_variables(p,s->prepared_source) : 2;
        if (status<0) return (fx_solve_ui_status)status;
        if (status) return error_pending(p,s,(uint8_t)status,1);
        write_byte(p,0x80fd,2); write_byte(p,0x83fd,0);
        if (fx_boot_initialize_editor(p,1)!=FX_BOOT_READY) return FX_SOLVE_UI_UNIMPLEMENTED;
        write_byte(p,0x80fe,4); item=2;
    } else if (item==16 || item==32) {
        write_byte(p,0x80fd,2); write_byte(p,0x83fd,0);
        if (fx_boot_initialize_editor(p,1)!=FX_BOOT_READY) return FX_SOLVE_UI_UNIMPLEMENTED;
        write_byte(p,0x80fe,4); item=2;
    }
    if (item==2) {
        index=read_byte(p,0x83fd);
        if (index>=10) return FX_SOLVE_UI_RESOURCE_LIMIT;
        id=read_byte(p,(uint16_t)(0x83fe + index));
        if (id!=255) return prompt(p,s,id);
        write_byte(p,0x80fd,4); s->handler_action=0;
        return FX_SOLVE_UI_INPUT;
    }
    if (item==64) {
        write_byte(p,0x80fd,4); s->handler_action=0;
        return FX_SOLVE_UI_INPUT;
    }
    if (item==4) {
        write_byte(p,0x80f5,0xed); write_byte(p,0x80f7,1);
        if (copy_string(p,0x8154,0x81b8)) return FX_SOLVE_UI_RESOURCE_LIMIT;
        write_byte(p,0x80fe,1); s->handler_action=0;
        /* Descriptor capture happens when the next input handler evaluates
         * this restored formula, never by reusing a FD2 prompt descriptor. */
        return fx_solve_controller_prepare(p,s,s->expression,s->expression_userdata,&s->cancellation);
    }
    return FX_SOLVE_UI_UNIMPLEMENTED;
}

static void load_variables(fx_platform *p, fx_solve_controller *s)
{
    unsigned id, i;
    for (id=0;id<FX_VARIABLE_COUNT;++id) for (i=0;i<10;++i) {
        s->variables.values[id][0].bytes[i]=read_byte(p,(uint16_t)(0x8226+10*id+i));
        s->variables.values[id][1].bytes[i]=read_byte(p,(uint16_t)(0x8408+10*id+i));
    }
}
static void commit_variables(fx_platform *p, fx_solve_controller *s)
{
    unsigned id, i;
    for (id=0;id<FX_VARIABLE_COUNT;++id) {
        int changed=0;
        for (i=0;i<10;++i) if (s->variables.values[id][0].bytes[i]!=
            read_byte(p,(uint16_t)(0x8226+10*id+i))) changed=1;
        if (changed) fx_store_variable_records(p,(uint8_t)id,s->variables.values[id]);
    }
}
static fx_eval_status expression_default(const uint8_t *input, size_t length,
    const fx_eval_options *options, const fx_eval_environment *environment,
    fx_eval_variables *variables, const fx_calculus_control *control,
    const fx_number *secondary, const fx_number *prior_answer,
    fx_eval_result *result, fx_solve_expression_effects *effects, void *userdata)
{
    fx_eval_state state={variables,NULL};
    fx_eval_effects observed={0,(uint8_t)(environment->restricted_state&~1u)};
    fx_eval_status status;
    solve_callback *callback=userdata;
    fx_platform *p=callback->platform;
    fx_eval_storage storage={p->ram,65536,p->rom,p->rom_size};
    status=fx_evaluate_prepared_with_storage(input,length,options,environment,
        &state,control,secondary,prior_answer,&storage,&observed,result);
    /* The public observed effect reports equation bit0. The native byte
     * also contains temporary-slot reservation bits and physical copy
     * effects, already committed by the prepared-memory evaluator. */
    effects->equation_used=read_byte(p,0x8125);
    effects->restricted_state=observed.restricted_state;
    return status;
}
static fx_eval_status evaluate_expression(fx_platform *p, fx_solve_controller *s,
                                          fx_eval_result *result)
{
    solve_callback callback={p,s};
    fx_calculus_control control={expression_cancelled,&callback};
    fx_eval_options options={0xc1,read_byte(p,0x8106),read_byte(p,0x8105)};
    fx_eval_environment environment={read_byte(p,0x80fc),read_byte(p,0x80f5),
        read_byte(p,0x810c),read_byte(p,0x8124),read_byte(p,0x8102),
        read_byte(p,0x8103),read_byte(p,0x80fa)};
    fx_number retained[2];
    fx_number prior_answer;
    fx_solve_expression_effects effects={0,(uint8_t)(environment.restricted_state&~1u)};
    fx_solve_expression_callback expression=s->expression ? s->expression : expression_default;
    fx_eval_status status;
    load_pair(p,0x8140,retained);
    { unsigned i; for (i=0;i<10;++i) prior_answer.bytes[i]=read_byte(p,(uint16_t)(0x828a+i)); }
    write_byte(p,0x8125,0);
    memset(result,0,sizeof *result); result->value[1]=retained[1];
    status=expression(s->input,s->input_length,&options,&environment,&s->variables,
                      &control,&retained[1],&prior_answer,result,&effects,
                      s->expression ? s->expression_userdata : &callback);
    write_byte(p,0x8125,effects.equation_used);
    write_byte(p,0x8124,effects.restricted_state);
    s->unsupported_token=result->unsupported_token;
    if (result->consumed<s->input_length)
        s->current_source=(uint16_t)(s->prepared_source+result->consumed);
    else s->current_source=(uint16_t)(s->prepared_source+s->input_length);
    commit_variables(p,s);
    return status;
}
static fx_solve_ui_status read_input(fx_platform *p, fx_solve_controller *s)
{
    size_t i;
    for (i=0;i<sizeof s->input;++i) {
        s->input[i]=read_byte(p,(uint16_t)(s->prepared_source+i));
        if (!s->input[i]) { s->input_length=i+1; return FX_SOLVE_UI_PREPARED; }
    }
    return FX_SOLVE_UI_RESOURCE_LIMIT;
}

fx_solve_ui_status fx_solve_controller_prepare(fx_platform *p,
    fx_solve_controller *s, fx_solve_expression_callback expression, void *userdata,
    const fx_calculus_control *control)
{
    fx_calculus_control saved_control;
    int ready;
    if (!p || !s) return FX_SOLVE_UI_INVALID;
    if (read_byte(p,0x80f9)!=0xc1 || read_byte(p,0x80fc)!=0xc0 ||
        read_byte(p,0x80fd)!=4 || read_byte(p,0x83fc)>=FX_VARIABLE_COUNT)
        return FX_SOLVE_UI_UNIMPLEMENTED;
    if (!read_byte(p,0x8154)) return FX_SOLVE_UI_DECLINED;
    /* control may point into the prior controller during prompt transition. */
    if (control) saved_control=*control;
    initialize(s,expression,userdata,control ? &saved_control : NULL);
    s->context=fx_input_context_capture(p,0x8154,0x8140);
    write_word(p,0x812c,0x8154);
    ready=fx_input_needs_export(p) ? fx_input_prepare_exported(p,&s->prepared_source) :
                                  fx_input_prepare_direct(p,&s->prepared_source);
    if (ready<0) return FX_SOLVE_UI_RESOURCE_LIMIT;
    s->preparation_ok=(uint8_t)ready; s->current_source=s->prepared_source;
    load_pair(p,0x8140,s->saved_result); load_variables(p,s);
    if (read_input(p,s)<0) return FX_SOLVE_UI_RESOURCE_LIMIT;
    s->phase=FX_SOLVE_UI_EVALUATE;
    return FX_SOLVE_UI_PREPARED;
}

fx_solve_ui_status fx_solve_controller_edit(fx_platform *p,
    fx_solve_controller *s, uint8_t token)
{
    int edited;
    if (!p || !s || !s->active || s->phase!=FX_SOLVE_UI_VARIABLES ||
        read_byte(p,0x80fd)!=2) return FX_SOLVE_UI_INVALID;
    write_byte(p,0x80f5,token); write_byte(p,0x811f,10);
    fx_key_normalize_action(p); token=read_byte(p,0x80f5);
    /* The special coefficient view consumes these delimiter keys. */
    if (token==':' || token==0xa4 || token=='=') {
        write_byte(p,0x80f5,0); return FX_SOLVE_UI_INPUT;
    }
    if (fx_key_is_data_token(p,token)) {
        if (read_byte(p,0x80fe)!=1) {
            if (read_byte(p,0x80fe)&64) return FX_SOLVE_UI_DECLINED;
            if (fx_boot_initialize_editor(p,0)!=FX_BOOT_READY) return FX_SOLVE_UI_UNIMPLEMENTED;
        }
        edited=fx_editor_has_natural_input(p) ? fx_editor_insert_construct(p,token) :
                                              fx_editor_insert_byte(p,token);
    } else if (token>=0xe0 && token<=0xe3) {
        /* Direction keys on an unchanged prompt are result-navigation
         * requests. FD2 has no eligible result cursor, so the native handler
         * leaves the expression cursor and busy flag untouched. */
        if (read_byte(p,0x80fe)!=1) return FX_SOLVE_UI_INPUT;
        edited=fx_editor_text_action(p,token);
    } else if (token==0xfe) edited=fx_editor_text_action(p,token);
    else return FX_SOLVE_UI_UNIMPLEMENTED;
    if (edited<0) return FX_SOLVE_UI_RESOURCE_LIMIT;
    if (read_byte(p,0x80fe)==1) {
        write_byte(p,0x8126,1);
        if (fx_input_draw_linear_expression(p)) return FX_SOLVE_UI_UNIMPLEMENTED;
    }
    return FX_SOLVE_UI_INPUT;
}

fx_solve_ui_status fx_solve_controller_accept(fx_platform *p, fx_solve_controller *s)
{
    fx_eval_result result;
    fx_eval_status status;
    uint8_t index, id;
    int ready;
    if (!p || !s || !s->active || s->phase!=FX_SOLVE_UI_VARIABLES ||
        read_byte(p,0x80fd)!=2) return FX_SOLVE_UI_INVALID;
    write_byte(p,0x80f5,0xf0);
    if (read_byte(p,0x80fe)==4) return fx_solve_controller_advance(p,s);
    if (!read_byte(p,0x8154)) { s->handler_action=0; return FX_SOLVE_UI_INPUT; }
    s->context=fx_input_context_capture(p,0x8154,0x8140);
    write_word(p,0x812c,0x8154);
    ready=fx_input_prepare_direct(p,&s->prepared_source);
    if (ready<0) return FX_SOLVE_UI_RESOURCE_LIMIT;
    s->preparation_ok=(uint8_t)ready;
    load_pair(p,0x8140,s->saved_result); load_variables(p,s);
    if (read_input(p,s)<0) return FX_SOLVE_UI_RESOURCE_LIMIT;
    fx_display_port_sleep(p);
    status=evaluate_expression(p,s,&result);
    if (status<0) return status==FX_EVAL_RESOURCE_LIMIT ? FX_SOLVE_UI_RESOURCE_LIMIT : FX_SOLVE_UI_UNIMPLEMENTED;
    s->evaluator_status=(uint8_t)status;
    if (status>0 && status<32) {
        unsigned i;
        for (i=0;i<10;++i) write_byte(p,(uint16_t)(0x8140+i),result.value[0].bytes[i]);
        write_byte(p,0x8114,(uint8_t)(s->current_source-s->prepared_source));
        return error_pending(p,s,(uint8_t)status,0);
    }
    store_pair(p,0x8140,result.value);
    fx_result_clear_flags(p); fx_result_set_format(p,13); write_byte(p,0x80fe,3);
    index=read_byte(p,0x83fd);
    if (index>=10) return FX_SOLVE_UI_RESOURCE_LIMIT;
    id=read_byte(p,(uint16_t)(0x83fe + index));
    if (id>=FX_VARIABLE_COUNT) return FX_SOLVE_UI_INVALID;
    fx_result_clear_display_state(p);
    fx_store_variable_address(p,id,0x8140);
    write_byte(p,0x83fd,(uint8_t)(index+1)); s->handler_action=0;
    return FX_SOLVE_UI_INPUT;
}

static fx_numeric_status evaluate_equation(fx_number sides[2], const fx_number *trial,
                                           void *userdata)
{
    solve_callback *callback=userdata;
    fx_platform *p=callback->platform; fx_solve_controller *s=callback->state;
    fx_eval_result result;
    uint8_t id=read_byte(p,0x83fc);
    fx_eval_status status;
    s->variables.values[id][0]=*trial;
    fx_store_variable_records(p,id,s->variables.values[id]);
    s->current_source=s->prepared_source;
    status=evaluate_expression(p,s,&result);
    sides[0]=result.value[0]; sides[1]=result.value[1];
    return (fx_numeric_status)status;
}
static int cancelled(void *userdata)
{
    solve_callback *callback=userdata;
    fx_host_control_state host;
    fx_solve_controller *s=callback->state;
    int requested;
    (void)fx_host_control_begin(callback->platform,&host);
    requested=s->cancellation.cancelled && s->cancellation.cancelled(s->cancellation.userdata);
    if (!requested) write_byte(callback->platform,0x8e00,0);
    return fx_host_control_finish(callback->platform,&host);
}
static int expression_cancelled(void *userdata)
{
    solve_callback *callback=userdata;
    fx_solve_controller *s=callback->state;
    if (s->expression) {
        /* A custom typed expression callback retains the host-poll adapter.
         * Its calculus implementation need not own platform5550. */
        fx_store_variable_records(callback->platform,FX_VARIABLE_X,
            s->variables.values[FX_VARIABLE_X]);
        return cancelled(userdata);
    }
    /* Default prepared-storage expressions own X publication and5550.
     * The enclosing SOLVE numerical driver keeps its own cancelled wrapper. */
    return s->cancellation.cancelled &&
           s->cancellation.cancelled(s->cancellation.userdata);
}
static fx_solve_ui_status solve(fx_platform *p, fx_solve_controller *s)
{
    solve_callback callback={p,s};
    fx_calculus_control control={cancelled,&callback};
    fx_number pair[2], answer[2];
    uint8_t id=read_byte(p,0x83fc);
    fx_number initial;
    fx_numeric_status status;
    unsigned i;
    if (id>=FX_VARIABLE_COUNT) return FX_SOLVE_UI_INVALID;
    initial=s->variables.values[id][0];
    if (!s->preparation_ok) return error_pending(p,s,2,0);
    fx_display_port_sleep(p);
    status=fx_solve_root(&s->numerical,&s->variables.values[id][0],evaluate_equation,&callback,&control);
    if (status!=FX_NUMERIC_OK) {
        s->variables.values[id][0]=initial;
        fx_store_variable_records(p,id,s->variables.values[id]);
        return FX_SOLVE_UI_UNIMPLEMENTED;
    }
    s->evaluator_status=s->numerical.firmware_status;
    s->variables.values[id][0]=s->numerical.variable;
    fx_store_variable_records(p,id,s->variables.values[id]);
    pair[0]=s->numerical.root; pair[1]=s->numerical.residual; store_pair(p,0x8140,pair);
    if (s->evaluator_status>0 && s->evaluator_status<32) {
        if (s->evaluator_status==1 || s->evaluator_status==10)
            s->current_source=(uint16_t)((s->current_source&0xff00) | (uint8_t)(s->current_source-1));
        if (s->context.natural_input) {
            if (fx_editor_export_input(p,0x8154,s->prepared_source,
                (uint8_t)(s->current_source-s->prepared_source),0)) return FX_SOLVE_UI_RESOURCE_LIMIT;
        } else write_byte(p,0x8114,(uint8_t)(s->current_source-s->prepared_source));
        return error_pending(p,s,s->evaluator_status,0);
    }
    fx_result_clear_flags(p);
    fx_result_set_format(p,read_byte(p,0x80f5)==0xf0 ? 13 : 0);
    write_byte(p,0x80fe,3); write_byte(p,0x80ff,19);
    write_byte(p,0x80fd,s->evaluator_status==36 ? 64 : 32);
    for (i=0;i<10;++i) write_byte(p,(uint16_t)(0x828a+i),read_byte(p,(uint16_t)(0x8230+i)));
    answer[0]=pair[0]; fx_number_zero(&answer[1]); fx_store_ans_records(p,answer);
    s->handler_action=2; s->phase=FX_SOLVE_UI_DONE;
    return FX_SOLVE_UI_COMPLETE;
}

fx_solve_ui_status fx_solve_controller_tick(fx_platform *p, fx_solve_controller *s)
{
    fx_key_controller_status event;
    uint8_t token;
    if (!p || !s || !s->active) return FX_SOLVE_UI_INVALID;
    if (s->phase==FX_SOLVE_UI_EVALUATE) return solve(p,s);
    if (s->phase==FX_SOLVE_UI_DONE) return FX_SOLVE_UI_COMPLETE;
    if (s->phase==FX_SOLVE_UI_RESET_PENDING) return FX_SOLVE_UI_RESET;
    if (s->phase==FX_SOLVE_UI_VARIABLES) return FX_SOLVE_UI_WAIT;
    if (s->phase==FX_SOLVE_UI_ERROR_PENDING) {
        write_byte(p,0x80fe,0x80);
        event=fx_error_event_begin(p,&s->error,s->evaluator_status);
        if (event<0) return FX_SOLVE_UI_UNIMPLEMENTED;
        s->phase=FX_SOLVE_UI_ERROR_WAIT;
        return FX_SOLVE_UI_WAIT;
    }
    if (s->phase!=FX_SOLVE_UI_ERROR_WAIT) return FX_SOLVE_UI_INVALID;
    event=fx_error_event_tick(p,&s->error);
    if (event==FX_KEY_CONTROLLER_WAIT) return FX_SOLVE_UI_WAIT;
    if (event==FX_KEY_CONTROLLER_EXPORT) return FX_SOLVE_UI_EXPORT;
    if (event<0) return FX_SOLVE_UI_UNIMPLEMENTED;
    (void)fx_error_event_finish(&s->error,&token);
    if (event==FX_KEY_CONTROLLER_RESET) {
        s->phase=FX_SOLVE_UI_RESET_PENDING; return FX_SOLVE_UI_RESET;
    }
    write_byte(p,0x80f5,token); write_byte(p,0x80f7,1);
    if (s->scanner_error) {
        fx_render render={p->rom,p->rom_size,p->ram};
        fx_clear_framebuffer(&render); write_byte(p,0x80fc,1);
        s->handler_action=0;
    } else {
        fx_error_context error={0x8154,0xc1};
        int handled;
        fx_result_clear(p);
        if (s->context.saved_math_result) store_pair(p,0x8140,s->saved_result);
        handled=fx_error_cursor_restore(p,&error);
        if (handled<0) return FX_SOLVE_UI_UNIMPLEMENTED;
        if (handled==1) s->handler_action=1;
        else {
            fx_input_recovery_context recovery={0x8154,0x8140,0xc1,
                s->context.saved_math_result,s->context.return_value};
            handled=fx_input_recover_after_error(p,&recovery);
            if (handled<0) return FX_SOLVE_UI_UNIMPLEMENTED;
            s->context.return_value=recovery.return_value;
            s->handler_action=(uint8_t)(handled!=0);
        }
    }
    s->phase=FX_SOLVE_UI_DONE; return FX_SOLVE_UI_COMPLETE;
}

fx_solve_ui_status fx_solve_controller_finish(fx_solve_controller *s, uint8_t *action)
{
    if (!s || !s->active || (s->phase!=FX_SOLVE_UI_DONE && s->phase!=FX_SOLVE_UI_RESET_PENDING))
        return FX_SOLVE_UI_INVALID;
    if (action) *action=s->handler_action;
    s->active=0;
    return s->phase==FX_SOLVE_UI_DONE ? FX_SOLVE_UI_COMPLETE : FX_SOLVE_UI_RESET;
}
