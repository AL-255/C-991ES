/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_eval_rich_reduce.h"
#include "fx_eval_surd_workspace.h"
#include "../numeric/fx_raw_fraction_convert.h"
#include "../platform/fx_result_classify.h"
#include <string.h>

typedef struct {
    /* Address zero denotes a native private matrix save, not RAM zero. */
    uint16_t address;
    fx_number local[9];
} matrix;
typedef struct {
    fx_eval_rich_result result;
    fx_eval_storage *storage;
    const fx_eval_rich_context *context;
    uint16_t pair;
    fx_numeric_status host;
} reduction;

static void refresh(reduction *w)
{
    if (w->pair) {
        memcpy(&w->result.value,w->storage->ram+w->pair,20);
        memcpy(&w->result.other,w->storage->ram+w->pair+20u,20);
    }
}
static void fail(reduction *w, uint8_t status)
{
    refresh(w);
    fx_number_error(&w->result.value.real,status);
    if (w->pair) memcpy(w->storage->ram+w->pair,&w->result.value.real,10);
    w->result.firmware_status = status;
}
static int stopped(const reduction *w)
{
    return w->host != FX_NUMERIC_OK || w->result.firmware_status;
}
static int poll(reduction *w)
{
    if (fx_eval_rich_poll(w->storage,&w->result.cancellation_checks,w->context)) {
        fail(w,1); return 1;
    }
    return 0;
}
static uint16_t address(const matrix *m, unsigned index)
{
    return m->address ? (uint16_t)(m->address+10u*index) : 0;
}
static fx_number get(const reduction *w, const matrix *m, unsigned index)
{
    fx_number value;
    if (m->address) memcpy(&value,w->storage->ram+address(m,index),10);
    else value = m->local[index];
    return value;
}
static void put(reduction *w, matrix *m, unsigned index, const fx_number *value)
{
    if (m->address) memcpy(w->storage->ram+address(m,index),value,10);
    else m->local[index] = *value;
}
static void put_zero(reduction *w, matrix *m, unsigned index)
{
    fx_number value;
    fx_number_zero(&value); put(w,m,index,&value);
}
static void copy_matrix(reduction *w, matrix *to, const matrix *from)
{
    unsigned index;
    for (index = 0; index < 9; ++index) {
        fx_number value = get(w,from,index); put(w,to,index,&value);
    }
}
/* CCF6 on a copied CPU-local value can unfold an opposite-sign surd at
 * pool0..5 and replace pool0 with its decimal conversion. */
