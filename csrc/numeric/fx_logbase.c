/* Readable real arbitrary-base logarithm for fx-991ES PLUS C.
 * GPL-3.0-or-later. No CPU execution or host floating-point arithmetic. */
#include "fx_logbase.h"
#include "fx_transcend.h"

fx_numeric_status fx_number_log_base(fx_number *out, const fx_number *base,
                                     const fx_number *argument) {
    fx_number logarithm_base, logarithm_argument;
    fx_numeric_status status;
    /*190d0 saves the argument, then190da computes log10(base). After swapping
     * the saved argument back,190e8 computes its logarithm and190f0 divides
     * that value by the saved base logarithm. Both guard words are cleared
     * by the scalar preparation, so division uses the fifteen stored digits
     * returned by these log10 kernels. Using natural logs instead would
     * change finite-precision output even though the identity is equivalent. */
    status = fx_number_log10(&logarithm_base, base);
    if (status != FX_NUMERIC_OK) return status;
    status = fx_number_log10(&logarithm_argument, argument);
    if (status != FX_NUMERIC_OK) return status;
    return fx_decimal_binary(out, &logarithm_argument, &logarithm_base, FX_DIVIDE);
}
