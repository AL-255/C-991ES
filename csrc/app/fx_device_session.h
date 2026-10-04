/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_DEVICE_SESSION_H
#define FX_DEVICE_SESSION_H

#include <stddef.h>
#include <stdint.h>
#include "../platform/fx_runtime.h"

#define FX_DEVICE_RAM_BYTES 65536u
#define FX_DEVICE_FRAMEBUFFER_BYTES 384u

typedef struct fx_device_session fx_device_session;

/* An optional, externally supplied power-on/retained data image is copied
 * before any controller runs. It must contain exactly65536 bytes; NULL/0
 * selects a zeroed cold image with the passive key input F040=FF. The raw
 * variant byte is published at F050 in either case. No instructions or CPU
 * state are accepted. The caller retains ownership of the source image. */
typedef struct {
    const uint8_t *initial_ram;
    size_t initial_ram_bytes;
    uint8_t variant;
} fx_device_configuration;

/* Read-only observation of the actual named controllers. A typed pending
 * request is retained as a request: the session cannot fabricate the result
 * of an unimplemented or delegated MAIN/INPUT body. The visible framebuffer
 * is32rows of12packed bytes taken from the original16-byte row stride. */
typedef struct {
    uint8_t framebuffer[FX_DEVICE_FRAMEBUFFER_BYTES];
    fx_runtime_status last_status;
    fx_runtime_phase phase;
    fx_runtime_event event;
    fx_runtime_request request;
    fx_memory_status memory_status;
    uint32_t steps;
    uint16_t timer_period;
    uint8_t active, timer_pending, export_mask, returned;
    uint8_t callback_pending;
    uint8_t main_request, wait_required, last_menu_result;
    uint8_t input_action, input_context_return;
    uint8_t mode_result, bank_result, mode_request, mode_page, bank_page;
    uint8_t unsupported_token;
    uint8_t key_columns, key_rows, host_wait;
} fx_device_snapshot;

/* Creation only initializes the persistent data/MMIO image and platform.
 * Call reset explicitly to start the real boot/runtime controller. A NULL
 * configuration selects the ordinary cold variant0 input. */
fx_device_session *fx_device_session_create(
    const fx_device_configuration *configuration);
void fx_device_session_destroy(fx_device_session *session);

/* Real firmware reset retains the current data/MMIO image and applies the
 * existing boot policy; it does not memset the session or fake boot READY. */
fx_runtime_status fx_device_session_reset(fx_device_session *session);

/* Raw emulator host packet, not an ASCII expression or mapped token. Packets
 * remain in8E01/8E02 until the host explicitly releases/replaces them. */
int fx_device_session_submit_pair(fx_device_session *session,
    uint8_t columns, uint8_t rows);
int fx_device_session_release(fx_device_session *session);

/* Exactly one existing runtime controller phase. The physical sample provider
 * is used where current boot controllers require it; ordinary key waits use
 * the submitted packet. A nonzero timer_elapsed acknowledges a real pending
 * semantic timer. No host wall clock, CPU tick or automatic loop is inferred. */
fx_runtime_status fx_device_session_step(fx_device_session *session,
    const fx_key_input *physical_input, uint8_t timer_elapsed);
/* A convenience acknowledgment performs one step only when a timer is
 * actually pending. Otherwise it returns INVALID without modifying state. */
fx_runtime_status fx_device_session_ack_timer(fx_device_session *session,
    const fx_key_input *physical_input);

/* Consume the existing F000 publication observer, not a simulated interrupt. */
uint8_t fx_device_session_take_callback(fx_device_session *session);
int fx_device_session_snapshot(const fx_device_session *session,
    fx_device_snapshot *snapshot);
/* Bounded, nonwrapping read-only RAM/MMIO inspection. A zero-byte read accepts
 * NULL output; other reads require storage. The source remains session-owned. */
int fx_device_session_read_ram(const fx_device_session *session,
    uint16_t address, uint8_t *output, size_t bytes);

#endif
