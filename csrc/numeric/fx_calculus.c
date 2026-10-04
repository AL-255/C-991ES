/* Real finite sums/products for fx-991ES PLUS C. GPL-3.0-or-later.
 * Handwritten C; no firmware execution or host floating-point arithmetic. */
#include "fx_calculus.h"

/*0429c checks fractional status, then adds packed BCD0xf0 to the exponent.
 * A carry rejects exponent10 or greater: the limit is10^10, not10^16.
 * Signed bounds are accepted. Metadata-marked bounds fail the integer gate. */
static fx_numeric_status integer_bound(int64_t *value, const fx_number *record,
                                       int *valid) {
    fx_number decimal;
    fx_decimal decoded;
    fx_numeric_status status = fx_number_to_decimal(&decimal, record);
    *valid = 0;
    if (status != FX_NUMERIC_OK) return status;
    if (fx_number_kind(&decimal) == FX_NUMBER_ERROR) return FX_NUMERIC_OK;
    if (fx_decimal_decode(&decoded, &decimal) != FX_NUMERIC_OK)
        return FX_NUMERIC_INVALID;
    if (decoded.sign && decoded.mantissa < UINT64_C(100000000000000))
        return FX_NUMERIC_INVALID;
    if (decoded.exponent >= 10 || fx_number_fractional_status(&decimal) ||
        fx_decimal_to_integer(value, &decimal) != FX_NUMERIC_OK)
        return FX_NUMERIC_OK;
    *valid = 1;
    return FX_NUMERIC_OK;
}

static fx_numeric_status finite_series(fx_number *out, const fx_number *lower,
                                       const fx_number *upper,
                                       fx_calculus_function function,
                                       void *userdata,
                                       const fx_calculus_control *control,
                                       int product) {
    fx_number result, x, value;
    int64_t first = 0, last = 0, index;
    int first_valid, last_valid;
    fx_numeric_status status;
    if (!out || !lower || !upper || !function) return FX_NUMERIC_INVALID;
    status = integer_bound(&first, lower, &first_valid);
    if (status != FX_NUMERIC_OK) return status;
    status = integer_bound(&last, upper, &last_valid);
    if (status != FX_NUMERIC_OK) return status;
    if (!first_valid || !last_valid || first > last) {
        fx_number_error(out, 8);
        return FX_NUMERIC_OK;
    }
    (void)fx_decimal_from_integer(&result, product ? 1 : 0);
    /*04330/04426 installs X before the cancellation poll. The expression is
     * then reparsed in ascending order, including both endpoints. Keeping
     * this order and cleaning every intermediate result reproduces the
     * original fifteen-digit rounding and early overflow behavior. */
    for (index = first; ; ++index) {
        (void)fx_decimal_from_integer(&x, index);
        if (control && control->cancelled &&
            control->cancelled(control->userdata)) {
            fx_number_error(out, 1);
            return FX_NUMERIC_OK;
        }
        status = function(&value, &x, userdata);
        if (status != FX_NUMERIC_OK) return status;
        if (fx_number_kind(&value) == FX_NUMBER_ERROR) {
            *out = value;
            return FX_NUMERIC_OK;
        }
        /*171ea disables natural radicals while evaluating the callback.
         * This also models an exact radical supplied by a host callback. */
        if (fx_number_kind(&value) == FX_NUMBER_SURD) {
            status = fx_number_to_decimal(&value, &value);
            if (status != FX_NUMERIC_OK) return status;
        }
        status = fx_number_binary(&result, &result, &value,
                                  product ? FX_MULTIPLY : FX_ADD);
        if (status != FX_NUMERIC_OK) return status;
        if (fx_number_kind(&result) == FX_NUMBER_ERROR) {
            *out = result;
            return FX_NUMERIC_OK;
        }
        status = fx_decimal_integer_cleanup(&result);
        if (status != FX_NUMERIC_OK) return status;
        if (fx_number_kind(&result) == FX_NUMBER_ERROR) {
            *out = result;
            return FX_NUMERIC_OK;
        }
        if (index == last) break;
    }
    /*04384 clears the product's decimal marker; the sum has no such step. */
    if (product && fx_number_kind(&result) == FX_NUMBER_DECIMAL)
        result.bytes[0] &= (uint8_t)~0x40;
    *out = result;
    return FX_NUMERIC_OK;
}

fx_numeric_status fx_number_sum(fx_number *out, const fx_number *lower,
                                const fx_number *upper,
                                fx_calculus_function function, void *userdata,
                                const fx_calculus_control *control) {
    return finite_series(out, lower, upper, function, userdata, control, 0);
}

fx_numeric_status fx_number_product(fx_number *out, const fx_number *lower,
                                    const fx_number *upper,
                                    fx_calculus_function function, void *userdata,
                                    const fx_calculus_control *control) {
    return finite_series(out, lower, upper, function, userdata, control, 1);
}
