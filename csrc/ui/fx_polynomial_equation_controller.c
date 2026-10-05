/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_polynomial_equation_controller.h"
#include "fx_error_boundary.h"
#include "fx_mode_setup.h"
#include "../numeric/fx_solver_polynomial_stage.h"
#include "../numeric/fx_surd_components.h"
#include "../parse/fx_eval_surd_workspace.h"
#include "../platform/fx_persistent.h"
#include "../platform/fx_result_classify.h"
#include "../render/fx_result_linalg.h"
#include "../render/fx_result_special.h"
#include "../trig/fx_math_context.h"
#include <string.h>

enum { POLYNOMIAL_INPUT=2, POLYNOMIAL_DONE=3,
       POLYNOMIAL_ERROR=4, POLYNOMIAL_RESET=5 };
static uint8_t get(fx_platform *p,uint16_t a)
{ return fx_data_read(p,0,a); }
static void put(fx_platform *p,uint16_t a,uint8_t v)
{ fx_data_write(p,0,a,v); }
static uint16_t word(fx_platform *p,uint16_t a)
{ return (uint16_t)(get(p,a)|(uint16_t)get(p,(uint16_t)(a+1))<<8); }
static void copy(fx_platform *p,uint16_t to,uint16_t from,unsigned count)
{ for(unsigned n=0;n<count;++n)put(p,(uint16_t)(to+n),get(p,(uint16_t)(from+n))); }
static void store(fx_platform *p,uint16_t to,const fx_number *v)
{ for(unsigned n=0;n<10;++n)put(p,(uint16_t)(to+n),v->bytes[n]); }
static void load(fx_platform *p,fx_number *v,uint16_t from)
{ for(unsigned n=0;n<10;++n)v->bytes[n]=get(p,(uint16_t)(from+n)); }
static int domain(fx_platform *p)
{
    return p&&p->ram&&p->rom&&get(p,0x80f9)==0x45&&
        get(p,0x80fa)>=3&&get(p,0x80fa)<=4&&get(p,0x80fc)==21;
}
static int selection_valid(fx_platform *p)
{
    return domain(p)&&get(p,0x811c)>=1&&
        get(p,0x811c)<=(get(p,0x80fa)==4?2:1)&&get(p,0x811d)==1&&
        get(p,0x811e)>=1&&get(p,0x811e)<=3;
}
static uint16_t selected(fx_platform *p)
{
    return word(p,(uint16_t)(0xfde + 18u*get(p,0x811c)+
        6u*get(p,0x811d)+2u*get(p,0x811e)));
}
int fx_polynomial_equation_move_selection(fx_platform *p,uint8_t token)
{
    if(!selection_valid(p))return -1;
    uint8_t page=get(p,0x811c),column=get(p,0x811e);
    int moved=0;
    if(token==0xe2||token==0xed) {
        if(column<3){++column;moved=1;}
        else if(page==1&&get(p,0x80fa)==4){++page;moved=1;}
    } else if(token==0xe3) {
        if(column>1){--column;moved=1;}
        else if(page>1){--page;moved=1;}
    }
    if(moved) {
        put(p,0x811c,page);put(p,0x811e,column);
        fx_result_clear_display_state(p);
    }
    return moved?0:1;
}
int fx_polynomial_equation_commit_coefficient(fx_platform *p,uint16_t source)
{
    if(!selection_valid(p)||source<0x8000||source>65526)return -1;
    uint16_t destination=selected(p);
    if(destination!=0x829e&&destination!=0x82a8&&destination!=0x82b2&&
       !(get(p,0x80fa)==4&&destination==0x82f8))return -1;
    /* D142 reads the first word, then eight bytes at the aligned post-word
     * address, before performing any destination write. */
    fx_number value;
    value.bytes[0]=get(p,source);value.bytes[1]=get(p,(uint16_t)(source+1));
    uint16_t tail=(uint16_t)((source+2u)&0xfffeu);
    for(unsigned n=0;n<8;++n)value.bytes[n+2]=get(p,(uint16_t)(tail+n));
    store(p,destination,&value);
    (void)fx_polynomial_equation_move_selection(p,0xed);
    put(p,0x80fd,1);put(p,0x80fe,3);return 0;
}
static void draw_text(fx_render *r,uint8_t x,uint8_t y,const uint8_t text[6])
{
    for(unsigned n=0;n<6&&text[n]&&x<=92;++n,x=(uint8_t)(x+4))
        fx_draw_glyph(r,x,(int8_t)y,text[n]);
}
static int prepare_compact_format(fx_platform *p,const fx_number *number)
{
    if((number->bytes[0]&0xf0)!=0x80)return 0;
    fx_number decimal;
    return fx_surd_components_convert_copy(p->ram,&decimal,number)==FX_NUMERIC_OK?0:-1;
}
int fx_polynomial_equation_present_coefficients(fx_platform *p)
{
    if(!selection_valid(p))return -1;
    uint8_t kind=get(p,0x80fa),page=get(p,0x811c),column=get(p,0x811e);
    fx_number number;load(p,&number,selected(p));
    fx_number zero;fx_number_zero(&zero);store(p,0x814a,&zero);
    store(p,0x8140,&number);
    if(fx_key_is_menu_token(p,get(p,0x80f5)))return -2;
    fx_render render={p->rom,p->rom_size,p->ram};fx_clear_framebuffer(&render);
    uint8_t caption[6];
    for(unsigned n=0;n<6;++n)caption[n]=get(p,(uint16_t)(0x119b+n));
    caption[2]=(uint8_t)(caption[2]+page-1);put(p,0x811f,6);
    for(unsigned n=0;n<3;++n) {
        draw_text(&render,(uint8_t)(12+28*n),1,caption);++caption[2];
    }
    /* Polynomial grids have no simultaneous-equation row labels. */
    uint16_t a=(uint16_t)(0x102e + 4u*kind);
    fx_draw_vertical(&render,get(p,a),get(p,(uint16_t)(a+1)),
        get(p,(uint16_t)(a+2)),page==1?get(p,(uint16_t)(a+3)):0);
    if(page!=1||kind!=4) {
        a=(uint16_t)(0x103e + 4u*kind);
        fx_draw_vertical(&render,get(p,a),get(p,(uint16_t)(a+1)),
            get(p,(uint16_t)(a+2)),get(p,(uint16_t)(a+3)));
    }
    fx_linalg_value value;memset(&value,0,sizeof value);
    value.rows=1;value.columns=3;
    for(unsigned i=0;i<3;++i)
        load(p,&value.cells[i],word(p,(uint16_t)(0xff8+18u*(page-1)+2u*i)));
    /* Each3EC0 cell snapshots its source, then3500/15C82 reduces a compact
     * value through173FA before the six-character budget. These pool writes
     * precede the next cell and the selected-value line. */
    for(unsigned i=0;i<3;++i) {
        if(prepare_compact_format(p,&value.cells[i])||
           fx_display_linalg_cell(&render,&value.cells[i],1,(uint8_t)(i+1),
               i+1==column)!=1)return -1;
    }
    put(p,0x811f,7);
    /*37BC/C060's ordinary AB8E decimal preparation follows the grid. The
     * prime-selection15 delegate bypasses that preparation. */
    if((get(p,0x8100)&15)!=15&&prepare_compact_format(p,&number))return -1;
    return fx_display_special_real_number(&render,&number,NULL)==1?0:-1;
}

