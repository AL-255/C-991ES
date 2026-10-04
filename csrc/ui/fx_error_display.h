/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_ERROR_DISPLAY_H
#define FX_ERROR_DISPLAY_H
#include "../platform/fx_platform.h"

/* Native3FBA four-line dialog: font7, up to16 characters per line, at
 * LCD coordinates(0,1),(0,9),(0,17),(0,25). Clears all512 LCD bytes, retains
 * the RAM framebuffer, and finishes with8121=1/F031=5. Line pointers are
 * data-bus addresses; the host descriptor is immutable. No CPU frame exists.
 * Returns0 success, -1 invalid platform/descriptor or missing font data,
 * -2 for an unmapped source span or an original CPU-stack/call-argument
 * source alias (8D00..8DF1 for this dialog,8D00..8DED for4074).
 * Invalid inputs are rejected before any writes. Unterminated text is
 * truncated at the original16-character limit; byte pointers may wrap. */
int fx_error_dialog_draw(fx_platform *platform, const uint16_t lines[4]);

/* Native4074: byte-valued(error-1) indexes the ROM113E word table, followed
 * by ROM11A1/1292/1158 on the remaining three rows. Errors1..13 are defined,
 * including blank6 and NULL ERROR13. Other bytes retain the native table
 * indexing when their source pointers are within the dialog API domain. */
int fx_error_display(fx_platform *platform, uint8_t error);
#endif
