/* Compiled host ABI closure for the whole-expression derivative proof. */
#include <stddef.h>
#include "parse/fx_eval_transport.h"
#include "parse/fx_eval_storage.h"
#include "complex/fx_complex.h"
size_t eval_c4_derivative_abi(unsigned index) {
 const size_t fields[]={sizeof(fx_number),offsetof(fx_number,bytes),
 sizeof(((fx_number*)0)->bytes),sizeof(fx_complex),offsetof(fx_complex,real),
 offsetof(fx_complex,imaginary),sizeof(fx_eval_transport),
 offsetof(fx_eval_transport,input_address),offsetof(fx_eval_transport,cursor_address),
 offsetof(fx_eval_transport,output_address),offsetof(fx_eval_transport,before_sample),
 offsetof(fx_eval_transport,userdata),sizeof(fx_eval_storage),offsetof(fx_eval_storage,ram),
 offsetof(fx_eval_storage,ram_size),offsetof(fx_eval_storage,rom),offsetof(fx_eval_storage,rom_size),
 sizeof(fx_eval_result),offsetof(fx_eval_result,value),sizeof(((fx_eval_result*)0)->value),
 offsetof(fx_eval_result,consumed),offsetof(fx_eval_result,unsupported_token),
 sizeof(fx_eval_effects),offsetof(fx_eval_effects,equation_used),offsetof(fx_eval_effects,restricted_state),
 sizeof(fx_calculus_control),offsetof(fx_calculus_control,cancelled),offsetof(fx_calculus_control,userdata),
 sizeof(fx_eval_options),offsetof(fx_eval_options,calculation_context),
 offsetof(fx_eval_options,math_output),offsetof(fx_eval_options,angle_unit)};
 return index<sizeof fields/sizeof fields[0]?fields[index]:0;
}
