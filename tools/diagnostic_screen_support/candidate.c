/* Test-only transaction recorder and modeled resource fault provider. */
#include "fx_boot_events.h"
#include "../render/fx_render.h"
static unsigned resource_phase, screen_flush_count;
static uint8_t screen_prefix[65536], screen_flush_frames[3*384];
static uint32_t screen_flush_events[3];
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#define DIAGNOSTIC_EVENT_CAPACITY 400000u
static uint8_t events[DIAGNOSTIC_EVENT_CAPACITY * 5u];
static size_t event_count;
static int event_overflow;
static uint8_t candidate_ram[65536];
static fx_platform platform;
static fx_diagnostic_resource_model model;
static fx_diagnostic_resources storage;
static uint32_t status_reads, fault_cycle;
static uint8_t fault_sample, retention_fault;
static fx_diagnostic_rom_status_result result;

static void event(uint8_t kind, uint8_t segment, uint16_t address,
                  uint8_t value)
{
    size_t offset;
    if (event_count >= DIAGNOSTIC_EVENT_CAPACITY) {
        event_overflow = 1;
        return;
    }
    offset = event_count++ * 5u;
    events[offset] = kind;
    events[offset + 1u] = segment;
    events[offset + 2u] = (uint8_t)address;
    events[offset + 3u] = (uint8_t)(address >> 8);
    events[offset + 4u] = value;
}

uint8_t __real_fx_data_read(fx_platform *, uint8_t, uint16_t);
uint8_t __wrap_fx_data_read(fx_platform *p, uint8_t segment, uint16_t address)
{
    uint8_t value = __real_fx_data_read(p, segment, address);
    if (resource_phase) event(1u, segment, address, value);
    return value;
}

static void write_status(void *context, uint8_t value)
{
    (void)context;
    storage.write_status(storage.context, value);
    event(2u, 0u, 0u, model.status);
}

static uint8_t read_status(void *context)
{
    uint8_t value;
    (void)context;
    ++status_reads;
    if (status_reads == fault_cycle) model.status = fault_sample;
    value = storage.read_status(storage.context);
    event(3u, 0u, 0u, value);
    return value;
}

static void write_retention(void *context, uint8_t value)
{
    (void)context;
    storage.write_retention(storage.context, value);
    event(4u, 0u, 0u, model.retention);
}

static uint8_t read_retention(void *context)
{
    uint8_t value;
    (void)context;
    if (retention_fault) model.retention = (uint8_t)(model.retention ^ 1u);
    value = storage.read_retention(storage.context);
    event(5u, 0u, 0u, value);
    return value;
}

int diagnostic_candidate_run(const uint8_t *rom_bytes, size_t rom_size,
                             const uint8_t *ram_bytes, uint8_t initial_status,
                             uint8_t initial_retention, uint32_t fault_at,
                             uint8_t sampled_value, uint8_t corrupt_retention,
                             unsigned callback_mask, unsigned resource_present,
                             unsigned platform_kind)
{
    fx_diagnostic_resources resources;
    fx_platform *input = &platform;
    memcpy(candidate_ram, ram_bytes, sizeof(candidate_ram));
    memset(&platform, 0, sizeof(platform));
    platform.rom = rom_bytes;
    platform.rom_size = rom_size;
    platform.ram = candidate_ram;
    model.status = initial_status;
    model.retention = initial_retention;
    storage = fx_diagnostic_resource_model_bind(&model);
    memset(&resources, 0, sizeof(resources));
    if (callback_mask & 1u) resources.write_status = write_status;
    if (callback_mask & 2u) resources.read_status = read_status;
    if (callback_mask & 4u) resources.write_retention = write_retention;
    if (callback_mask & 8u) resources.read_retention = read_retention;
    event_count = 0;
    event_overflow = 0;
    status_reads = 0;
    fault_cycle = fault_at;
    fault_sample = sampled_value;
    retention_fault = corrupt_retention;
    if (platform_kind == 1u) input = NULL;
    if (platform_kind == 2u) platform.ram = NULL;
    if (platform_kind == 3u) platform.rom = NULL;
    resource_phase=0; screen_flush_count=0;
    memset(screen_prefix,0,sizeof screen_prefix);
    memset(screen_flush_frames,0,sizeof screen_flush_frames);
    memset(screen_flush_events,0,sizeof screen_flush_events);
    result = fx_diagnostic_run_screen(input,
                                         resource_present ? &resources : NULL);
    return (int)result.status;
}