static fx_numeric_status private_classify(reduction *w, uint8_t *classification,
                                          const fx_number *number)
{
    if ((number->bytes[0] & 0xf0u) == 0x80 && number->bytes[9] &&
        (uint8_t)(number->bytes[8]+number->bytes[9]) == 7) {
        fx_number components[6],converted;
        fx_numeric_status status = fx_surd_unpack(components,number);
        if (status == FX_NUMERIC_OK)
            memcpy(w->storage->ram+0x8640u,components,sizeof components);
        if (status == FX_NUMERIC_OK) status = fx_number_to_decimal(&converted,number);
        if (status != FX_NUMERIC_OK) return status;
        memcpy(w->storage->ram+0x8640u,&converted,10);
    }
    return fx_scalar_numeric_classify(classification,number);
}
static void absolute(reduction *w, fx_number *out, const fx_number *input)
{
    uint8_t classification;
    *out = *input;
    w->host = private_classify(w,&classification,input);
    if (w->host != FX_NUMERIC_OK) return;
    if (classification == 0xf0) fx_number_error(out,3);
    else {
        out->bytes[0] &= (uint8_t)~0x40u;
        if (classification == 2) w->host = fx_number_negate(out,out);
    }
}
static int zero(reduction *w, const matrix *m, unsigned index, int tiny)
{
    uint8_t classification;
    fx_number value;
    if (m->address) {
        fx_platform platform = {w->storage->rom,w->storage->rom_size,
            w->storage->ram,0,FX_MEMORY_OK};
        fx_result_classification classified;
        w->host = fx_result_classify_address(&platform,address(m,index),
            (uint16_t)(10u*index),&classified);
        if (w->host != FX_NUMERIC_OK) return 0;
        classification = classified.classification;
    } else {
        value = get(w,m,index);
        w->host = private_classify(w,&classification,&value);
    }
    if (w->host != FX_NUMERIC_OK) return 0;
    if (classification == 1) return 1;
    if (!tiny) return 0;
    /*149D2 copies only after the first classification's workspace writes. */
    value = get(w,m,index);
    absolute(w,&value,&value);
    return w->host == FX_NUMERIC_OK && fx_number_exponent(&value) <= -11;
}
static fx_numeric_status malformed_fraction(fx_number *out,
    const fx_number *a, const fx_number *b, unsigned header)
{
    const fx_number *operand[2] = {a,b};
    unsigned index;
    for (index = 0; index < 2; ++index)
        if ((operand[index]->bytes[0] & 0xf0u) == header) {
            fx_rational fraction;
            fx_number converted;
            fx_numeric_status status;
            if (fx_rational_decode(&fraction,operand[index]) == FX_NUMERIC_OK) continue;
            status = fx_raw_fraction_convert(&converted,operand[index]);
            if (status != FX_NUMERIC_OK) return status;
            if (converted.bytes[0] >= 0xf0) {
                fx_number_error(out,3); return FX_NUMERIC_OK;
            }
            return FX_NUMERIC_UNIMPLEMENTED;
        }
    return FX_NUMERIC_INVALID;
}
static void arithmetic(reduction *w, fx_number *out, const fx_number *a,
    const fx_number *b, fx_binary_op operation, uint16_t physical_a,
    uint16_t physical_b)
{
    /*1C6E0 chooses the surd workspace before its ordinary error predicate. */
    if ((a->bytes[0] & 0xf0u) == 0x80 || (b->bytes[0] & 0xf0u) == 0x80) {
        w->host = fx_eval_surd_workspace_binary(out,w->storage->ram,a,b,
            physical_a,physical_b,operation); return;
    }
    if (a->bytes[0] >= 0xf0 || b->bytes[0] >= 0xf0) {
        fx_number_error(out,3); return;
    }
    w->host = fx_number_binary(out,a,b,operation);
    if (w->host == FX_NUMERIC_INVALID)
        w->host = malformed_fraction(out,a,b,0x60);
}
static void check_number(reduction *w, const fx_number *value)
{
    if (value->bytes[0] >= 0xf0 && (value->bytes[0] & 15u))
        fail(w,value->bytes[0] & 15u);
}
static void divide(reduction *w, fx_number *out, const fx_number *a,
                   const fx_number *b)
{
    fx_number left = *a,right = *b;
    int64_t numerator,denominator;
    left.bytes[0] &= (uint8_t)~0x40u;
    right.bytes[0] &= (uint8_t)~0x40u;
    if (((left.bytes[0] & 0xf0u) != 0 && (left.bytes[0] & 0xf0u) != 0x20) ||
        ((right.bytes[0] & 0xf0u) != 0 && (right.bytes[0] & 0xf0u) != 0x20)) {
        fx_number_error(out,3); return;
    }
    /* CA3E chooses its unchecked rational arithmetic core before scalar
     * conversion. Malformed fractions can return a finite zero through
     * that core even when the standalone fraction converter returns F3.
     * Do not substitute the separately proven scalar-conversion fallback. */
    if ((left.bytes[0] & 0xf0u) == 0x20 || (right.bytes[0] & 0xf0u) == 0x20) {
        fx_rational fraction;
        if (((left.bytes[0] & 0xf0u) == 0x20 &&
             fx_rational_decode(&fraction,&left) != FX_NUMERIC_OK) ||
            ((right.bytes[0] & 0xf0u) == 0x20 &&
             fx_rational_decode(&fraction,&right) != FX_NUMERIC_OK)) {
            w->host = FX_NUMERIC_UNIMPLEMENTED; return;
        }
    }
    /*94EC constructs a fraction only for its bounded integral packer. */
    if (left.bytes[0] < 10 && right.bytes[0] < 10 &&
        fx_number_fractional_status(&left) == 0 &&
        fx_number_fractional_status(&right) == 0 &&
        fx_decimal_to_integer(&numerator,&left) == FX_NUMERIC_OK &&
        fx_decimal_to_integer(&denominator,&right) == FX_NUMERIC_OK && denominator) {
        fx_rational fraction;
        if (denominator < 0) { numerator = -numerator; denominator = -denominator; }
        fraction.numerator = numerator; fraction.denominator = (uint64_t)denominator;
        fraction.flags = 0; w->host = fx_rational_encode(out,&fraction);
    } else {
        arithmetic(w,out,&left,&right,FX_DIVIDE,0,0);
    }
}
static void prepare(reduction *w, matrix *m, unsigned rows, unsigned columns)
{
    unsigned row,column;
    for (row = 0; row < rows; ++row) for (column = 0; column < columns; ++column) {
        unsigned index = row*3u+column;
        fx_number value = get(w,m,index);
        fx_rational fraction;
        if ((value.bytes[0] & 0xf0u) == 0x40) value.bytes[0] &= (uint8_t)~0x40u;
        if (fx_number_recognize_rational(&fraction,&value)) {
            w->host = fx_rational_encode(&value,&fraction);
            if (w->host != FX_NUMERIC_OK) return;
        }
        put(w,m,index,&value);
    }
}
static void swap_rows(reduction *w, matrix *m, unsigned first, unsigned second,
                      unsigned columns)
{
    unsigned column;
    for (column = 0; column < columns; ++column) {
        fx_number a = get(w,m,first*3u+column);
        fx_number b = get(w,m,second*3u+column);
        put(w,m,first*3u+column,&b); put(w,m,second*3u+column,&a);
    }
}
static void lexical_order(reduction *w, matrix *m, unsigned rows, unsigned columns)
{
    unsigned target,column,candidate;
    for (target = 0; target+1 < rows; ++target) {
        int found = 0;
        for (column = 0; column < columns && !found; ++column) {
            for (candidate = target; candidate+1 < rows; ++candidate) {
                int is_zero;
                if (poll(w)) return;
                is_zero = zero(w,m,candidate*3u+column,0);
                if (stopped(w)) return;
                if (!is_zero) { found = 1; break; }
                if (candidate+2 == rows) {
                    is_zero = zero(w,m,(rows-1)*3u+column,0);
                    if (stopped(w)) return;
                    if (!is_zero) { candidate = rows-1; found = 1; break; }
                }
            }
            if (found && candidate != target) swap_rows(w,m,target,candidate,columns);
        }
    }
}
/*15C82 converts copied absolute records in order. Its private destination
 * prevents7576 from replacing pool0, while178BA still writes pool0..5. */
