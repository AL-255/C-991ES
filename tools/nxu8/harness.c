/* Instrumented, headless firmware harness. GPL-3.0; see COPYING.
 * CPU: unmodified LifeEmu/SimU8 core. Memory: ROM window, RAM, ROM aliases.
 * Peripherals are passive RAM; whole-calculator behavior is not asserted.
 */
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <stdio.h>
#include "vendor/SimU8/core.h"
#include "vendor/SimU8/mmu.h"

static uint8_t rom[0x30000], ram[0x10000];
static size_t rom_size;
void *CodeMemory = rom, *DataMemory = ram;
bool IsMemoryInited = true;
MEMORY_STATUS MemoryStatus = MEMORY_OK;
unsigned int ROMWinAccessCount;
uint64_t execution_counts[0x18000], rom_read_counts[0x30000], ram_write_counts[0x10000];
static uint32_t callback_pending;
static uint32_t last_address;
static FILE *trace_file;
static uint64_t trace_index;
static bool trace_reads;

int harness_trace_open(const char *path, bool reads) {
    if (trace_file) fclose(trace_file);
    trace_file = fopen(path, "w");
    trace_index = 0; trace_reads = reads;
    return trace_file ? 0 : -1;
}
void harness_trace_close(void) {
    if (trace_file) fclose(trace_file);
    trace_file = NULL;
}

uint16_t memoryGetCodeWord(SR_t segment, PC_t offset) {
    uint32_t address = ((segment & 0xF) << 16) | (offset & 0xFFFE);
    MemoryStatus = MEMORY_OK;
    if (address + 1 >= rom_size) return 0xFFFF;
    return rom[address] | (rom[address + 1] << 8);
}

uint64_t memoryGetData(SR_t segment, EA_t offset, size_t size) {
    uint64_t value = 0;
    MemoryStatus = MEMORY_OK;
    for (size_t i = 0; i < size; ++i) {
        uint16_t pos = (offset + i) & 0xFFFF;
        uint32_t address = ((uint32_t)segment << 16) | pos;
        uint8_t byte = 0;
        if (!segment && pos >= 0x8000) byte = ram[pos];
        else {
            if (segment >= 8 && segment <= 9) address -= 0x80000;
            if (address < rom_size) { byte = rom[address]; ++rom_read_counts[address]; }
            else MemoryStatus = MEMORY_UNMAPPED;
        }
        value |= (uint64_t)byte << (i * 8);
    }
    if (trace_file && trace_reads)
        fprintf(trace_file, "R,%llu,%06x,%02x,%04x,%zu,%016llx\n",
                (unsigned long long)trace_index, last_address, segment, offset,
                size, (unsigned long long)value);
    return value;
}

void memorySetData(SR_t segment, EA_t offset, size_t size, uint64_t value) {
    if (trace_file)
        fprintf(trace_file, "W,%llu,%06x,%02x,%04x,%zu,%016llx\n",
                (unsigned long long)trace_index, last_address, segment, offset,
                size, (unsigned long long)value);
    MemoryStatus = MEMORY_OK;
    for (size_t i = 0; i < size; ++i) {
        uint16_t pos = (offset + i) & 0xFFFF;
        if (!segment && pos >= 0x8000) {
            ram[pos] = (value >> (i * 8)) & 0xFF;
            ++ram_write_counts[pos];
            if (pos == 0xF000 && ram[pos]) callback_pending = ram[pos];
        } else MemoryStatus = MEMORY_READ_ONLY;
    }
}

void harness_init(const uint8_t *bytes, size_t size) {
    rom_size = size < sizeof(rom) ? size : sizeof(rom);
    memset(rom, 0, sizeof(rom)); memcpy(rom, bytes, rom_size);
    memset(ram, 0, sizeof(ram));
    memset(execution_counts, 0, sizeof(execution_counts));
    memset(rom_read_counts, 0, sizeof(rom_read_counts));
    memset(ram_write_counts, 0, sizeof(ram_write_counts));
    callback_pending = 0;
    coreZero(); coreReset();
}
void harness_set_pc(uint32_t address) { PC = address & 0xFFFF; CSR = address >> 16; }
uint32_t harness_get_pc(void) { return ((uint32_t)CSR << 16) | PC; }
void harness_set_reg(unsigned index, uint8_t value) { if (index < 16) GR.rs[index] = value; }
uint8_t harness_get_reg(unsigned index) { return index < 16 ? GR.rs[index] : 0; }
void harness_set_sp(uint16_t value) { SP = value; }
uint16_t harness_get_sp(void) { return SP; }
void harness_set_lr(uint32_t address) { LR = address & 0xFFFF; LCSR = address >> 16; }
uint8_t *harness_ram(void) { return ram; }
uint32_t harness_callback(void) { uint32_t value = callback_pending; callback_pending = 0; return value; }
uint32_t harness_last_address(void) { return last_address; }
int harness_run(uint64_t limit, uint32_t stop, bool stop_callback) {
    for (uint64_t i = 0; i < limit; ++i) {
        uint32_t address = harness_get_pc();
        if (address == stop) return 100;
        if (address >= sizeof(rom)) return 101;
        last_address = address;
        if (trace_file) {
            ++trace_index;
            fprintf(trace_file, "I,%llu,%06x,%04x,%04x,%02x,%02x,%06x,",
                    (unsigned long long)trace_index, address, SP, EA, DSR, PSW.raw,
                    ((uint32_t)LCSR << 16) | LR);
            for (unsigned n = 0; n < 16; ++n) fprintf(trace_file, "%02x", GR.rs[n]);
            fputc('\n', trace_file);
        }
        ++execution_counts[address >> 1];
        CORE_STATUS status = coreStep();
        if (status != CORE_OK) return status;
        if (stop_callback && callback_pending) return 102;
    }
    return 103;
}
