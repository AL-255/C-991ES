/* Statistics table editing and evaluated-input commits. GPL-3.0-or-later. */
#ifndef FX_STATS_EDITOR_H
#define FX_STATS_EDITOR_H
#include "../platform/fx_platform.h"

/* Original5110 column policy, including the nonstatistics table contexts. */
uint8_t fx_stats_editor_columns(fx_platform *platform);
/* Original5096 bus output parameter. Raw selectors0/1/2 address x/y/frequency;
 * selector3 addresses trailing reserved records. Raw row0 wraps to255 after
 * decrement, as in firmware. Output-pointer alias effects are retained. */
int fx_stats_editor_address_raw(fx_platform *platform, uint8_t selector,
                                uint8_t row, uint16_t output_address);
/* Checked statistics UI lookup requires80F9=3 and uses one-based columns/rows.
 * Invalid UI rows/columns return2 and write a zero host address. */
int fx_stats_editor_address_checked(fx_platform *platform, uint8_t column,
                                    uint8_t row, uint16_t *address);
/* Original1D66C/1D6AC: five descending independently snapshotted word copies.
 * Memory addresses use the platform data bus; aliases are supported except
 * aliases into the native CPU stack, which is not part of this implementation. */
int fx_stats_editor_write_raw(fx_platform *platform, uint8_t selector,
                              uint8_t row, uint16_t source_address);
int fx_stats_editor_read_raw(fx_platform *platform, uint8_t selector,
                             uint8_t row, uint16_t destination_address);
/* Native1D426: capacity failure1 takes precedence over invalid row2.
 * Insertion initializes x/y to zero and frequency to one. Insert/delete do
 * not invalidate the moment cache; the invoking UI controller owns that. */
int fx_stats_editor_insert(fx_platform *platform, uint8_t row);
int fx_stats_editor_delete(fx_platform *platform, uint8_t row);
/* Native1D60A clears STAT data and cursor/cache state; other contexts return
 * their mode byte unchanged and preserve memory. */
int fx_stats_editor_clear(fx_platform *platform);
/* Original0E450 cursor movement. E0/E1 up/down, E2/E3 right/left, ED commit
 * advance. Return0 for movement and1 for an unchanged selection. */
int fx_stats_editor_move(fx_platform *platform, uint8_t key);
/* Native0E680 STAT-input branch, with evaluated input at a data-bus address.
 * Requires80F9=3 and80FC=18; otherwise returns-1 without mutation. Returns3
 * as the native UI state, rather than a numeric error status. */
int fx_stats_editor_commit(fx_platform *platform, uint16_t input_address);
#endif
