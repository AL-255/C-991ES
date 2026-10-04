/* Prepared stage observation, independent of calculator display/timer IO. */
#ifndef FX_LINALG_STAGE_H
#define FX_LINALG_STAGE_H
#include "fx_linalg.h"
/* Called after incrementing cancellation_checks and before testing cancellation.
 * The state is borrowed and cannot be mutated. A nonzero response cancels.
 * The hook may publish these values to a separate physical device image. */
typedef int (*fx_linalg_stage_callback)(const fx_linalg_result *state,void *userdata);
fx_numeric_status fx_linalg_inverse_observed(fx_linalg_result *out,const fx_linalg_value *input,const fx_linalg_context *context,fx_linalg_stage_callback callback,void *userdata);
fx_numeric_status fx_linalg_multiply_observed(fx_linalg_result *out,const fx_linalg_value *left,const fx_linalg_value *right,const fx_linalg_context *context,fx_linalg_stage_callback callback,void *userdata);
#endif
