/* Physical real Richardson workspace. GPL-3.0-or-later. */
#ifndef FX_DERIVATIVE_STORAGE_H
#define FX_DERIVATIVE_STORAGE_H
#include "fx_derivative.h"
#include <stddef.h>
#include <stdint.h>

/* Full physical RAM is required. The supported global80F9 modes are
 * C1,6,7; other modes return FX_NUMERIC_UNIMPLEMENTED without writes.
 * C4 needs the native20-byte complex callback/argument contract. */
typedef struct {
    uint8_t *ram;
    size_t ram_size;
} fx_derivative_storage;

/* The expression adapter calls point preparation immediately after parsing
 * the point, before evaluating an explicit tolerance. Each helper preserves
 * native partial writes. All arithmetic records remain backed by RAM.
 * These helpers receive parsed argument values; loading/finishing a rich
 * variable is owned by the expression adapter. Point preparation includes
 * native15C82 normalization and any supplied SURD's8640 component stores. */
fx_numeric_status fx_derivative_storage_point(fx_derivative_storage *storage,
                                             const fx_number *point);
fx_numeric_status fx_derivative_storage_tolerance(fx_derivative_storage *storage,
                                                 const fx_number *tolerance,
                                                 unsigned *native_status);
/* Run after both preparation stages. Before each callback,8276 receives X.
 * Callback/poll code may modify RAM; the driver reloads the fixed records.
 * The expression adapter owns522A full variable publication, rich bank
 * refresh/cleanup, saved-X restoration and5550 timer/device effects.
 * Evaluator-error status publishes F(status) at85B4; a successful F-valued
 * callback preserves its independent success channel. Mathematical results
 * follow fx_number_derivative. Raw comparator header errors retain nativeF0.
 * Malformed decimal coordinates outside its bounded decoder return host
 * UNIMPLEMENTED. Negative host failures leave out unchanged. */
fx_numeric_status fx_number_derivative_storage(fx_number *out,
                                               fx_derivative_storage *storage,
                                               fx_calculus_function function,
                                               void *userdata,
                                               const fx_calculus_control *control);
#endif
