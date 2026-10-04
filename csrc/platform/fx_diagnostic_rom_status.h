/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FX_DIAGNOSTIC_ROM_STATUS_H
#define FX_DIAGNOSTIC_ROM_STATUS_H

#include "fx_platform.h"

/* Resources used only by the original 7334 diagnostic. These operations do
 * not expose an instruction executor, CPU register file, or ALU flag model.
 * A hardware adapter or an explicitly modeled resource backend supplies the
 * actual writes and readbacks. The provider owns its context and lifetime. */
typedef struct {
    void *context;
    void (*write_status)(void *context, uint8_t value);
    uint8_t (*read_status)(void *context);
    void (*write_retention)(void *context, uint8_t value);
    uint8_t (*read_retention)(void *context);
} fx_diagnostic_resources;

typedef enum {
    FX_DIAGNOSTIC_ROM_STATUS_COMPLETE = 0,
    FX_DIAGNOSTIC_ROM_STATUS_INVALID = -1,
    FX_DIAGNOSTIC_ROM_STATUS_UNAVAILABLE = -2
} fx_diagnostic_rom_status;

typedef struct {
    fx_diagnostic_rom_status status;
    /* Only COMPLETE has a firmware return value: A5 for success, 00 for a
     * failed status/retention test. UNAVAILABLE is not a native Read NG. */
    uint8_t value;
} fx_diagnostic_rom_status_result;

/* Read ROM alias8 offsets0000..FFFF, then bank1 offsets0000..FFFB. Every
 * byte read precedes a status44 write/read requiring maskedF4==44. Data is
 * discarded; this is separate from the preceding additive checksum. The
 * second sweep retains5A. Failed status samples stop immediately.
 * All resources are required before the first bus operation. Named C locals
 * and the returned object never create a calculator-RAM CPU frame or failure
 * flag. Provider storage must belong to its declared resource backend. */
fx_diagnostic_rom_status_result fx_diagnostic_rom_status_run(
    fx_platform *platform, const fx_diagnostic_resources *resources);

/* Portable simulator model of these two diagnostic resources. Volatile
 * storage preserves actual write/read operations even in optimized builds.
 * This is a software device model, not certification of a physical nX-U8
 * CPU. It does not model status changes from other firmware arithmetic.
 * The caller initializes and owns this storage outside calculator RAM. */
typedef struct {
    volatile uint8_t status;
    volatile uint8_t retention;
} fx_diagnostic_resource_model;

/* NULL storage returns an unavailable provider with no accessors. */
fx_diagnostic_resources fx_diagnostic_resource_model_bind(
    fx_diagnostic_resource_model *model);

#endif
