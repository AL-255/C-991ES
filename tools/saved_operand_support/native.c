/* SPDX-License-Identifier: GPL-3.0-only
 * Original ISA execution exists only in this independent test oracle. */
#include "harness.c"

#define SAVED_EVENT_CAPACITY 1024u
typedef struct {
    uint32_t pc;
    uint16_t argument_address;
    uint8_t depth, data[100];
} saved_event;
saved_event fx_saved_events[SAVED_EVENT_CAPACITY];
unsigned fx_saved_event_count, fx_saved_event_overflow;
unsigned fx_saved_native_steps, fx_saved_native_polls, fx_saved_native_poll_overflow;
uint32_t fx_saved_native_stop_pc;
uint8_t fx_saved_native_poll_data[SAVED_EVENT_CAPACITY][100];

size_t fx_saved_native_abi(unsigned item)
{
    switch (item) {
    case 0: return sizeof(saved_event);
    case 1: return offsetof(saved_event, pc);
    case 2: return offsetof(saved_event, argument_address);
    case 3: return offsetof(saved_event, depth);
    case 4: return offsetof(saved_event, data);
    default: return 0;
    }
}

int fx_saved_native_run(uint16_t cursor_address, uint16_t output,
    uint64_t instruction_limit)
{
    const uint32_t sentinel = 0x2fffe;
    harness_set_reg(0, (uint8_t)cursor_address);
    harness_set_reg(1, (uint8_t)(cursor_address >> 8));
    harness_set_reg(2, (uint8_t)output);
    harness_set_reg(3, (uint8_t)(output >> 8));
    harness_set_sp(0x8dee);
    harness_set_lr(sentinel);
    harness_set_pc(0x171f4);
    fx_saved_event_count = fx_saved_event_overflow = 0;
    fx_saved_native_steps = fx_saved_native_polls = fx_saved_native_poll_overflow = 0;
    int outcome = 103;
    for (uint64_t index = 0; index < instruction_limit; ++index) {
        uint32_t pc = harness_get_pc();
        if (pc == sentinel) { outcome = 100; break; }
        if (pc == 0x5564) {
            /* The authored no-interrupt input acknowledges the real external
             * readiness read; it does not fabricate a completed child call. */
            ram[0x8e00] = 0;
            if (fx_saved_native_polls < SAVED_EVENT_CAPACITY)
                memcpy(fx_saved_native_poll_data[fx_saved_native_polls], ram + 0x8078, 100);
            else ++fx_saved_native_poll_overflow;
            ++fx_saved_native_polls;
        }
        if (pc == 0x1669a || pc == 0x166c4 || pc == 0x166c8 || pc == 0x171ea) {
            if (fx_saved_event_count < SAVED_EVENT_CAPACITY) {
                saved_event *event = &fx_saved_events[fx_saved_event_count];
                event->pc = pc;
                event->argument_address = (uint16_t)(harness_get_reg(2) |
                    (uint16_t)harness_get_reg(3) << 8);
                event->depth = harness_get_reg(11);
                memcpy(event->data, ram + 0x8078, 100);
                ++fx_saved_event_count;
            } else ++fx_saved_event_overflow;
        }
        outcome = harness_run(1, sentinel, false);
        ++fx_saved_native_steps;
        if (outcome != 103) break;
    }
    fx_saved_native_stop_pc = harness_get_pc();
    return outcome;
}
