/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_HOST_BRIDGE_H
#define FX_HOST_BRIDGE_H
#include "fx_platform.h"
#include "../numeric/fx_numeric.h"

/* Host-owned counterpart of the native twenty-byte descriptor. A controller
 * can retain these addresses without allocating a synthetic CPU local in RAM. */
typedef struct {
    uint16_t wait_flag;
    uint16_t key_columns;
    uint16_t key_rows;
    uint16_t numeric_packet;
    uint16_t framebuffer_packet;
    uint16_t packet_length;
    uint16_t status_packet;
    uint16_t status_details;
    uint16_t text_header;
    uint16_t text;
} fx_host_descriptor;

void fx_host_descriptor_default(fx_host_descriptor *descriptor);

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
void fx_host_write_framebuffer_fields(fx_platform *platform,
                                      const fx_host_descriptor *descriptor);
/* 0xaf5a: update the status packet, optional zero-terminated text header and
 * four ASCII hexadecimal length digits through a prepared descriptor.
 * Return -1 for an unterminated 64 KiB string; native code would loop. */
int fx_host_write_text_packet(fx_platform *platform, uint16_t descriptor);
int fx_host_write_text_packet_fields(fx_platform *platform,
                                    const fx_host_descriptor *descriptor);
/* 75a4: raw numeric export, distinct from on-screen scalar formatting.
 * The caller supplies a 23-byte field. Error records write only ERROR/NUL;
 * surds write 22 bytes and retain the last byte. Returns 1 for an error
 * record, 0 otherwise, or -1 without writes for a malformed rational whose
 * encoded length would overflow the native local field. Overlap is safe. */
int fx_host_format_number(const fx_number *number, uint8_t output[23]);
/* 747a: export record 8230 and, in mode C4, record 8412; other modes use zero.
 * Fields are prezeroed. The packet is 30/00/43/09, 22 real bytes, TAB, 23
 * imaginary bytes. Malformed rational lengths return -1 without RAM writes. */
int fx_host_write_numeric_packet(fx_platform *platform);
int fx_host_write_numeric_packet_fields(fx_platform *platform,
                                       const fx_host_descriptor *descriptor);
#endif
