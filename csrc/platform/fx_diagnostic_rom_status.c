/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_diagnostic_rom_status.h"

static int status_sample_passes(const fx_diagnostic_resources *resources)
{
    resources->write_status(resources->context, 0x44);
    uint8_t observed = resources->read_status(resources->context);
    return (observed & 0xf4u) == 0x44u;
}

static int sweep(fx_platform *platform, const fx_diagnostic_resources *resources,
    uint8_t segment, uint32_t count)
{
    for (uint32_t offset = 0; offset < count; ++offset) {
        /* The original read tests the ROM bus even though its data does not
         * enter the status predicate. Keep the byte load observable when
         * the platform data accessor is inlined during optimization. */
        volatile uint8_t discarded = fx_data_read(platform, segment,
                                                  (uint16_t)offset);
        (void)discarded;
        if (!status_sample_passes(resources)) return 0;
    }
    return 1;
}

fx_diagnostic_rom_status_result fx_diagnostic_rom_status_run(
    fx_platform *platform, const fx_diagnostic_resources *resources)
{
    fx_diagnostic_rom_status_result result = {
        FX_DIAGNOSTIC_ROM_STATUS_INVALID, 0
    };
    if (!platform || !platform->ram ||
        (!platform->rom && platform->rom_size)) return result;
    result.status = FX_DIAGNOSTIC_ROM_STATUS_UNAVAILABLE;
    if (!resources || !resources->write_status || !resources->read_status ||
        !resources->write_retention || !resources->read_retention) return result;

    result.status = FX_DIAGNOSTIC_ROM_STATUS_COMPLETE;
    if (!sweep(platform, resources, 8, 65536u)) return result;
    resources->write_retention(resources->context, 0x5a);
    if (!sweep(platform, resources, 1, 65532u)) return result;
    if (resources->read_retention(resources->context) != 0x5a) return result;
    result.value = 0xa5;
    return result;
}

static void model_write_status(void *context, uint8_t value)
{
    ((fx_diagnostic_resource_model *)context)->status = value;
}

static uint8_t model_read_status(void *context)
{
    return ((fx_diagnostic_resource_model *)context)->status;
}

static void model_write_retention(void *context, uint8_t value)
{
    ((fx_diagnostic_resource_model *)context)->retention = value;
}

static uint8_t model_read_retention(void *context)
{
    return ((fx_diagnostic_resource_model *)context)->retention;
}

fx_diagnostic_resources fx_diagnostic_resource_model_bind(
    fx_diagnostic_resource_model *model)
{
    fx_diagnostic_resources resources = {model, NULL, NULL, NULL, NULL};
    if (model) {
        resources.write_status = model_write_status;
        resources.read_status = model_read_status;
        resources.write_retention = model_write_retention;
        resources.read_retention = model_read_retention;
    }
    return resources;
}
