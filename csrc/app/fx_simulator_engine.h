/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_SIMULATOR_ENGINE_H
#define FX_SIMULATOR_ENGINE_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct fx_simulator fx_simulator;

enum {
    FXSIM_COMP = 0, FXSIM_CMPLX = 1, FXSIM_BIN = 2,
    FXSIM_OCT = 3, FXSIM_DEC = 4, FXSIM_HEX = 5
};
enum { FXSIM_DEG = 0, FXSIM_RAD = 1, FXSIM_GRAD = 2 };

/* A session owns its ten scalar variable pairs, Ans, PreAns and random seed.
 * Reset restores their initial zero records. Separate sessions share only
 * immutable firmware data. These functions do not run original CPU code. */
fx_simulator *fxsim_create(void);
void fxsim_destroy(fx_simulator *simulator);
void fxsim_reset(fx_simulator *simulator);

/* Evaluate bounded ASCII expression text through the native-token encoder
 * and the high-level prepared evaluator. mode and angle use the enums above;
 * math is 0 for linear output or 1 for natural output. ASCII input is bounded
 * to 4096 bytes, excluding NUL. Embedded NUL ends the request.
 *
 * Return 0 for a complete JSON response, including calculator errors and
 * explicit unsupported expressions. Return -1 for invalid arguments,
 * allocation failure or insufficient output capacity. A -1 return leaves
 * session state unchanged and clears out[0] when out/capacity permit it.
 * The input string and output buffer must not overlap.
 *
 * JSON: status (ok/error/unsupported), native_status, error, error_position,
 * error_position_kind, real/imag/tokens hex, framebuffer hex, width, height,
 * and plain. Native errors report a zero-based INPUT-token cursor; encoder
 * failures report an ASCII-byte cursor. Framebuffer is 384 row-major bytes:
 * 12 bytes per row, top to bottom, most-significant bit is the left pixel.
 * The screen is the existing result-only B070 presentation or error dialog;
 * this API does not perform a complete key/UI transaction. Exact numeric
 * records and emitted tokens remain authoritative when plain is unavailable.
 */
int fxsim_evaluate(fx_simulator *simulator, const char *expression,
                  unsigned mode, unsigned angle, unsigned math,
                  char *out, size_t capacity);

#ifdef __cplusplus
}
#endif
#endif
