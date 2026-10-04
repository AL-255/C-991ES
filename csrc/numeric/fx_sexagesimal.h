/* DMS composition, original unit conversions and constants. GPL-3.0-or-later. */
#ifndef FX_SEXAGESIMAL_H
#define FX_SEXAGESIMAL_H
#include "fx_numeric.h"

/* Counterpart of16A7E with one, two or three prepared scalar components in
 * degree/minute/second order. Components may be signed independently; an
 * expression's outer unary minus belongs to its parser. The result carries
 * the native DMS marker40 when its magnitude is below10^7. */
fx_numeric_status fx_number_sexagesimal(fx_number *out,
                                        const fx_number *components,
                                        size_t count);

/* Counterpart of161AC..161F2, with the already resolved zero-based native
 * conversion selector0..39. Even selectors multiply by a stored factor;
 * odd selectors divide.36/37 apply the Celsius/Fahrenheit offset as well.
 * These are the firmware's stored factors, without modern replacements. */
fx_numeric_status fx_number_unit_convert(fx_number *out, const fx_number *input,
                                         unsigned conversion);

/* Copy one of the original40 scientific-constant records at264A..27DA.
 * Index0..39 is already decoded by the caller. No numeric cleanup is added. */
fx_numeric_status fx_number_scientific_constant(fx_number *out, unsigned index);

/* Inputs are immutable, may alias out, and negative host-status returns
 * leave out unchanged. Native numeric failures use an F-valued record and
 * FX_NUMERIC_OK, as with the other prepared numeric APIs. */
#endif
