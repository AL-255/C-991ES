/* Handwritten prepared SOLVE parser/numerical bridge. GPL-3.0-or-later. */
#include "fx_solve_expression.h"
#include <string.h>

fx_numeric_status fx_solve_expression_init(fx_solve_expression *expression,
    const uint8_t *input, size_t length, uint8_t selected_id,
    const fx_eval_options *options, const fx_eval_environment *environment,
    const fx_eval_state *state, const fx_calculus_control *control,
    const fx_number *prior_answer)
{
    if (!expression || !input || !length || !state || !state->variables ||
        selected_id >= FX_VARIABLE_COUNT) return FX_NUMERIC_INVALID;
    fx_eval_options prepared = options ? *options : fx_eval_default_options();
    if (prepared.calculation_context != 0xc1) return FX_NUMERIC_UNIMPLEMENTED;
    fx_eval_environment prepared_environment = environment ? *environment : fx_eval_default_environment();
    fx_eval_state prepared_state = *state;
    fx_number saved_answer;
    if (prior_answer) saved_answer = *prior_answer;
    else fx_number_zero(&saved_answer);
    memset(expression, 0, sizeof *expression);
    expression->input = input;
    expression->length = length;
    expression->selected_id = selected_id;
    expression->options = prepared;
    expression->environment = prepared_environment;
    expression->environment.screen = 0xc0;
    expression->state = prepared_state;
    expression->control = control;
    expression->prior_answer = saved_answer;
    return FX_NUMERIC_OK;
}

fx_numeric_status fx_solve_expression_set_storage(fx_solve_expression *expression,
    fx_eval_storage *storage)
{
    if (!expression || !expression->state.variables || !expression->input ||
        !expression->length) return FX_NUMERIC_INVALID;
    if (storage && (!storage->ram || storage->ram_size != 65536u))
        return FX_NUMERIC_INVALID;
    if (storage && storage->ram[0x80f9] != expression->options.calculation_context)
        return FX_NUMERIC_UNIMPLEMENTED;
    expression->storage = storage;
    return FX_NUMERIC_OK;
}

fx_numeric_status fx_solve_expression_evaluate(fx_number sides[2],
    const fx_number *variable, void *userdata)
{
    fx_solve_expression *expression = userdata;
    if (!sides || !variable || !expression || !expression->state.variables ||
        !expression->input || !expression->length ||
        expression->selected_id >= FX_VARIABLE_COUNT) return FX_NUMERIC_INVALID;
    /*1076E publishes the cleaned real trial, before resetting the cursor and
     * entering171F4. The evaluator receives the complete original tokens. */
    expression->state.variables->values[expression->selected_id][0] = *variable;
    fx_number secondary = sides[1];
    fx_eval_status status;
    if (expression->storage)
        status = fx_evaluate_prepared_with_storage(expression->input,
            expression->length, &expression->options, &expression->environment,
            &expression->state, expression->control, &secondary,
            &expression->prior_answer, expression->storage, &expression->effects,
            &expression->last_evaluation);
    else
        status = fx_evaluate_prepared_observed(expression->input,
            expression->length, &expression->options, &expression->environment,
            &expression->state, expression->control, &secondary,
            &expression->prior_answer, &expression->effects,
            &expression->last_evaluation);
    ++expression->evaluations;
    sides[0] = expression->last_evaluation.value[0];
    sides[1] = expression->last_evaluation.value[1];
    expression->environment.restricted_state = expression->effects.restricted_state;
    if (status == FX_EVAL_UNIMPLEMENTED) return FX_NUMERIC_UNIMPLEMENTED;
    if (status < 0) return FX_NUMERIC_UNREPRESENTABLE;
    return (fx_numeric_status)status;
}

fx_numeric_status fx_solve_expression_root(fx_solve_result *out,
    fx_solve_expression *expression)
{
    if (!out || !expression || !expression->state.variables ||
        expression->selected_id >= FX_VARIABLE_COUNT) return FX_NUMERIC_INVALID;
    fx_number initial = expression->state.variables->values[expression->selected_id][0];
    fx_numeric_status status = fx_solve_root(out, &initial,
        fx_solve_expression_evaluate, expression, expression->control);
    if (status == FX_NUMERIC_OK) {
        expression->state.variables->values[expression->selected_id][0] = out->variable;
        if (expression->storage)
            memcpy(expression->storage->ram + 0x8226 + 10 * expression->selected_id,
                out->variable.bytes, 10);
    }
    return status;
}