unsigned diagnostic_candidate_value(void) { return result.value; }
unsigned diagnostic_candidate_memory_status(void) { return platform.status; }
unsigned diagnostic_candidate_resource_storage(void)
{
    return (unsigned)model.status | ((unsigned)model.retention << 8);
}
const uint8_t *diagnostic_candidate_events(void) { return events; }
size_t diagnostic_candidate_event_count(void) { return event_count; }
int diagnostic_candidate_overflow(void) { return event_overflow; }
const uint8_t *diagnostic_candidate_ram(void) { return candidate_ram; }

unsigned diagnostic_candidate_storage_roundtrip(uint8_t status,
                                                uint8_t retention)
{
    fx_diagnostic_resource_model local = {0u, 0u};
    fx_diagnostic_resources resources = fx_diagnostic_resource_model_bind(&local);
    uint8_t sampled_status, sampled_retention;
    resources.write_status(resources.context, status);
    resources.write_retention(resources.context, retention);
    sampled_status = resources.read_status(resources.context);
    sampled_retention = resources.read_retention(resources.context);
    return (unsigned)sampled_status | ((unsigned)sampled_retention << 8);
}

int diagnostic_candidate_null_binding(void)
{
    fx_diagnostic_resources resources = fx_diagnostic_resource_model_bind(NULL);
    event_count = 0;
    event_overflow = 0;
    result = fx_diagnostic_rom_status_run(&platform, &resources);
    return (int)result.status;
}

fx_diagnostic_rom_status_result __real_fx_diagnostic_rom_status_run(fx_platform *,const fx_diagnostic_resources *);
fx_diagnostic_rom_status_result __wrap_fx_diagnostic_rom_status_run(fx_platform *p,const fx_diagnostic_resources *r) {
    fx_diagnostic_rom_status_result value;
    memcpy(screen_prefix,p->ram,sizeof screen_prefix);
    resource_phase=1; value=__real_fx_diagnostic_rom_status_run(p,r); resource_phase=0;
    return value;
}
void __real_fx_flush_framebuffer(fx_render *);
void __wrap_fx_flush_framebuffer(fx_render *r) {
    if(screen_flush_count<3) {
        memcpy(screen_flush_frames+384*screen_flush_count,r->memory+0x87d0,384);
        screen_flush_events[screen_flush_count]=(uint32_t)event_count;
    }
    ++screen_flush_count; __real_fx_flush_framebuffer(r);
}
const uint8_t *screen_candidate_prefix(void) {return screen_prefix;}
const uint8_t *screen_candidate_flush_frames(void) {return screen_flush_frames;}
const uint32_t *screen_candidate_flush_events(void) {return screen_flush_events;}
unsigned screen_candidate_flush_count(void) {return screen_flush_count;}
unsigned screen_candidate_callback(void) {return platform.callback_pending;}
void screen_candidate_prepared_label(const uint8_t *rom_bytes,size_t rom_size,const uint8_t *ram_bytes,uint8_t value) {
    memcpy(candidate_ram,ram_bytes,65536);
    memset(&platform,0,sizeof platform);
    platform.rom=rom_bytes; platform.rom_size=rom_size; platform.ram=candidate_ram;
    resource_phase=0; event_count=0; screen_flush_count=0;
    fx_diagnostic_draw_screen(&platform,value);
}
