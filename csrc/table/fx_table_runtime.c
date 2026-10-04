/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_table_runtime.h"
#include "../parse/fx_eval_table.h"
#include <string.h>

static void load_record(fx_number *n,const uint8_t *ram,uint16_t source)
{
    for(unsigned i=0;i<10;i++)n->bytes[i]=ram[(uint16_t)(source+i)];
}

typedef struct {
    fx_platform *platform;
    fx_table_poll poll;
    void *userdata;
    unsigned evaluator_calls;
} table_body;

/* Bound the prepared contiguous live source without taking a token snapshot.
 * Wrapped ROM/CPU addresses remain an explicit architectural boundary. */
static int expression_length(size_t *length,const uint8_t *ram,
    uint16_t source,int colon_terminates)
{
    if(source<0x8000)return -2;
    for(size_t n=0;n<1024 && n<65536u-source;n++){
        uint8_t b=ram[source+n];
        if(!b || (colon_terminates && b==':')){*length=n+1;return 0;}
    }
    return -3;
}

static int evaluate_row(void *userdata,uint8_t *ram,uint8_t mode,
    uint8_t continuation,uint16_t *source,fx_number *output)
{
    table_body *body=userdata;size_t length;
    if(mode!=0x88||continuation!=1)return -2;
    int admission=expression_length(&length,ram,*source,0);
    if(admission)return admission;
    fx_eval_storage storage={ram,65536u,body->platform->rom,body->platform->rom_size};
    fx_eval_effects effects;fx_eval_result result;
    int status=fx_evaluate_table_expression(ram+*source,length,&storage,&effects,&result);
    ++body->evaluator_calls;
    if(status<0)return status;
    *source=(uint16_t)(*source+result.consumed);
    *output=result.value[0];return status;
}

static int poll_row(void *userdata,uint8_t *ram)
{
    table_body *body=userdata;
    return body->poll ? body->poll(body->userdata,ram) : 0;
}

fx_table_controller_status fx_table_execute_request(
    fx_platform *p,fx_table_controller *state,fx_table_poll poll,
    void *userdata,fx_table_execution *execution)
{
    if(!p||!p->ram||!state||!execution||!state->active||
        (state->request!=FX_TABLE_REQUEST_GENERATION &&
         state->request!=FX_TABLE_REQUEST_PARAMETER_EVALUATION))return FX_TABLE_CONTROLLER_INVALID;
    memset(execution,0,sizeof *execution);
    uint16_t source=state->current_source;int status;
    if(state->request==FX_TABLE_REQUEST_GENERATION){
        table_body body={p,poll,userdata,0};
        fx_table_control control={evaluate_row,poll_row,&body};fx_table_result result;
        status=fx_table_generate_source(p->ram,&source,&control,&result);
        execution->evaluator_calls=body.evaluator_calls;
    }else{
        size_t length;fx_number prior;
        int admission=expression_length(&length,p->ram,source,1);
        if(admission)return admission==-3 ? FX_TABLE_CONTROLLER_RESOURCE_LIMIT : FX_TABLE_CONTROLLER_UNIMPLEMENTED;
        load_record(&prior,p->ram,0x828a);
        fx_eval_storage storage={p->ram,65536u,p->rom,p->rom_size};fx_eval_result result;
        fx_eval_source transport={source,state->context.result_address,NULL,NULL};
        status=fx_evaluate_table_parameter_source(length,&storage,
            &transport,&source,&prior,&result);
        p->ram[0x8124]&=254;
        execution->evaluator_calls=1;

    }
    execution->body_status=status;execution->returned_source=source;
    return fx_table_controller_accept_execution(p,state,status,source);
}
