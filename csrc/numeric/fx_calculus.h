/* Readable real finite sums and products. GPL-3.0-or-later. */
#ifndef FX_CALCULUS_H
#define FX_CALCULUS_H
#include "fx_numeric.h"

/* Evaluate the expression at a local X. Negative return values are host
 * failures and leave the API output unchanged. A native expression failure
 * is an F1..FF value record returned with FX_NUMERIC_OK. The evaluator adapter
 * must use calculus evaluation mode, which suppresses natural surd output. */
typedef fx_numeric_status (*fx_calculus_function)(fx_number *value,
                                                 const fx_number *x,
                                                 void *userdata);
/* Integral/derivative evaluator adapters may return these positive statuses
 * to distinguish the native evaluator's success/failure condition from the
 * value record. A successful evaluation may contain an F-valued variable;
 * its later arithmetic, rather than the callback, then determines failure.
 * Legacy FX_NUMERIC_OK plus an F record retains its failure semantics.
 * Negative statuses retain the host-failure channel. Sum/product adapters
 * continue using the legacy callback contract above. */
typedef enum {
    FX_CALCULUS_EVALUATION_OK = 1,
    FX_CALCULUS_EVALUATION_ERROR = 2
} fx_calculus_evaluation_status;
typedef int (*fx_calculus_cancel)(void *userdata);
typedef struct {
    fx_calculus_cancel cancelled;
    void *userdata;
} fx_calculus_control;

/* Integral bounds satisfy |bound| <10^10 and lower <= upper (F8 otherwise).
 * X visits lower, lower+1, ... upper. Cancellation is sampled before each
 * evaluation (F1). No calculator variable storage is changed by these APIs.
 * Inputs and outputs may alias. NULL control means no cancellation. */
fx_numeric_status fx_number_sum(fx_number *out, const fx_number *lower,
                                const fx_number *upper,
                                fx_calculus_function function, void *userdata,
                                const fx_calculus_control *control);
fx_numeric_status fx_number_product(fx_number *out, const fx_number *lower,
                                    const fx_number *upper,
                                    fx_calculus_function function, void *userdata,
                                    const fx_calculus_control *control);
#endif
