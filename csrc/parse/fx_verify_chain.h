/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_VERIFY_CHAIN_H
#define FX_VERIFY_CHAIN_H
#include "fx_eval_verify.h"

typedef struct {
    uint16_t source;
    uint32_t operands,relations,cancellation_checks;
    uint8_t truth,unsupported_token;
    int native_status;
} fx_verify_chain_result;

/*138EE relation chain over the actual mode137 operand grammar. Source is a
 * named caller-owned16-bit cursor. Native DEC/INC change only its low byte.
 * Every relation polls5550; false comparisons still evaluate later operands.
 * The global output pair is constructed only on successful final EOF.
 * Operand/predicate errors and cancellation retain that pair and all earlier
 * actual workspace/variable/peripheral effects. result and control are
 * separate host objects outside RAM. Input/output must be disjoint from the
 * parser's numeric pools, variable banks and inherited sample sink aliases.
 * The six insertable relations are supported; raw low-nibble aliases are
 * admitted when they resolve to the same six native predicate entries.
 * Unknown dispatch addresses return explicit UNIMPLEMENTED after preceding
 * operand/poll effects. No CPU-local frames or whole key workflow is modeled.
 * input_capacity bounds each remaining physical operand stream. A missing
 * NUL within that bound returns RESOURCE_LIMIT, rather than reading past it. */
fx_eval_status fx_verify_chain(fx_eval_storage *storage,uint16_t source,
    uint16_t output_address,size_t input_capacity,
    const fx_calculus_control *control,fx_verify_chain_result *result);
#endif
