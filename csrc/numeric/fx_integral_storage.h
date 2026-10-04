/* Physical real Gauss-Kronrod workspace. GPL-3.0-or-later. */
#ifndef FX_INTEGRAL_STORAGE_H
#define FX_INTEGRAL_STORAGE_H
#include "fx_integral.h"

typedef struct {
    uint8_t *ram;
    size_t ram_size;
} fx_integral_storage;

/* The supported80F9 contexts are C1,6,7; other modes return UNIMPLEMENTED
 * without writes. C4 has a distinct20-byte argument/callback copy contract.
 * Full65536-byte RAM is required. Rich loading/terminal cleanup belongs to
 * the expression adapter. These stages preserve the original partial writes:
 * lower850A immediately after lower parsing, upper8514 immediately after
 * upper parsing, then tolerance851E and saved cursor85C8. Native15C82's
 * conversion failure is unchecked; an F/rich header can survive in RAM.
 * Negative tolerance returns native8 before the tolerance/cursor writes.
 * NULL tolerance supplies1e-5. SURD conversion publishes8640..867B.
 */
fx_numeric_status fx_integral_storage_lower(fx_integral_storage *storage,
                                            const fx_number *lower);
fx_numeric_status fx_integral_storage_upper(fx_integral_storage *storage,
                                            const fx_number *upper);
fx_numeric_status fx_integral_storage_tolerance(fx_integral_storage *storage,
    const fx_number *tolerance,uint16_t final_cursor,unsigned *native_status);

/* Native522A variable publication precedes each evaluation. The caller owns
 * the global variable policy and rich-bank refresh, so this optional seam
 * publishes the supplied local X before the ordinary calculus callback. */
typedef void (*fx_integral_storage_publish)(const fx_number *x,void *userdata);
/* Before evaluation, expose inheritedER8 and the semantic cursor to the
 * parser callback adapter. Initial/midpoint errors publish F(status) at the
 * supplied output_address; pair callbacks inherit immutable node ROM
 * addresses2B1C..2BA8, with bit0 set for the second member. Original17250
 * rejects those ROM writes. The callback owns that physical error sink and
 * updates cursor with its actual consumption, independently of value type. */
typedef void (*fx_integral_storage_callback_context)(uint16_t error_destination,
    uint16_t *cursor,void *userdata);

/* Run after the three preparation stages, from native04786. Fixed records
 * are reloaded after every callback/poll, including decimal index855A and
 * denominator8564. The caller owns5550 device/timer effects, saved-X restore,
 * final evaluator error normalization, and named output publication.
 * native_status is0/1/3/B; out retains the last callback record on errors.
 * On success it receives the integral. The driver restores cursor from85C8
 * on status0/1 only; callback consumption remains visible on other errors.
 * out/native_status/cursor must be separate objects outside RAM. Host errors
 * retain earlier RAM writes. Nonintegral or unrepresentable modified dyadic
 * indices return UNIMPLEMENTED. Comparison preserves native1/2/4/F0 raw
 * admission: headers >=0A are invalid, not equal. Malformed decimal records
 * admitted by that header guard return host UNIMPLEMENTED if decoding fails.
 * CPU frames/numeric8000..80DB are not modeled.
 */
fx_numeric_status fx_number_integral_storage(fx_number *out,
    fx_integral_storage *storage,fx_calculus_function function,void *userdata,
    fx_integral_storage_publish publish,uint16_t output_address,
    fx_integral_storage_callback_context callback_context,
    const fx_calculus_control *control,unsigned *native_status,uint16_t *cursor);
#endif
