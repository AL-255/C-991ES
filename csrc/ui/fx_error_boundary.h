/* SPDX-License-Identifier: GPL-3.0-only */
/* Additive E47E completed-export boundary; existing APIs unchanged. */
#ifndef FX_ERROR_BOUNDARY_H
#define FX_ERROR_BOUNDARY_H
#include "ui/fx_error_event.h"
/* Return EXPORT after completed packets, before beginning the next wait.
 * A subsequent tick starts that wait and returns WAIT; host key pairs remain
 * host-owned. No original CPU frame or PC is implementation state. */
fx_key_controller_status fx_error_event_tick_export_boundary(fx_platform *,fx_error_event *);
#endif
