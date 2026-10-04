/* SPDX-License-Identifier: GPL-3.0-only; test-only compiled host ABI. */
#include "ui/fx_input_controller.h"
#include "parse/fx_eval_transport.h"
#include <stddef.h>
size_t odd_input_size(void){return sizeof(fx_input_controller);}
unsigned odd_input_field(const fx_input_controller *s,unsigned n){return n==0?s->context.return_value:n==1?s->handler_action:s->evaluator_status;}
size_t odd_input_abi(unsigned n){const size_t a[]={sizeof(fx_platform),offsetof(fx_platform,rom),offsetof(fx_platform,rom_size),offsetof(fx_platform,ram),offsetof(fx_platform,callback_pending),offsetof(fx_platform,status),sizeof(fx_input_context),offsetof(fx_input_context,display_address),offsetof(fx_input_context,result_address),offsetof(fx_input_context,return_value),offsetof(fx_input_context,calculation_mode),offsetof(fx_input_context,saved_math_result),offsetof(fx_input_context,natural_input),offsetof(fx_input_context,natural_result),offsetof(fx_input_context,special_view),sizeof(fx_eval_storage),sizeof(fx_eval_source),sizeof(fx_eval_result)};return n<sizeof a/sizeof*a?a[n]:(size_t)-1;}

int odd_result_begin(fx_platform *p, void *state, uint16_t address,
                     uint8_t mode, uint8_t math)
{
    fx_input_context context={0x8154,address,1,mode,0,0,math,0};
    return fx_input_controller_begin(p,state,&context,NULL);
}
int odd_result_prepared(fx_platform *p,uint16_t address,size_t length,
                        uint16_t *cursor)
{
    fx_eval_storage storage={p->ram,65536,p->rom,p->rom_size};
    fx_eval_source source={0x8154,address,NULL,NULL};
    fx_eval_effects effects; fx_eval_result result;
    *cursor=0x8154;
    return fx_evaluate_prepared_source(length,NULL,NULL,NULL,NULL,NULL,
                                      &storage,&source,cursor,&effects,&result);
}
