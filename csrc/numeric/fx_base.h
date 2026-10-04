/* Readable BASE-N integer conversion and prepared arithmetic.
 * GPL-3.0-or-later. */
#ifndef FX_BASE_H
#define FX_BASE_H
#include "fx_numeric.h"

/* These are the firmware's complete 80FA values, not radix numbers. */
typedef enum { FX_BASE_BIN = 1, FX_BASE_OCT = 7,
               FX_BASE_DEC = 9, FX_BASE_HEX = 15 } fx_base_radix;
typedef enum { FX_BASE_NOT, FX_BASE_NEGATE } fx_base_unary_op;
typedef enum { FX_BASE_ADD, FX_BASE_SUBTRACT, FX_BASE_MULTIPLY, FX_BASE_DIVIDE,
               FX_BASE_OR, FX_BASE_XOR, FX_BASE_XNOR, FX_BASE_AND } fx_base_binary_op;
typedef struct {
    size_t consumed;
    unsigned native_status; /* R2: 0 success,2 syntax,3 range */
    uint8_t native_kind;    /* R7: 4 on success,0 on failure */
} fx_base_literal_result;

/* 15A1E/15A94: read ten digits after adding 10^10, then convert modulo
 * 2^32. A failed BIN magnitude check sets carry and leaves word positive.
 * Canonical decimal, marked decimal, rational, marked rational, surd and F*
 * records are accepted. The bias addition rejects surds and F* as F3,
 * whose zero digit payload is still extracted, matching the original leaf. */
fx_numeric_status fx_base_decode_word(uint32_t *word, unsigned *carry,
                                     const fx_number *number, uint8_t base_mask);
/* 15B00/15A64: serialize the signed 32-bit word. In BIN, a word outside
 * [-32768,32767] sets native_status=3 and leaves out unchanged. */
fx_numeric_status fx_base_encode_word(fx_number *out, uint32_t word,
                                     uint8_t base_mask, unsigned *native_status);
/* 15E82 with R0=0/R6=2: range check without changing the source record.
 * BIN uses [-32768,32768); other bases use [-2^31,2^31). Fractions are
 * admitted by this checker; it does not itself truncate. */
fx_numeric_status fx_base_validate(const fx_number *number, uint8_t base_mask,
                                  unsigned *native_status);
/* Literal 15E82 raw-record dispatch, entered with prior arithmetic status0.
 * Accepts canonical headers0/2/4/6/8/F. Tagged comparisons at CD60 returnF0:
 * positive tagged results fail with status3, other tagged classes pass.
 * This preserves the native sign/tag rule, including surd cancellation;
 * it is distinct from validating the mathematical value after conversion. */
fx_numeric_status fx_base_validate_raw(const fx_number *number,
                                      uint8_t base_mask,
                                      unsigned *native_status);
/* 1D040 then 15E82: truncate toward zero and check the selected range. */
fx_numeric_status fx_base_prepare(fx_number *out, const fx_number *number,
                                 uint8_t base_mask, unsigned *native_status);
/* 15ED6 after a scalar bank fetch: normalize a stored decimal/rational/surd,
 * remove decimal/rational metadata, truncate and range-check. Stored error
 * records and canonical empty-payload 6x/9x references become Math ERROR F3
 * without fetching reference cells. The variable-bank copy and imaginary-field
 * clearing are the caller's responsibility. */
fx_numeric_status fx_base_prepare_scalar(fx_number *out, const fx_number *number,
                                        uint8_t base_mask, unsigned *native_status);
/* Native status is the original R0. It is distinct from the C API status.
 * Rejected NEG keeps the original record; range-rejected +,-,* keep the
 * computed decimal record. Division truncates and performs no range check.
 * Logical operators use all 32 bits, including sign extension in BIN.
 * Arithmetic +,-,*,/ admits canonical decimal, marked decimal, rational,
 * marked rational, surd and error records. It uses exact scalar arithmetic
 * before the native raw range check; any incoming F* becomes F3/status3.
 * Division converts/truncates without a range check. NOT/Neg and logical
 * operations admit the same canonical scalar metadata as word conversion.
 * NOT/logical ignore incoming BIN carry and preserve returning partial
 * serialization after BIN rejection, including noncanonical result bytes.
 * Only the proven zero-residual-pair native non-return boundary returns
 * UNIMPLEMENTED, preserving both output and native_status.
 * Input and output aliases are supported. */
fx_numeric_status fx_base_unary(fx_number *out, const fx_number *number,
                               uint8_t base_mask, fx_base_unary_op operation,
                               unsigned *native_status);
fx_numeric_status fx_base_binary(fx_number *out, const fx_number *left,
                                const fx_number *right, uint8_t base_mask,
                                fx_base_binary_op operation,
                                unsigned *native_status);
/* 16828, called after the radix prefix was decoded. Tokens are calculator
 * digit tokens (ASCII0..9 or B8..BD for hex), followed by an explicit NUL or
 * delimiter. The successful cursor stops before the delimiter; failures
 * include the offending token. Leading zeros do not use the width budget.
 * Early errors preserve out; selected-BIN rejection preserves native late
 * partial writes. Input-token storage and out must not overlap. */
fx_numeric_status fx_base_parse_literal(fx_number *out, const uint8_t *tokens,
                                       size_t length, uint8_t input_base,
                                       uint8_t selected_base,
                                       fx_base_literal_result *result);
#endif
