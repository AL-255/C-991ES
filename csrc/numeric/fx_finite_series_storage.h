/* Prepared native finite SUM/product data flow. SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_FINITE_SERIES_STORAGE_H
#define FX_FINITE_SERIES_STORAGE_H
#include "fx_calculus.h"
#include "../complex/fx_complex.h"

typedef struct {
    uint8_t *ram;
    size_t ram_size;
    const uint8_t *rom;
    size_t rom_size;
} fx_finite_series_storage;
/* The descriptor is outside its RAM image. Named state, bound arguments and
 * control descriptors are outside RAM and mutually disjoint with state and
 * storage descriptors. Callback userdata may refer to the live RAM image.
 * Calculator address aliases are represented by transfer/publication calls,
 * rather than overlapping these host objects. */

typedef enum { FX_FINITE_SUM, FX_FINITE_PRODUCT } fx_finite_series_kind;
typedef enum {
    FX_FINITE_EMPTY, FX_FINITE_LOWER_STAGED, FX_FINITE_READY,
    FX_FINITE_ACTIVE, FX_FINITE_NUMERIC_FINISHED
} fx_finite_series_phase;
enum { FX_FINITE_EXPRESSION_COMPLETE = 0xfe };

/* A callback condition is independent of its value. FE means that171EA
 * completed the body; every other byte is retained as its native condition.
 * In particular a completed F-valued expression still reaches arithmetic.
 * error_sink_written reports an actual evaluator store to the caller-owned
 * accumulator, independently of value/condition. The driver applies that
 * returned event before testing condition; it is not a guessed terminal
 * CDE4 store. This event-result seam does not expose the accumulator during
 * callback execution. Negative host returns do not publish this descriptor.
 * source is a named calculator input cursor, not a host pointer or CPU state. */
typedef struct {
    fx_complex value;
    uint16_t source;
    uint8_t condition, error_sink_written;
    fx_number error_sink;
} fx_finite_series_evaluation;
typedef fx_numeric_status (*fx_finite_series_function)(
    fx_finite_series_evaluation *evaluation, const fx_complex *live_x,
    void *userdata);

/* Four adjacent ten-byte DATA records: accumulator, saved initial X,
 * end bound, and the companion spilled past the original30-byte allocation.
 * This object is outside RAM; it is not an emulated processor frame.
 * spilled records the native out-of-allocation transfer. Finishing numeric
 * work alone does not prove that the original caller's epilogue returns.
 * value is the original working result pair: failed numeric conditions do
 * not synthesize a CDE4 error store; the expression caller owns that store. */
typedef struct {
    fx_number records[4];
    fx_complex value;
    uint16_t source, body_source;
    uint8_t kind, phase, native_status, spilled;
} fx_finite_series_state;

/* Original169C0/169F4 transfer policy, including odd8+2 alignment and a
 * post-real-write live80F9 read. Both source/destination need room for20
 * bytes. Source reads below8000 use immutable ROM; destinations are RAM.
 * Invalid host extents are rejected before any write. */
fx_numeric_status fx_finite_series_transfer(fx_finite_series_storage *storage,
    uint16_t destination, uint16_t source);
/* Original522A X publication uses ten ascending bytes, then the live mode
 * test, then ten ascending companion bytes to8458. Physical aliases are live. */
fx_numeric_status fx_finite_series_publish_x(fx_finite_series_storage *storage,
    uint16_t source);

fx_numeric_status fx_finite_series_begin(fx_finite_series_state *state,
    fx_finite_series_kind kind);
/* Corresponds to the lower171EA result's immediate copy to local+10.
 * Named state/arguments must be outside the supplied RAM image. */
fx_numeric_status fx_finite_series_lower(fx_finite_series_state *state,
    fx_finite_series_storage *storage, const fx_complex *lower);
/* Gate upper then lower; convert upper then lower; compare; sleep; copy
 * upper at+20; install identity and its live C4 companion; publish X ONCE.
 * after_arguments is the already-resolved native caller source cursor.
 * Argument8 finishes before the spilling copy and before any poll. */
fx_numeric_status fx_finite_series_upper(fx_finite_series_state *state,
    fx_finite_series_storage *storage, const fx_complex *upper,
    uint16_t after_arguments);
/* Successful169F4 publication to the NUMERIC working result, independently
 * of the outer171F4 output. Copy the accumulator8+2 first; reread live80F9;
 * only C4 copies the adjacent initial-X record. Odd and mode aliases remain
 * live. value is then read from that physical working pair. This prepared
 * stage does not assert that a spilling native caller epilogue returns. */
fx_numeric_status fx_finite_series_store_result(fx_finite_series_state *state,
    fx_finite_series_storage *storage, uint16_t working_address);
/* One actual finite-series sample:5550 handshake, body, scalar arithmetic,
 * cleanup, equality or live-X increment. The backedge does not republish X.
 * The control callback is sampled after actual timer/request publication;
 * it may mutate RAM. NULL control supplies a noncancelled host response.
 * Numeric errors/cancellation finish with native_status; host failures retain
 * all preceding data effects and return the separate negative status. */
fx_numeric_status fx_finite_series_step(fx_finite_series_state *state,
    fx_finite_series_storage *storage, fx_finite_series_function function,
    void *userdata, const fx_calculus_control *control);
/* max_samples0 is unlimited. Exhausting an explicit host budget returns
 * UNIMPLEMENTED with the still-active state/RAM retained, never a native
 * Argument/Math error. Native completion remains equality-only. */
fx_numeric_status fx_finite_series_run(fx_finite_series_state *state,
    fx_finite_series_storage *storage, fx_finite_series_function function,
    void *userdata, const fx_calculus_control *control, size_t max_samples);
#endif
