/* Native finite-order REF/RREF numerical stages. GPL-3.0-or-later. */
#ifndef FX_LINALG_REDUCE_H
#define FX_LINALG_REDUCE_H
#include "fx_linalg.h"
/* Prepared matrix references and canonical fixed backing; reduced selects
 * REF0 or RREF1. Context/cancellation contract matches the core kernels. */
fx_numeric_status fx_linalg_echelon(fx_linalg_result *out,
                                    const fx_linalg_value *input,
                                    int reduced,
                                    const fx_linalg_context *context);
#endif
