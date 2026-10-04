/* Paired-copy Richardson storage. GPL-3.0-or-later. */
#ifndef FX_C4_DERIVATIVE_STORAGE_H
#define FX_C4_DERIVATIVE_STORAGE_H
#include "fx_derivative_storage.h"
#include "../complex/fx_complex.h"
typedef fx_numeric_status (*fx_c4_derivative_function)(fx_complex *out,const fx_complex *x,void *userdata);
typedef void (*fx_c4_derivative_publish)(const fx_complex *x,void *userdata);
/* Prepared C4 copies transfer the first record before reading its live mate.
 * Arithmetic remains scalar10, so this is not ordinary complex calculus.
 * Arguments/output/status must be outside supplied RAM; an overlap is INVALID.
 * Copies and X publication re-read live80F9 for the second half. A callback
 * that changes mode owns the corresponding evaluator transport policy.
 * Preparation and helper gaps preserve previous RAM writes. The expression
 * adapter owns original argument syntax, cursor consumption, final error
 * publication, physical timer effects and full saved-X restoration. */
fx_numeric_status fx_c4_derivative_point(fx_derivative_storage *storage,const fx_complex *point);
fx_numeric_status fx_c4_derivative_tolerance(fx_derivative_storage *storage,const fx_complex *tolerance,unsigned *native_status);
/* Run the prepared4B94 boundary. The first callback evaluator error keeps
 * its published85B4 F-record code; later symmetric evaluator errors become
 * native3. A protocolERROR callback owns the85B4 evaluator-error publication;
 * its live output pair may retain the earlier value. Without an F publication,
 * an F-valued output supplies the compatibility error code (otherwise3).
 * Native status is independent of the
 * live paired callback/result record. Host failures do not commit out/status.
 * Publish is optional; RAM8276/8458 always receives the live X pair first. */
fx_numeric_status fx_c4_derivative_run(fx_complex *out,fx_derivative_storage *storage,
 fx_c4_derivative_function function,void *userdata,fx_c4_derivative_publish publish,
 const fx_calculus_control *control,unsigned *native_status);
#endif
