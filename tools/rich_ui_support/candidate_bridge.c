#include "ui/fx_linalg_controller.h"
#include <stddef.h>
size_t candidate_size(unsigned kind)
{
    if (kind==0) return sizeof(fx_input_controller);
    if (kind==1) return sizeof(fx_ui_controller);
    return sizeof(fx_linalg_controller);
}
unsigned candidate_field(const void *p,unsigned kind,unsigned field)
{
    if (kind==0) {
        const fx_input_controller *s=p;
        const unsigned values[]={s->context.return_value,s->handler_action,
            s->evaluator_status,s->phase,s->unsupported_token,
            s->prepared_source,s->current_source};
        return field<sizeof values/sizeof values[0] ? values[field] : 0;
    }
    if (kind==1) {
        const fx_ui_controller *s=p;
        const unsigned values[]={s->context.return_value,s->handler_action,
            s->input.evaluator_status,s->phase,s->request};
        return field<sizeof values/sizeof values[0] ? values[field] : 0;
    }
    const fx_linalg_controller *s=p;
    const unsigned values[]={s->returned,s->slot,s->selected_address,s->phase,
        s->input.request,s->input.context.return_value,s->input.handler_action};
    return field<sizeof values/sizeof values[0] ? values[field] : 0;
}
size_t candidate_abi(unsigned index)
{
    const size_t values[]={sizeof(fx_platform),offsetof(fx_platform,rom),
        offsetof(fx_platform,rom_size),offsetof(fx_platform,ram),
        offsetof(fx_platform,callback_pending),offsetof(fx_platform,status),
        sizeof(fx_input_context),offsetof(fx_input_context,display_address),
        offsetof(fx_input_context,result_address),offsetof(fx_input_context,return_value),
        offsetof(fx_input_context,calculation_mode),offsetof(fx_input_context,saved_math_result),
        offsetof(fx_input_context,natural_input),offsetof(fx_input_context,natural_result),
        offsetof(fx_input_context,special_view),sizeof(fx_calculus_control),
        offsetof(fx_calculus_control,cancelled),offsetof(fx_calculus_control,userdata)};
    return index<sizeof values/sizeof values[0] ? values[index] : 0;
}
