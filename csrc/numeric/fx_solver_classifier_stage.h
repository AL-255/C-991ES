/* Prepared simultaneous-equation classification effects.
 * SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef FX_SOLVER_CLASSIFIER_STAGE_H
#define FX_SOLVER_CLASSIFIER_STAGE_H
#include "fx_solver.h"

/* Called immediately before each reached native 1ccf6 classification. The
 * borrowed number is a captured coefficient or a named mathematical
 * intermediate. It is immutable and valid only for the callback duration.
 * Hooks can publish prepared physical conversion effects. Non-OK status
 * stops the classification, retains prior hook effects, and does not commit
 * a final classification value. The callback never supplies a class. */
typedef fx_numeric_status (*fx_solver_classification_callback)(
    const fx_number *number, void *userdata);

/* Same finite determinant/zero-pivot policy as the original public API.
 * Twelve input records are captured before hooks/output; old public structs
 * and function signatures remain unchanged. A NULL hook has no IO effects. */
fx_numeric_status fx_solver_classify_degenerate_observed(uint8_t *classification,
    const fx_number coefficients[12], fx_solver_kind kind,
    fx_solver_classification_callback callback, void *userdata);
#endif