static void compare_prepare(reduction *w, fx_number *value)
{
    if ((value->bytes[0] & 0xf0u) == 0x80) {
        fx_number parts[6],converted;
        w->host = fx_surd_unpack(parts,value);
        if (w->host != FX_NUMERIC_OK) return;
        memcpy(w->storage->ram+0x8640u,parts,sizeof parts);
        w->host = fx_number_to_decimal(&converted,value);
        if (w->host != FX_NUMERIC_OK) return;
        *value = converted;
    }
    if (value->bytes[0] <= 0x4f) {
        fx_rational fraction;
        if ((value->bytes[0] & 0xb0u) == 0x20 &&
            fx_rational_decode(&fraction,value) != FX_NUMERIC_OK) {
            w->host = FX_NUMERIC_UNIMPLEMENTED; return;
        }
        value->bytes[0] &= (uint8_t)~0x40u;
        w->host = fx_number_to_decimal(value,value);
    }
}
static int less(reduction *w, const fx_number *a, const fx_number *b)
{
    fx_number first = *a,second = *b;
    fx_decimal x,y;
    compare_prepare(w,&first);
    if (w->host == FX_NUMERIC_OK) compare_prepare(w,&second);
    if (w->host != FX_NUMERIC_OK) return 0;
    if (fx_decimal_decode(&x,&first) != FX_NUMERIC_OK ||
        fx_decimal_decode(&y,&second) != FX_NUMERIC_OK) return 0;
    if (!x.mantissa) return y.mantissa != 0;
    if (!y.mantissa) return 0;
    return x.exponent != y.exponent ? x.exponent < y.exponent : x.mantissa < y.mantissa;
}
static void magnitude_order(reduction *w, matrix *m, unsigned rows, unsigned columns)
{
    unsigned column,base,next;
    fx_number first,second,input;
    for (column = 0; column < columns; ++column) {
        int is_zero = zero(w,m,column,0);
        if (stopped(w)) return;
        if (!is_zero) break;
    }
    if (column == columns) return;
    for (base = 0; base+1 < rows; ++base) {
restart:
        input = get(w,m,base*3u+column); absolute(w,&first,&input);
        if (stopped(w)) return;
        for (next = base+1; ; ++next) {
            uint8_t classification;
            if (poll(w)) return;
            if (next >= rows) break;
            /*148DA captures the candidate before either classification or
             * absolute conversion writes the shared component workspace. */
            input = get(w,m,next*3u+column);
            w->host = private_classify(w,&classification,&input);
            if (stopped(w) || classification == 1) return;
            absolute(w,&second,&input);
            if (stopped(w)) return;
            if (less(w,&first,&second)) {
                swap_rows(w,m,base,next,columns); goto restart;
            }
            if (stopped(w)) return;
        }
    }
}
static void normalize(reduction *w, matrix *m, unsigned rows, unsigned columns, int tiny)
{
    unsigned row,column;
    fx_number pivot,value;
    for (row = 0; row < rows; ++row) {
        for (column = 0; ; ++column) {
            if (poll(w)) return;
            if (column >= columns) break;
            if (zero(w,m,row*3u+column,tiny)) {
                put_zero(w,m,row*3u+column);
                if (stopped(w)) return;
                continue;
            }
            if (stopped(w)) return;
            pivot = get(w,m,row*3u+column);
            fx_decimal_from_u8(&value,1); put(w,m,row*3u+column,&value);
            for (++column; ; ++column) {
                fx_number input;
                if (poll(w)) return;
                if (column >= columns) break;
                input = get(w,m,row*3u+column); divide(w,&value,&input,&pivot);
                if (w->host != FX_NUMERIC_OK) return;
                put(w,m,row*3u+column,&value); check_number(w,&value);
                if (stopped(w)) return;
            }
            break;
        }
    }
}
static void forward(reduction *w, matrix *m, unsigned rows, unsigned columns);
static void shift_right(reduction *w, matrix *m, unsigned rows, unsigned width,
                        unsigned offset)
{
    unsigned row,remaining,column;
    for (row = 0; row < rows; ++row) {
        for (remaining = width; remaining; --remaining) {
            fx_number value;
            if (poll(w)) return;
            column = remaining-1;
            value = get(w,m,row*3u+column); put(w,m,row*3u+column+offset,&value);
        }
        for (column = 0; column < offset; ++column) put_zero(w,m,row*3u+column);
    }
}
static void leading_columns(reduction *w, matrix *m, unsigned rows, unsigned columns)
{
    unsigned offset,row,column,width;
    if (columns == 1) return;
    for (offset = 1; offset+1 < columns; ++offset) {
        if (!zero(w,m,offset,0)) break;
        if (stopped(w)) return;
    }
    if (stopped(w)) return;
    width = columns-offset;
    for (row = 0; row < rows; ++row) for (column = 0; ; ++column) {
        fx_number value;
        if (poll(w)) return;
        if (column >= width) break;
        value = get(w,m,row*3u+column+offset); put(w,m,row*3u+column,&value);
    }
    forward(w,m,rows,width);
    if (!stopped(w)) shift_right(w,m,rows,width,offset);
}
static void forward(reduction *w, matrix *m, unsigned rows, unsigned columns)
{
    matrix pending = {0,{{{0}}}},scratch = {0,{{{0}}}};
    fx_number first,second,a,b,value;
    unsigned pivot,row,column,index;
    if (columns == 1) {
        if (!zero(w,m,0,0)) {
            if (stopped(w)) return;
            fx_decimal_from_u8(&value,1); put(w,m,0,&value);
        }
        for (row = 1; ; ++row) {
            if (poll(w)) return;
            if (row >= rows) return;
            put_zero(w,m,row*3u);
        }
    }
    if (zero(w,m,0,0)) { leading_columns(w,m,rows,columns); return; }
    if (stopped(w)) return;
    for (pivot = 0; ; ++pivot) {
        if (poll(w)) return;
        if (pivot+1 >= rows || pivot >= columns) return;
        copy_matrix(w,&pending,m);
        if (pivot && zero(w,m,pivot*3u+pivot,0)) {
            unsigned lower_rows = rows-pivot,lower_columns = columns-pivot;
            /*14CE8 copies lower-row prefixes, not a geometric submatrix. */
            for (row = 0; ; ++row) {
                if (poll(w)) return;
                if (row >= lower_rows) break;
                for (column = 0; column < lower_columns; ++column) {
                    value = get(w,m,(row+pivot)*3u+column);
                    put(w,m,row*3u+column,&value);
                }
            }
            leading_columns(w,m,lower_rows,lower_columns);
            if (stopped(w)) return;
            shift_right(w,m,lower_rows,lower_columns,pivot);
            if (stopped(w)) return;
            /*The saved pivot row survives; reduced row zero is skipped. */
            for (row = 1; ; ++row) {
                if (poll(w)) return;
                if (row >= lower_rows) break;
                for (column = 0; column < 3; ++column) {
                    value = get(w,m,row*3u+column);
                    put(w,&pending,(row+pivot)*3u+column,&value);
                }
            }
            copy_matrix(w,m,&pending); return;
        }
        if (stopped(w)) return;
        for (row = pivot+1; row < rows; ++row) {
            for (index = 0; index < 9; ++index) put_zero(w,&scratch,index);
            for (column = pivot+1; ; ++column) {
                if (poll(w)) return;
                if (column >= columns) break;
                a = get(w,m,pivot*3u+pivot); b = get(w,m,row*3u+column);
                arithmetic(w,&first,&a,&b,FX_MULTIPLY,0,address(m,row*3u+column));
                if (stopped(w)) return;
                a = get(w,m,pivot*3u+column); b = get(w,m,row*3u+pivot);
                arithmetic(w,&second,&a,&b,FX_MULTIPLY,0,address(m,row*3u+pivot));
                if (stopped(w)) return;
                arithmetic(w,&value,&first,&second,FX_SUBTRACT,0,0);
                if (w->host != FX_NUMERIC_OK) return;
                put(w,&scratch,column,&value); check_number(w,&value);
                if (stopped(w)) return;
            }
            normalize(w,&scratch,1,columns,1);
            if (stopped(w)) return;
            for (column = 0; column < 3; ++column) {
                value = get(w,&scratch,column); put(w,&pending,row*3u+column,&value);
            }
        }
        if (pivot+2 < columns) {
            lexical_order(w,&pending,rows,columns);
            if (stopped(w)) return;
        }
        copy_matrix(w,m,&pending);
    }
}
static void backward(reduction *w, matrix *m, unsigned rows, unsigned columns)
{
    unsigned row,column,above,next;
    fx_number factor,right,product,value,input;
    for (row = 1; row < rows; ++row) {
        for (column = row; column < columns; ++column) {
            if (!zero(w,m,row*3u+column,0)) break;
            if (stopped(w)) return;
        }
        if (stopped(w)) return;
        if (column >= columns) continue;
        for (above = 0; above < row; ++above) {
            if (zero(w,m,above*3u+column,0)) continue;
            if (stopped(w)) return;
            for (next = column+1; ; ++next) {
                if (poll(w)) return;
                if (next >= columns) break;
                /*14DF6 reloads the upper coefficient after each callback. */
                factor = get(w,m,above*3u+column); right = get(w,m,row*3u+next);
                arithmetic(w,&product,&factor,&right,FX_MULTIPLY,0,
                    address(m,row*3u+next));
                if (stopped(w)) return;
                input = get(w,m,above*3u+next);
                arithmetic(w,&value,&input,&product,FX_SUBTRACT,
                    address(m,above*3u+next),0);
                if (w->host != FX_NUMERIC_OK) return;
                put(w,m,above*3u+next,&value); check_number(w,&value);
                if (stopped(w)) return;
            }
            put_zero(w,m,above*3u+column);
        }
    }
}
static int overlaps(unsigned a, unsigned size, unsigned b, unsigned length)
{
    return a < b+length && b < a+size;
}
fx_numeric_status fx_eval_rich_reduce_after_storage(fx_eval_rich_result *out,
    fx_eval_storage *storage, const fx_complex *current, const fx_complex *other,
    uint8_t selector, const fx_eval_rich_context *context, uint16_t pair)
{
    reduction work;
    matrix cells = {0,{{{0}}}};
    unsigned identity,rows,columns;
    if (!out || !storage || !storage->ram || storage->ram_size != 65536u ||
        !current || !other || !context || context->numeric.exact_math > 1 ||
        context->numeric.digits > 9 ||
        (context->numeric.display_mode != 0 && context->numeric.display_mode != 4 &&
         context->numeric.display_mode != 8 && context->numeric.display_mode != 9) ||
        (selector != 16 && selector != 17 && selector != 21 && selector != 22))
        return FX_NUMERIC_INVALID;
    if (pair && ((pair & 1u) || pair < 0x8000u || pair > 65536u-40u ||
        overlaps(pair,40,0x829e,1440) || overlaps(pair,40,0x80e0,32) ||
        overlaps(pair,40,0x8b00,0x300))) return FX_NUMERIC_UNIMPLEMENTED;
    work.result.value = *current; work.result.other = *other;
    work.result.firmware_status = 0; work.result.cancellation_checks = 0;
    work.storage = storage; work.context = context; work.pair = pair;
    work.host = FX_NUMERIC_OK;
    if (selector == 21 || selector == 22) {
        if ((current->real.bytes[0] & 0xf0u) != 0x90)
            return FX_NUMERIC_UNIMPLEMENTED;
        if (selector == 21) fail(&work,3);
        else {
            /*15A1E's scalar bias addition rejects9x and clears its digit
             * payload.15A56 ignores the error, extracts zero, then NOT
             * serializes signedFFFFFFFF as minus one in contexts6/7. */
            if (context->calculation_context != 6 && context->calculation_context != 7)
                return FX_NUMERIC_UNIMPLEMENTED;
            fx_decimal_from_integer(&work.result.value.real,-1);
            if (pair) memcpy(storage->ram+pair,&work.result.value.real,10);
            refresh(&work);
        }
        *out = work.result; return FX_NUMERIC_OK;
    }
    if ((current->real.bytes[0] & 0xf0u) != 0x60) {
        fail(&work,3); *out = work.result; return FX_NUMERIC_OK;
    }
    identity = current->real.bytes[0] & 15u;
    rows = storage->ram[0x80e0u+2u*identity];
    columns = storage->ram[0x80e1u+2u*identity];
    if (!rows || !columns) {
        fail(&work,9); *out = work.result; return FX_NUMERIC_OK;
    }
    if (rows > 3 || columns > 3) return FX_NUMERIC_UNIMPLEMENTED;
    cells.address = (uint16_t)(0x829eu+90u*identity);
    prepare(&work,&cells,rows,columns);
    if (!stopped(&work)) lexical_order(&work,&cells,rows,columns);
    if (!stopped(&work)) magnitude_order(&work,&cells,rows,columns);
    if (!stopped(&work)) normalize(&work,&cells,rows,columns,0);
    if (!stopped(&work)) forward(&work,&cells,rows,columns);
    if (!stopped(&work) && selector == 17) backward(&work,&cells,rows,columns);
    if (work.host != FX_NUMERIC_OK) return work.host;
    refresh(&work); *out = work.result; return FX_NUMERIC_OK;
}
