/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_HOST_BRIDGE_H
#define FX_HOST_BRIDGE_H
#include "fx_platform.h"

/* 0x792c: ten little-endian pointers used by the Windows emulator host.
 * They name the wait/key flags, framebuffer packet, packet length, status
 * packet and optional text packet. The descriptor occupies twenty bytes. */
void fx_host_write_descriptor(fx_platform *platform, uint16_t destination);
/* 0x796e: write the complete 48-byte status packet. Cursor coordinates are
 * hidden when the editor suppresses its cursor; all reserved bytes are zero. */
void fx_host_write_status(fx_platform *platform, uint16_t destination);
/* 0x742c: write header 80 01 and all 384 visible LCD bytes to 0x9000.
 * The four padding bytes on each LCD row are excluded. */
void fx_host_write_framebuffer(fx_platform *platform);
/* 0xaf5a: update the status packet, optional zero-terminated text header and
 * four ASCII hexadecimal length digits through a prepared descriptor.
 * Return -1 for an unterminated 64 KiB string; native code would loop. */
int fx_host_write_text_packet(fx_platform *platform, uint16_t descriptor);
#endif
