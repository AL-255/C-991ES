/* Exact real-number output permission. GPL-3.0-or-later. */
#ifndef FX_MATH_CONTEXT_H
#define FX_MATH_CONTEXT_H
#include <stdint.h>

/* Original18212 for this firmware variant. memory supplies the same64KiB
 * application-state image used by editor/render APIs; no memory is changed.
 * The fixed ROM capability byte at1FFE1 is zero in this variant. */
int fx_exact_output_allowed(const uint8_t memory[65536]);

#endif
