/* SPDX-License-Identifier: GPL-3.0-only */
#include "table/fx_table_runtime.h"
#include "parse/fx_eval_table.h"
#include <stddef.h>

/* A verifier may use ctypes only after checking the actual compiled headers. */
size_t table_composition_abi(unsigned field)
{
    switch(field) {
    case 0:return sizeof(fx_platform);
    case 1:return sizeof(fx_table_controller);
    case 2:return sizeof(fx_input_context);
    case 3:return sizeof(fx_table_execution);
    case 4:return sizeof(fx_eval_source);
    case 5:return sizeof(fx_eval_result);
    case 6:return offsetof(fx_table_execution,returned_source);
    case 7:return offsetof(fx_table_execution,evaluator_calls);
    case 8:return offsetof(fx_table_execution,body_status);
    case 9:return offsetof(fx_eval_source,input_address);
    case 10:return offsetof(fx_eval_source,output_address);
    case 11:return offsetof(fx_eval_source,before_sample);
    case 12:return offsetof(fx_eval_source,userdata);
    case 13:return offsetof(fx_table_controller,context);
    case 14:return offsetof(fx_table_controller,error);
    case 15:return offsetof(fx_table_controller,saved_result);
    case 16:return offsetof(fx_table_controller,current_source);
    case 17:return offsetof(fx_table_controller,request);
    case 18:return offsetof(fx_table_controller,phase);
    case 19:return offsetof(fx_input_context,display_address);
    case 20:return offsetof(fx_input_context,result_address);
    case 21:return offsetof(fx_input_context,return_value);
    case 22:return offsetof(fx_input_context,calculation_mode);
    case 23:return offsetof(fx_input_context,special_view);
    default:return (size_t)-1;
    }
}
