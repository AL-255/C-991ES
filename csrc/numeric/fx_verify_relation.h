/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef FX_VERIFY_RELATION_H
#define FX_VERIFY_RELATION_H
#include "fx_numeric.h"

/* Prepared18A02..18AE6 scalar predicate. RawINPUT relation tokens are
 *94<=,95!=,96>=,3C<,3D=,3E>. The Boolean replaces the prepared left
 *record; native_status/truth are separate from the host return status.
 *Copy/preparation is right-first, then left. Canonical decimal/marked
 *decimal, rational, compactSURD andF* fields are admitted. Other raw
 *field formats remain explicit host gaps. Optional ram holds the ordered
 *compactSURD component pool; it is disjoint from the named record fields.
 *Input/output record aliases work. Neither arbitrary physical address
 *alignment nor original CPU frame aliases are part of this value API.
 *Output,truth,native_status use separate storage. */
fx_numeric_status fx_verify_relation(fx_number *out,
    const fx_number *left, const fx_number *right, uint8_t token,
    uint8_t ram[65536], uint8_t *truth, unsigned *native_status);
#endif