int fx_polynomial_equation_present_root_caption(fx_platform *p)
{
    if(!p||!p->ram||!p->rom||get(p,0x80f9)!=0x45||
       get(p,0x80fc)!=1||get(p,0x80fa)<3||get(p,0x80fa)>4)return -1;
    uint8_t count,index=get(p,0x8113),kind=get(p,0x80fa);
    if(fx_replay_count(p,&count)||!index||(kind==4&&index>count))return -1;
    fx_render render={p->rom,p->rom_size,p->ram};fx_clear_framebuffer(&render);
    uint16_t caption;
    if(kind==3) {
        fx_result_classification classification;
        if(fx_result_classify_address(p,0x829e,0,&classification)!=FX_NUMERIC_OK)
            return -1;
        uint8_t offset=(uint8_t)(index-1),negative=classification.classification==2?2:0;
        if(count==4) {
            if(offset>1)offset=(uint8_t)(offset+negative);
        } else if(!offset)offset=6;
        else offset=(uint8_t)(offset+negative+1);
        /* C236 retains8113 after replay exhaustion. In particular, AC from
         * the negative-leading four-entry quadratic can select the seventh
         * caption (X=) with index5. It does not clamp to the replay count.
         * This host entry bounds the seven original18-byte caption records;
         * raw globals selecting outside that table remain unsupported. */
        if(offset>6)return -1;
        caption=(uint16_t)(0x2e50+18u*offset);
    } else caption=(uint16_t)((count==1?0x1a98:0x1aa1)+
        (count==1?3u:4u)*(index-1u));
    fx_draw_text(&render,0,1,&caption);return 0;
}

