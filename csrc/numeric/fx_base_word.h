/* Prepared scalar word operations with independent native mode policies.
 * GPL-3.0-or-later. */
#ifndef FX_BASE_WORD_H
#define FX_BASE_WORD_H
#include "fx_base.h"

/* Complete firmware bytes, not normalized radix or Boolean values.
 * The three fields control different stages and must remain independent. */
typedef struct {
    uint8_t selected_mask;       /* 80FA: exact1 selects the BIN width. */
    uint8_t calculation_context; /* 80F9: global mode used by serialization. */
    uint8_t operation_context;   /* Prepared operation context, native R6. */
} fx_base_word_context;

/* 15A1E/15A94: unchecked ten-digit extraction after adding10^10, modulo2^32.
 * Every selected byte is accepted. Only exact selected_mask1 applies the
 * signed16 magnitude check; rejected negative magnitudes remain positive.
 * carry reports this rejection separately from the C API status. */
fx_numeric_status fx_base_word_decode(uint32_t *word, unsigned *carry,
                                     const fx_number *number,
                                     uint8_t selected_mask);

/* 15B00/15A64: encode a signed32 word. Signed16 rejection applies only when
 * calculation_context2 AND selected_mask1. It sets native_status3 and keeps
 * out unchanged. Every other context/selected combination uses signed32. */
fx_numeric_status fx_base_word_encode(fx_number *out, uint32_t word,
                                     uint8_t selected_mask,
                                     uint8_t calculation_context,
                                     unsigned *native_status);

/* 15E82: native_status is both input and output. A prior nonzero status, or
 * operation_context other than2, returns unchanged without examining the
 * scalar. Otherwise raw sign/tag admission uses signed16 for exact selected
 * byte1 and signed32 for every other selected byte. number stays unchanged. */
fx_numeric_status fx_base_word_validate(const fx_number *number,
                                       const fx_base_word_context *context,
                                       unsigned *native_status);

/* 15C1C/15C46: decode under selected_mask, apply NOT or two's-complement
 * negation, then serialize under calculation_context. Input/output aliases
 * work. Rejected NEG retains the original record and reports native_status3.
 * NOT ignores incoming carry and preserves native partial serialization when
 * BIN output is rejected. A zero residual pair makes the original serializer
 * non-returning: that known boundary returns FX_NUMERIC_UNIMPLEMENTED without
 * changing out/native_status, rather than claiming a native return. */
fx_numeric_status fx_base_word_unary(fx_number *out, const fx_number *number,
                                    const fx_base_word_context *context,
                                    fx_base_unary_op operation,
                                    unsigned *native_status);

/* 15F34/15F40/15F4C/15F58 and15D62/15D9E/15DDA/15E1E. Arithmetic retains
 * exact scalar policies. Only operation_context2 enables result range checks
 * for +,-,* or truncation after successful division. Logical operations use
 * decode and serialization policies independently, as unary operations do.
 * Input/output aliases work. Canonical decimal/marked decimal, rational/
 * marked rational, surd and F* records have the same admission as fx_base;
 * unknown record kinds remain explicit unsupported inputs. This prepared
 * API does not widen the original typed literal or UI-mask APIs. */
fx_numeric_status fx_base_word_binary(fx_number *out, const fx_number *left,
                                     const fx_number *right,
                                     const fx_base_word_context *context,
                                     fx_base_binary_op operation,
                                     unsigned *native_status);
#endif
