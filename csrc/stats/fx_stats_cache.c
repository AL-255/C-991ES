/* Native118b2/118c4 persistent cache copies, with original alias order.
 * GPL-3.0-or-later. */
#include "fx_stats_cache.h"
#include <string.h>

void fx_stats_cache_load(const uint8_t memory[65536], fx_stats_cache *out) {
    uint8_t snapshot[8];
    unsigned chunk;
    uint8_t *destination = (uint8_t *)out;
    /* Ten independently snapshotted8-byte copies, rather than memmove of
     * the whole80-byte region, retain the original behavior for aliases. */
    for (chunk = 0; chunk < 10; ++chunk) {
        memcpy(snapshot, memory + 0x829e + 8*chunk, 8);
        memcpy(destination + 8*chunk, snapshot, 8);
    }
}

void fx_stats_cache_store(uint8_t memory[65536], const fx_stats_cache *cache) {
    uint8_t snapshot[8];
    unsigned chunk;
    const uint8_t *source = (const uint8_t *)cache;
    memory[0x812a] = 1;
    for (chunk = 0; chunk < 10; ++chunk) {
        memcpy(snapshot, source + 8*chunk, 8);
        memcpy(memory + 0x829e + 8*chunk, snapshot, 8);
    }
}
