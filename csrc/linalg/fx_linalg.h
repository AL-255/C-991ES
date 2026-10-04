/* Fixed-stride matrix and vector kernels. GPL-3.0-or-later. */
#ifndef FX_LINALG_H
#define FX_LINALG_H
#include "../numeric/fx_numeric.h"

/* Evaluator references have header6x (matrix) or9x (vector), where the low
 * nibble identifies storage. Each slot reserves nine ten-byte scalars with
 * row stride three. Inactive cells are observable and must be preserved. */
typedef struct {
    fx_number reference;
    uint8_t rows, columns;
    fx_number cells[9];
} fx_linalg_value;

typedef struct {
    uint8_t exact_math, display_mode, digits;
    /* Prepared cancellation response: zero never cancels; otherwise the
     * numbered native timer check returns cancellation. Physical timing and
     * the key/interrupt controller remain outside this numerical API. */
    uint32_t cancel_at;
} fx_linalg_context;

typedef struct {
    fx_linalg_value value;
    uint8_t firmware_status;
    uint32_t cancellation_checks;
} fx_linalg_result;

typedef enum {
    FX_LINALG_ADD, FX_LINALG_SUBTRACT, FX_LINALG_MATRIX_MULTIPLY,
    FX_LINALG_DOT, FX_LINALG_CROSS
} fx_linalg_binary_op;

typedef enum {
    FX_LINALG_TRANSPOSE, FX_LINALG_DETERMINANT, FX_LINALG_INVERSE,
    FX_LINALG_VECTOR_MAGNITUDE, FX_LINALG_ABSOLUTE,
    FX_LINALG_DISPLAY_ROUND, FX_LINALG_RATIONAL_PREPARE,
    FX_LINALG_INTEGER_CLEANUP, FX_LINALG_NEGATE,
    FX_LINALG_SQUARE, FX_LINALG_CUBE
} fx_linalg_unary_op;

typedef enum {
    FX_LINALG_SCALE, FX_LINALG_DIVIDE, FX_LINALG_FRACTION_DIVIDE
} fx_linalg_scalar_op;

void fx_linalg_context_default(fx_linalg_context *context);
/* Prepared numerical entries, not a second evaluator/parser. Inputs may
 * alias result.value. Reference output may become a scalar or error while
 * the dimensional/payload state retains native partial changes. */
fx_numeric_status fx_linalg_binary(fx_linalg_result *out,
                                   const fx_linalg_value *left,
                                   const fx_linalg_value *right,
                                   fx_linalg_binary_op operation,
                                   const fx_linalg_context *context);
fx_numeric_status fx_linalg_scalar(fx_linalg_result *out,
                                   const fx_linalg_value *input,
                                   const fx_number *scalar,
                                   fx_linalg_scalar_op operation,
                                   const fx_linalg_context *context);
fx_numeric_status fx_linalg_unary(fx_linalg_result *out,
                                  const fx_linalg_value *input,
                                  fx_linalg_unary_op operation,
                                  const fx_linalg_context *context);
#endif
