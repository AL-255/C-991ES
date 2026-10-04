/* Ordered compact-radical conversion for a prepared physical RAM view.
 * SPDX-License-Identifier: GPL-3.0-or-later
 * No CPU or firmware execution is used by this implementation. */
#ifndef FX_SURD_COMPONENTS_H
#define FX_SURD_COMPONENTS_H
#include "fx_numeric_components.h"

/* Source may be a live ten-byte region within ram. The source field reads
 * occur between each committed component, preserving overlap with 8640..867B.
 * The copy variant snapshots source first, as TABLE 51CA does. */
/* The RAM view is exactly 64 KiB. Live source+9 must remain inside it;
 * unchecked architectural wrapping is outside this prepared facade. */
fx_numeric_status fx_surd_components_emit_live(uint8_t ram[65536],
                                              uint16_t source);
fx_numeric_status fx_surd_components_emit_copy(uint8_t ram[65536],
                                              const fx_number *source);

/* A completed six-component snapshot is safe after emission:17576 performs
 * no further component-pool writes before its final destination commit.
 * The proved active radical domain is positive-tagged packed integers 0..999;
 * aligned canonical source aliases can also produce raw sign2 coefficients.
 * General malformed radicals/unnormalized raw arithmetic remain host gaps.
 * Numerical error records are successful host results. A host arithmetic
 * gap prevents the final numerical output commit: decimal leaves out
 * untouched. Both conversion entries retain prior component emission,
 * including emitted bytes overlapping their output/destination. The final
 * numerical output commit follows all component reads. Output may overlap
 * a completed component or copied source. */
fx_numeric_status fx_surd_components_decimal(fx_number *out,
                                            const fx_number components[6]);
fx_numeric_status fx_surd_components_convert_live(uint8_t ram[65536],
                                                  uint16_t source,
                                                  uint16_t destination);
fx_numeric_status fx_surd_components_convert_copy(uint8_t ram[65536],
                                                  fx_number *out,
                                                  const fx_number *source);
#endif
