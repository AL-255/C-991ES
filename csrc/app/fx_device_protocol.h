/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_DEVICE_PROTOCOL_H
#define FX_DEVICE_PROTOCOL_H

#include "fx_device_session.h"

/* An allocated, read-only observation of the real device controllers.
 * The caller frees the returned string with free(). NULL reports allocation
 * or observation failure. No controller step or callback drain is performed. */
char *fx_device_session_json(const fx_device_session *session);

#endif