static void publish_work(fx_platform *p,const fx_solver_result *state)
{
    put(p,0x80e8,state->coefficient_rows);put(p,0x80e9,state->coefficient_columns);
    put(p,0x80ea,state->root_rows);put(p,0x80eb,state->root_columns);
    for(unsigned i=0;i<9;++i) {
        store(p,(uint16_t)(0x8406+10*i),&state->coefficient_work[i]);
        store(p,(uint16_t)(0x8460+10*i),&state->root_work[i]);
    }
}
typedef struct {
    fx_platform *platform;
    const fx_calculus_control *control;
} polynomial_poll_context;
static int publish_poll(const fx_solver_result *state,
    fx_solver_polynomial_stage stage,void *userdata)
{
    polynomial_poll_context *poll=userdata;fx_platform *p=poll->platform;
    (void)stage;publish_work(p,state);
    put(p,0x8e00,2);fx_timer_start(p,0x129a);
    int cancelled=poll->control&&poll->control->cancelled&&
        poll->control->cancelled(poll->control->userdata);
    if(cancelled){put(p,0x80f2,4);put(p,0x80f3,16);}
    put(p,0x8e00,0);return cancelled;
}
static void sleep_display(fx_platform *p)
{ put(p,0xf031,6);fx_display_port_sleep(p); }
static fx_numeric_status prepare_binary(fx_number *out,const fx_number *a,
    const fx_number *b,fx_binary_op operation,void *userdata)
{
    fx_platform *p=userdata;
    return fx_eval_surd_workspace_binary(out,p->ram,a,b,0,0,operation);
}
static fx_numeric_status prepare_root(fx_number *out,const fx_number *input,
    int exact_math,void *userdata)
{
    fx_platform *p=userdata;
    return fx_eval_surd_workspace_sqrt(out,p->ram,input,exact_math);
}
static fx_numeric_status prepare_decimal(fx_number *out,const fx_number *input,
    void *userdata)
{
    fx_platform *p=userdata;
    return (input->bytes[0]&0xf0)==0x80
        ? fx_surd_components_convert_copy(p->ram,out,input)
        : fx_number_to_decimal(out,input);
}
static fx_numeric_status prepare_classification(uint8_t *out,
    const fx_number *input,void *userdata)
{
    fx_platform *p=userdata;
    if((input->bytes[0]&0xf0)==0x80&&input->bytes[9]&&
       (uint8_t)(input->bytes[8]+input->bytes[9])==7) {
        fx_number converted;
        fx_numeric_status status=fx_surd_components_convert_copy(p->ram,&converted,input);
        if(status!=FX_NUMERIC_OK)return status;
        store(p,0x8640,&converted);
    }
    return fx_scalar_numeric_classify(out,input);
}
static int append_pair(fx_platform *p,const fx_complex *value)
{
    uint8_t classification;
    if(fx_scalar_numeric_classify(&classification,&value->imaginary)!=FX_NUMERIC_OK)
        return -1;
    store(p,0x814a,&value->imaginary);store(p,0x8140,&value->real);
    return fx_replay_append_prepared(p,classification);
}
static int export_roots(fx_platform *p,fx_solver_result *solved)
{
    fx_result_clear_flags(p);
    fx_result_set_format(p,get(p,0x8106)&&!get(p,0x810c)?13:0);
    put(p,0x8154,0);put(p,0x812c,0x54);put(p,0x812d,0x81);put(p,0x8113,0);
    if(!solved->count)return 3;
    /* 1695C chooses polynomial bank5 and retains a full3x3 copy in bank3. */
    copy(p,0x80e6,0x80ea,2);copy(p,0x83ac,0x8460,90);
    for(unsigned n=0;n<270;++n)put(p,(uint16_t)(0x8406+n),0);
    for(unsigned root=0;root<solved->count;++root) {
        fx_complex original,cleaned;uint8_t error;
        uint16_t source=(uint16_t)(0x83ac+30*root);
        /* D12C publishes the raw imaginary record before the real record. */
        copy(p,0x814a,(uint16_t)(source+10),10);copy(p,0x8140,source,10);
        load(p,&original.real,0x8140);load(p,&original.imaginary,0x814a);
        if(fx_complex_cleanup(&cleaned,&original)!=FX_NUMERIC_OK||
           fx_complex_firmware_status(&error,FX_COMPLEX_CLEANUP_RETURN,
               &original,&cleaned)!=FX_NUMERIC_OK)return -1;
        store(p,0x814a,&cleaned.imaginary);store(p,0x8140,&cleaned.real);
        if(error)return error;
        solved->roots[root]=cleaned;
        if(append_pair(p,&cleaned))return -1;
    }
    return 0;
}
static fx_numeric_status vertex_binary(fx_platform *p,fx_number *out,const fx_number *a,
    const fx_number *b,fx_binary_op operation)
{
    if(a->bytes[0]>=0xf0||b->bytes[0]>=0xf0) {
        fx_number_error(out,3);return FX_NUMERIC_OK;
    }
    return prepare_binary(out,a,b,operation,p);
}
static int admit_vertex_coordinate(fx_number *value)
{
    if(fx_decimal_integer_cleanup(value)!=FX_NUMERIC_OK)return -1;
    /* 1CEC0 removes an ordinary record's marker before its return check. */
    if((value->bytes[0]&0xf0)==0x40)value->bytes[0]&=(uint8_t)~0x40;
    return value->bytes[0]>=0xf0?3:0;
}
static int export_vertex(fx_platform *p)
{
    fx_number a,b,c,constant,four_a,b_squared,ratio,x,y;
    sleep_display(p);load(p,&a,0x829e);load(p,&b,0x82a8);load(p,&c,0x82b2);
    if(!fx_exact_output_allowed(p->ram)) {
        fx_number *values[3]={&a,&b,&c};
        for(unsigned i=0;i<3;++i)
            if((values[i]->bytes[0]&0xf0)==0x80&&
               prepare_decimal(values[i],values[i],p)!=FX_NUMERIC_OK)return -1;
    }
    fx_decimal_from_u8(&constant,4);
    if(vertex_binary(p,&four_a,&constant,&a,FX_MULTIPLY)!=FX_NUMERIC_OK||
       vertex_binary(p,&b_squared,&b,&b,FX_MULTIPLY)!=FX_NUMERIC_OK||
       vertex_binary(p,&ratio,&b_squared,&four_a,FX_DIVIDE)!=FX_NUMERIC_OK||
       vertex_binary(p,&y,&c,&ratio,FX_SUBTRACT)!=FX_NUMERIC_OK)return -1;
    int admitted=admit_vertex_coordinate(&y);if(admitted)return admitted;
    fx_decimal_from_u8(&constant,2);
    if(vertex_binary(p,&a,&a,&constant,FX_MULTIPLY)!=FX_NUMERIC_OK||
       vertex_binary(p,&b,&b,&a,FX_DIVIDE)!=FX_NUMERIC_OK||
       fx_number_negate(&x,&b)!=FX_NUMERIC_OK)return -1;
    admitted=admit_vertex_coordinate(&x);if(admitted)return admitted;
    fx_complex value;fx_number_zero(&value.imaginary);value.real=x;
    if(append_pair(p,&value))return -1;
    value.real=y;return append_pair(p,&value);
}
static int solve(fx_platform *p,fx_polynomial_equation_controller *state)
{
    fx_number coefficients[12];memset(coefficients,0,sizeof coefficients);
    uint8_t kind=get(p,0x80fa);
    for(unsigned i=0;i<kind;++i)
        load(p,&coefficients[i],i==3?0x82f8:(uint16_t)(0x829e + 10*i));
    fx_solver_context context={(uint8_t)fx_exact_output_allowed(p->ram),0,0};
    put(p,0x8129,0);sleep_display(p);
    for(unsigned n=0;n<180;++n)put(p,(uint16_t)(0x8406+n),0);
    polynomial_poll_context poll={p,&state->cancellation};
    fx_complex_preparation preparation={prepare_root,prepare_decimal,
        prepare_classification,prepare_binary,p};
    if(fx_solver_solve_polynomial_prepared(&state->numerical,coefficients,
        (fx_solver_kind)kind,&context,publish_poll,&poll,&preparation)!=FX_NUMERIC_OK)return -1;
    publish_work(p,&state->numerical);
    if(state->numerical.firmware_status)return state->numerical.firmware_status;
    int status=export_roots(p,&state->numerical);
    if(!status&&kind==3)status=export_vertex(p);
    if(status)return status;
    put(p,0x80fc,1);put(p,0x80fd,2);state->returned=0;return 0;
}
static fx_ui_status error_status(fx_platform *p,
    fx_polynomial_equation_controller *state,fx_key_controller_status event)
{
    if(event==FX_KEY_CONTROLLER_WAIT)return FX_UI_WAIT;
    if(event==FX_KEY_CONTROLLER_EXPORT)return FX_UI_EXPORT;
    if(event==FX_KEY_CONTROLLER_RESET){state->phase=POLYNOMIAL_RESET;return FX_UI_RESET;}
    if(event!=FX_KEY_CONTROLLER_TOKEN)return FX_UI_UNIMPLEMENTED;
    uint8_t token;
    if(fx_error_event_finish(&state->error,&token)!=FX_KEY_CONTROLLER_TOKEN)
        return FX_UI_INVALID;
    put(p,0x80f5,token);put(p,0x80f7,1);
    state->returned=1;state->phase=POLYNOMIAL_DONE;return FX_UI_COMPLETE;
}
fx_ui_status fx_polynomial_equation_controller_begin(fx_platform *p,
    fx_polynomial_equation_controller *state,const fx_calculus_control *control)
{
    if(!domain(p)||!state)return FX_UI_INVALID;
    uint8_t token=get(p,0x80f5);
    int solving=(token==0xed||token==0xf0)&&!get(p,0x80fd);
    if((solving&&!get(p,0x80f7))||(!solving&&!selection_valid(p)))return FX_UI_INVALID;
    fx_calculus_control saved={0};if(control)saved=*control;
    memset(state,0,sizeof *state);state->cancellation=saved;
    state->active=1;state->returned=1;
    if(solving) {
        int status=solve(p,state);
        if(status==0){state->phase=POLYNOMIAL_DONE;return FX_UI_COMPLETE;}
        if(status!=1&&status!=3)return FX_UI_UNIMPLEMENTED;
        state->phase=POLYNOMIAL_ERROR;
        return error_status(p,state,fx_error_event_begin(p,&state->error,(uint8_t)status));
    }
    put(p,0x8129,0);put(p,0x80fd,0);
    if(fx_key_is_direction_token(p,token)) {
        (void)fx_acquire_busy(p);
        int moved=fx_polynomial_equation_move_selection(p,token);
        if(moved<0)return FX_UI_UNIMPLEMENTED;
        if(moved){fx_clear_busy(p);state->phase=POLYNOMIAL_DONE;return FX_UI_COMPLETE;}
    } else if(token==0xe6) {
        fx_result_clear_flags(p);fx_mode_initialize_equation(p,21);
    }
    int shown=fx_polynomial_equation_present_coefficients(p);
    if(shown==-2) {
        state->phase=POLYNOMIAL_INPUT;
        return fx_ui_controller_begin(p,&state->input,0,&state->cancellation);
    }
    if(shown)return FX_UI_UNIMPLEMENTED;
    state->phase=POLYNOMIAL_DONE;return FX_UI_COMPLETE;
}
fx_ui_status fx_polynomial_equation_controller_tick(fx_platform *p,
    fx_polynomial_equation_controller *state)
{
    if(!p||!state||!state->active)return FX_UI_INVALID;
    if(state->phase==POLYNOMIAL_DONE)return FX_UI_COMPLETE;
    if(state->phase==POLYNOMIAL_RESET)return FX_UI_RESET;
    if(state->phase==POLYNOMIAL_ERROR)
        return error_status(p,state,fx_error_event_tick_export_boundary(p,&state->error));
    if(state->phase!=POLYNOMIAL_INPUT)return FX_UI_UNIMPLEMENTED;
    fx_ui_status status=fx_ui_controller_tick(p,&state->input);
    if(status==FX_UI_COMPLETE) {
        uint8_t returned;
        if(fx_ui_controller_finish(&state->input,&returned)!=FX_UI_COMPLETE)
            return FX_UI_INVALID;
        state->phase=POLYNOMIAL_DONE;
    }
    return status;
}
fx_ui_status fx_polynomial_equation_controller_finish(
    fx_polynomial_equation_controller *state,uint8_t *returned)
{
    if(!state||!state->active||state->phase!=POLYNOMIAL_DONE)return FX_UI_INVALID;
    if(returned)*returned=state->returned;
    state->active=0;return FX_UI_COMPLETE;
}
uint8_t fx_polynomial_equation_controller_export_mask(
    const fx_polynomial_equation_controller *state)
{
    if(!state||!state->active)return 0;
    if(state->phase==POLYNOMIAL_ERROR||state->phase==POLYNOMIAL_RESET)
        return state->error.key.export_mask;
    if(state->phase==POLYNOMIAL_INPUT)
        return state->input.input.error.key.export_mask;
    return 0;
}
