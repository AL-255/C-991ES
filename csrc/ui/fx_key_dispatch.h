/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_KEY_DISPATCH_H
#define FX_KEY_DISPATCH_H
#include "fx_editor.h"

/* Process the token produced by a key table (1DC3E..1DCB6). action_address
 * is the caller's action byte, written3 for E7. The output is the token
 * after context remapping and input permission checks. Returns1 when a
 * token is ready,0 when a modifier was consumed and the caller should
 * await another key, or -1 for a bounded malformed editor buffer.
 * No scan, blocking wait, menu action or physical timer scheduling occurs. */
int fx_key_process_token(fx_platform *platform, uint8_t token,
                          uint16_t action_address, uint8_t *output);

#endif
