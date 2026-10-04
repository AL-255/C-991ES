/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_C4_INTEGRAL_STORAGE_H
#define FX_C4_INTEGRAL_STORAGE_H
#include "fx_integral_storage.h"
#include "../complex/fx_complex.h"
typedef fx_numeric_status (*fx_c4_integral_function)(fx_complex *value,const fx_complex *x,void *userdata);
typedef void (*fx_c4_integral_publish)(const fx_complex *x,void *userdata);
/* Prepared original C4 copy mode. Fixed arithmetic remains scalar; each
 * 169C0/169F4/16A0A transfer commits real before reading its live companion.
 * This is not ordinary complex quadrature. Named values and outputs occupy
 * separate host objects outside RAM. Native CPU-local overflow at04696 is
 * an explicit architectural boundary after preceding RAM/callback effects. */
fx_numeric_status fx_c4_integral_lower(fx_integral_storage *storage,const fx_complex *value);
fx_numeric_status fx_c4_integral_upper(fx_integral_storage *storage,const fx_complex *value);
fx_numeric_status fx_c4_integral_tolerance(fx_integral_storage *storage,const fx_complex *value,uint16_t final_cursor,unsigned *native_status);
fx_numeric_status fx_c4_integral_run(fx_complex *out,fx_integral_storage *storage,fx_c4_integral_function function,void *userdata,fx_c4_integral_publish publish,uint16_t output_address,fx_integral_storage_callback_context callback_context,const fx_calculus_control *control,unsigned *native_status,uint16_t *cursor);
#endif
