/* Arbitrary-base real logarithm. GPL-3.0-or-later. */
#ifndef FX_LOGBASE_H
#define FX_LOGBASE_H
#include "fx_numeric.h"

/* Counterpart of public1C082/kernel190CE. Base is operand0 and argument is
 * operand2. Canonical decimal/rational/surd records are converted through
 * the original decimal-logarithm order. Native domain errors become F3
 * records with FX_NUMERIC_OK. Both sources may alias the output. */
fx_numeric_status fx_number_log_base(fx_number *out, const fx_number *base,
                                     const fx_number *argument);
#endif
