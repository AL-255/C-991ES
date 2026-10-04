/* Test-only passive observer around the unmodified original CPU core. */
#define memoryGetData diagnostic_base_memory_get_data
#include "nxu8/harness.c"
#undef memoryGetData

#define DIAGNOSTIC_EVENT_CAPACITY 400000u
static uint8_t diagnostic_events[DIAGNOSTIC_EVENT_CAPACITY * 5u];
static size_t diagnostic_event_count;
static int diagnostic_overflow;

static void diagnostic_event(uint8_t kind, uint8_t segment,
                             uint16_t address, uint8_t value)
{
    size_t offset;
    if (diagnostic_event_count >= DIAGNOSTIC_EVENT_CAPACITY) {
        diagnostic_overflow = 1;
        return;
    }
    offset = diagnostic_event_count++ * 5u;
    diagnostic_events[offset] = kind;
    diagnostic_events[offset + 1u] = segment;
    diagnostic_events[offset + 2u] = (uint8_t)address;
    diagnostic_events[offset + 3u] = (uint8_t)(address >> 8);
    diagnostic_events[offset + 4u] = value;
}

uint64_t memoryGetData(SR_t segment, EA_t offset, size_t size)
{
    uint64_t value = diagnostic_base_memory_get_data(segment, offset, size);
    if ((last_address == 0x7344u || last_address == 0x7362u) && size == 1u)
        diagnostic_event(1u, (uint8_t)segment, (uint16_t)offset,
                         (uint8_t)value);
    return value;
}

void diagnostic_native_seed(uint8_t status)
{
    /* Input-only setup, called before the first original instruction. */
    PSW.raw = status;
    diagnostic_event_count = 0;
    diagnostic_overflow = 0;
}

int diagnostic_native_run(uint64_t limit, uint32_t stop)
{
    uint64_t i;
    for (i = 0; i < limit; ++i) {
        uint32_t address = harness_get_pc();
        CORE_STATUS status;
        if (address == stop) return 100;
        if (address >= sizeof(rom)) return 101;
        last_address = address;
        ++execution_counts[address >> 1];
        if (address == 0x734au || address == 0x7368u)
            diagnostic_event(3u, 0u, 0u, PSW.raw);
        if (address == 0x7374u)
            diagnostic_event(5u, 0u, 0u, GR.rs[9]);
        status = coreStep();
        if (address == 0x7348u || address == 0x7366u)
            diagnostic_event(2u, 0u, 0u, PSW.raw);
        if (address == 0x7356u)
            diagnostic_event(4u, 0u, 0u, GR.rs[9]);
        if (status != CORE_OK) return status;
    }
    return 103;
}

const uint8_t *diagnostic_native_events(void) { return diagnostic_events; }
size_t diagnostic_native_event_count(void) { return diagnostic_event_count; }
int diagnostic_native_overflow(void) { return diagnostic_overflow; }
unsigned diagnostic_native_status(void) { return PSW.raw; }
