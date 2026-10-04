/* Readable native C4 integral copy semantics. SPDX-License-Identifier: GPL-3.0-only.
 * Original numeric functions remain scalar, while native transfer helpers
 * copy paired adjacent records. No CPU, ROM execution or host floating point. */
#include "fx_c4_integral_storage.h"
#include "fx_raw_fraction_convert.h"
#include "fx_surd_components.h"
#include <string.h>
/* Immutable native number-table pairs, not executable instructions. */
typedef struct { uint16_t address; uint8_t bytes[20]; } constant_pair;
static const constant_pair constants[] = {
 {0x25f0,{0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x01,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x01}},
 {0x25fa,{0x01,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x01,0x02,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x01}},
 {0x2604,{0x02,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x01,0x03,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x01}},
 {0x2b08,{0x04,0x17,0x95,0x91,0x83,0x67,0x34,0x69,0x99,0x00,0x02,0x09,0x48,0x21,0x41,0x08,0x47,0x28,0x99,0x00}},
 {0x2b12,{0x02,0x09,0x48,0x21,0x41,0x08,0x47,0x28,0x99,0x00,0x09,0x49,0x10,0x79,0x12,0x34,0x27,0x59,0x99,0x00}},
 {0x2b1c,{0x09,0x49,0x10,0x79,0x12,0x34,0x27,0x59,0x99,0x00,0x06,0x30,0x92,0x09,0x26,0x29,0x97,0x86,0x98,0x00}},
 {0x2b26,{0x06,0x30,0x92,0x09,0x26,0x29,0x97,0x86,0x98,0x00,0x01,0x29,0x48,0x49,0x66,0x16,0x88,0x70,0x99,0x00}},
 {0x2b30,{0x01,0x29,0x48,0x49,0x66,0x16,0x88,0x70,0x99,0x00,0x07,0x41,0x53,0x11,0x85,0x59,0x93,0x94,0x99,0x00}},
 {0x2b3a,{0x07,0x41,0x53,0x11,0x85,0x59,0x93,0x94,0x99,0x00,0x01,0x40,0x65,0x32,0x59,0x71,0x55,0x26,0x99,0x00}},
 {0x2b44,{0x01,0x40,0x65,0x32,0x59,0x71,0x55,0x26,0x99,0x00,0x02,0x79,0x70,0x53,0x91,0x48,0x92,0x77,0x99,0x00}},
 {0x2b4e,{0x02,0x79,0x70,0x53,0x91,0x48,0x92,0x77,0x99,0x00,0x04,0x05,0x84,0x51,0x51,0x37,0x73,0x97,0x99,0x00}},
 {0x2b58,{0x04,0x05,0x84,0x51,0x51,0x37,0x73,0x97,0x99,0x00,0x01,0x90,0x35,0x05,0x78,0x06,0x47,0x85,0x99,0x00}},
 {0x2b62,{0x01,0x90,0x35,0x05,0x78,0x06,0x47,0x85,0x99,0x00,0x03,0x81,0x83,0x00,0x50,0x50,0x51,0x19,0x99,0x00}},
 {0x2b6c,{0x03,0x81,0x83,0x00,0x50,0x50,0x51,0x19,0x99,0x00,0x09,0x91,0x45,0x53,0x71,0x12,0x08,0x13,0x99,0x00}},
 {0x2b76,{0x09,0x91,0x45,0x53,0x71,0x12,0x08,0x13,0x99,0x00,0x02,0x29,0x35,0x32,0x20,0x10,0x52,0x92,0x98,0x00}},
 {0x2b80,{0x02,0x29,0x35,0x32,0x20,0x10,0x52,0x92,0x98,0x00,0x08,0x64,0x86,0x44,0x23,0x35,0x97,0x69,0x99,0x00}},
 {0x2b8a,{0x08,0x64,0x86,0x44,0x23,0x35,0x97,0x69,0x99,0x00,0x01,0x04,0x79,0x00,0x10,0x32,0x22,0x50,0x99,0x00}},
 {0x2b94,{0x01,0x04,0x79,0x00,0x10,0x32,0x22,0x50,0x99,0x00,0x05,0x86,0x08,0x72,0x35,0x46,0x76,0x91,0x99,0x00}},
 {0x2b9e,{0x05,0x86,0x08,0x72,0x35,0x46,0x76,0x91,0x99,0x00,0x01,0x69,0x00,0x47,0x26,0x63,0x92,0x68,0x99,0x00}},
 {0x2ba8,{0x01,0x69,0x00,0x47,0x26,0x63,0x92,0x68,0x99,0x00,0x02,0x07,0x78,0x49,0x55,0x00,0x78,0x99,0x99,0x00}},
 {0x2bb2,{0x02,0x07,0x78,0x49,0x55,0x00,0x78,0x99,0x99,0x00,0x02,0x04,0x43,0x29,0x40,0x07,0x52,0x99,0x99,0x00}},
 {0x2bbc,{0x02,0x04,0x43,0x29,0x40,0x07,0x52,0x99,0x99,0x00,0xec,0x23,0xec,0x23,0xd0,0x24,0x9e,0x24,0x54,0x24}},
};

typedef struct {
    fx_calculus_function function;
    void *userdata;
    const fx_calculus_control *control;
    fx_numeric_status host_status;
    unsigned native_error;
} integral_context;

static int numeric_result(integral_context *context, fx_number *value, fx_numeric_status status) {
    if (status != FX_NUMERIC_OK) {
        context->host_status = status;
        return 0;
    }
    if (fx_number_kind(value) == FX_NUMBER_ERROR) {
        context->native_error = 3;
        return 0;
    }
    return 1;
}

static fx_numeric_status binary_record(fx_number *out, const fx_number *a, const fx_number *b, fx_binary_op op) {
    fx_number first, second;
    fx_numeric_status status;
    /* AB64 clears bit40 on every non-F header before scalar dispatch.
    * Consequently a surviving61 reference uses its raw rational payload;
    * this is distinct from15C82, which rejects the unmasked header. */
    if ((fx_number_kind(a) != FX_NUMBER_DECIMAL && fx_number_kind(a) != FX_NUMBER_RATIONAL) || (fx_number_kind(b) != FX_NUMBER_DECIMAL && fx_number_kind(b) != FX_NUMBER_RATIONAL)) {
        fx_number_error(out, 3);
        return FX_NUMERIC_OK;
    }
    /* Ordinary scalar wrappers load rational components as decimals before
    * operating; they do not use the exact rational arithmetic dispatcher. */
    if (fx_number_kind(a) == FX_NUMBER_RATIONAL) {
        status = fx_raw_fraction_convert(&first, a);
        if (status != FX_NUMERIC_OK) return status;
        first.bytes[0] |= a->bytes[0] & 0x40;
        a = &first;
    }
    if (fx_number_kind(b) == FX_NUMBER_RATIONAL) {
        status = fx_raw_fraction_convert(&second, b);
        if (status != FX_NUMERIC_OK) return status;
        second.bytes[0] |= b->bytes[0] & 0x40;
        b = &second;
    }
    if (fx_number_kind(a) == FX_NUMBER_ERROR || fx_number_kind(b) == FX_NUMBER_ERROR) {
        fx_number_error(out, 3);
        return FX_NUMERIC_OK;
    }
    return op == FX_SUBTRACT ? fx_decimal_subtract_cancel(out, a, b) : fx_decimal_binary(out, a, b, op);
}

static int cleanup(integral_context *context, fx_number *value) {
    return numeric_result(context, value, fx_decimal_integer_cleanup(value));
}

static int decimal(integral_context *context, fx_number *out, const fx_number *in) {
    fx_number value = *in;
    if (fx_number_kind(&value) == FX_NUMBER_SURD && !numeric_result(context, &value, fx_number_to_decimal(&value, &value))) return 0;
    if (value.bytes[0] > 0x4f) {
        context->native_error = 3;
        return 0;
    }
    /*15c82 clears the scalar metadata after radical/rational conversion. */
    value.bytes[0] &= (uint8_t)~0x40;
    return numeric_result(context, out, fx_number_to_decimal(out, &value));
}

static int absolute(integral_context *context, fx_number *value) {
    fx_decimal decoded;
    value->bytes[0] &= (uint8_t)~0x40;
    if (fx_decimal_decode(&decoded, value) != FX_NUMERIC_OK) {
        context->host_status = FX_NUMERIC_INVALID;
        return 0;
    }
    if (decoded.sign < 0) return numeric_result(context, value, fx_number_negate(value, value));
    return 1;
}
/* 1CD60/1CD94: 1 equal, 2 less, 4 greater, F0 invalid. The raw
* header admission test precedes arithmetic and does not convert RAT/SURD.
* Malformed admitted decimal encodings remain a bounded host gap. */

static int compare(integral_context *context,const fx_number *a,const fx_number *b,int cancel) {
    fx_decimal x, y, difference;
    fx_number residue;
    if(a->bytes[0]>=10 || b->bytes[0]>=10)return 0xf0;
    if(fx_decimal_decode(&x,a)!=FX_NUMERIC_OK || fx_decimal_decode(&y,b)!=FX_NUMERIC_OK) {
        context->host_status=FX_NUMERIC_UNIMPLEMENTED;
        return 0xf0;
    }
    if (x.sign != y.sign) return x.sign < y.sign ? 2 : 4;
    if (!x.sign) return 1;
    fx_numeric_status status=cancel ? fx_decimal_subtract_cancel(&residue,a,b) : fx_decimal_binary(&residue,a,b,FX_SUBTRACT);
    if(status!=FX_NUMERIC_OK || fx_decimal_decode(&difference,&residue)!=FX_NUMERIC_OK) {
        context->host_status=FX_NUMERIC_UNIMPLEMENTED;
        return 0xf0;
    }
    return difference.sign<0 ? 2 : difference.sign>0 ? 4 : 1;
}

static int poll(integral_context *context) {
    if (context->control && context->control->cancelled && context->control->cancelled(context->control->userdata)) {
        context->native_error = 1;
        return 0;
    }
    return 1;
}


enum {
    LOWER=0x850a,UPPER=0x8514,TOL=0x851e,LEFT=0x8528,RIGHT=0x8532,
    TOTAL=0x8546,INDEX=0x855a,DENOM=0x8564,SPAN=0x8578,HALF=0x8582,
    CENTER=0x858c,ERROR=0x8596,RESULT=0x85a0,PAIR=0x85aa,WORK=0x85b4,
    FINAL_CURSOR=0x85c8,BUDGET=0x85ca,DEPTH=0x85cd
};
static int storage_valid(const fx_integral_storage *s) {
    return s && s->ram && s->ram_size == 65536u;
}
static int paired_context(const fx_integral_storage *s) {
    return s->ram[0x80f9] == 0xc4;
}
static int overlaps_ram(const fx_integral_storage *s,const void *object,size_t size) {
    uintptr_t address=(uintptr_t)object,base=(uintptr_t)s->ram;
    return address>=base ? address-base<65536u : base-address<size;
}
static const uint8_t *constant_at(uint16_t address) {
    for (size_t i=0;i<sizeof constants/sizeof constants[0];++i)
        if (constants[i].address==address) return constants[i].bytes;
    return NULL;
}
/* Each real transfer finishes before a live companion is read. In particular
 * a destination one record above the source duplicates the old real value. */
static void copy_pair(fx_integral_storage *s,unsigned dst,unsigned src) {
    fx_number value;
    memcpy(&value,s->ram+src,10);
    memcpy(s->ram+dst,&value,10);
    if (paired_context(s)) {
        memcpy(&value,s->ram+src+10u,10);
        memcpy(s->ram+dst+10u,&value,10);
    }
}
static void copy_named_pair(fx_integral_storage *s,unsigned dst,const fx_complex *input) {
    memcpy(s->ram+dst,&input->real,10);
    if (paired_context(s)) memcpy(s->ram+dst+10u,&input->imaginary,10);
}
static void copy_constant(fx_integral_storage *s,unsigned dst,uint16_t address) {
    const uint8_t *value=constant_at(address);
    memcpy(s->ram+dst,value,10);
    if (paired_context(s)) memcpy(s->ram+dst+10u,value+10,10);
}
static fx_numeric_status prepare_record(fx_integral_storage *s,fx_number *out,
                                       const fx_number *input) {
    fx_number value=*input;
    fx_numeric_status status;
    if (fx_number_kind(&value)==FX_NUMBER_SURD) {
        status=fx_surd_components_convert_copy(s->ram,&value,&value);
        if (status!=FX_NUMERIC_OK) return status;
    }
    if (value.bytes[0]>0x4f) { *out=value;return FX_NUMERIC_OK; }
    value.bytes[0]&=(uint8_t)~0x40u;
    status=(value.bytes[0]&0xb0u)==0x20u ?
        fx_raw_fraction_convert(out,&value):fx_number_to_decimal(out,&value);
    if (status==FX_NUMERIC_OK && fx_number_kind(out)!=FX_NUMBER_ERROR)
        out->bytes[0]&=(uint8_t)~0x40u;
    return status;
}
static fx_numeric_status prepare_bound(fx_integral_storage *s,
                                       const fx_complex *input,unsigned dst) {
    fx_complex value;
    if (!storage_valid(s)||!input) return FX_NUMERIC_INVALID;
    if (!paired_context(s)) return FX_NUMERIC_UNIMPLEMENTED;
    value=*input;
    fx_numeric_status status=prepare_record(s,&value.real,&value.real);
    if (status==FX_NUMERIC_OK) copy_named_pair(s,dst,&value);
    return status;
}
fx_numeric_status fx_c4_integral_lower(fx_integral_storage *s,const fx_complex *input) {
    return prepare_bound(s,input,LOWER);
}
fx_numeric_status fx_c4_integral_upper(fx_integral_storage *s,const fx_complex *input) {
    return prepare_bound(s,input,UPPER);
}
fx_numeric_status fx_c4_integral_tolerance(fx_integral_storage *s,
    const fx_complex *input,uint16_t cursor,unsigned *native_status) {
    fx_complex value;
    uint8_t classification;
    if (!storage_valid(s)||!native_status) return FX_NUMERIC_INVALID;
    if (!paired_context(s)) return FX_NUMERIC_UNIMPLEMENTED;
    if (input) {
        value=*input;
        fx_numeric_status status=prepare_record(s,&value.real,&value.real);
        if (status!=FX_NUMERIC_OK) return status;
        status=fx_scalar_numeric_classify(&classification,&value.real);
        if (status!=FX_NUMERIC_OK) return status;
        if (classification==2) { *native_status=8;return FX_NUMERIC_OK; }
    } else {
        memcpy(&value,constant_at(0x25fa),20);
        value.real.bytes[8]=0x95;value.real.bytes[9]=0;
    }
    copy_named_pair(s,TOL,&value);
    s->ram[FINAL_CURSOR]=(uint8_t)cursor;s->ram[FINAL_CURSOR+1]=(uint8_t)(cursor>>8);
    *native_status=0;return FX_NUMERIC_OK;
}

typedef struct {
    integral_context math;
    fx_integral_storage *storage;
    fx_complex *out;
    fx_c4_integral_function function;
    fx_c4_integral_publish publish;
    uint16_t *cursor;
    uint16_t output_address,callback_sink;
    fx_integral_storage_callback_context callback_context;
} paired_integral;
static fx_number load(paired_integral *c,unsigned address) {
    fx_number value;memcpy(&value,c->storage->ram+address,10);return value;
}
static void store(paired_integral *c,unsigned address,const fx_number *value) {
    memcpy(c->storage->ram+address,value,10);
}
static int calculate(paired_integral *c,unsigned dst,const fx_number *a,
    const fx_number *b,fx_binary_op operation,int checked) {
    fx_number value;
    fx_numeric_status status=binary_record(&value,a,b,operation);
    if (status!=FX_NUMERIC_OK) { c->math.host_status=status;return 0; }
    store(c,dst,&value);
    return !checked||numeric_result(&c->math,&value,status);
}
static int records(paired_integral *c,unsigned dst,unsigned a,unsigned b,
                   fx_binary_op operation,int checked) {
    fx_number left=load(c,a),right=load(c,b);
    return calculate(c,dst,&left,&right,operation,checked);
}
static int constant(paired_integral *c,unsigned dst,const fx_number *b,
                    fx_binary_op operation) {
    fx_number a=load(c,dst);return calculate(c,dst,&a,b,operation,1);
}
static int clean_record(paired_integral *c,unsigned address) {
    fx_number value=load(c,address);
    fx_numeric_status status=fx_decimal_integer_cleanup(&value);
    if (status!=FX_NUMERIC_OK) { c->math.host_status=status;return 0; }
    store(c,address,&value);return numeric_result(&c->math,&value,status);
}
static int decimal_record(paired_integral *c,unsigned address) {
    fx_number value=load(c,address),result;
    if (!decimal(&c->math,&result,&value)) return 0;
    store(c,address,&result);return 1;
}
static int abs_record(paired_integral *c,unsigned address) {
    fx_number value=load(c,address);
    if (!absolute(&c->math,&value)) return 0;
    store(c,address,&value);return 1;
}
static int sample(paired_integral *c,unsigned address) {
    fx_complex x;
    memcpy(&x,c->storage->ram+address,20);
    if (c->publish) c->publish(&x,c->math.userdata);
    if (c->callback_context)
        c->callback_context(c->callback_sink,c->cursor,c->math.userdata);
    fx_numeric_status status=c->function(c->out,&x,c->math.userdata);
    if ((int)status==FX_CALCULUS_EVALUATION_ERROR) {
        c->math.native_error=3;return 0;
    }
    if ((int)status==FX_CALCULUS_EVALUATION_OK) {
        if (fx_number_kind(&c->out->real)==FX_NUMBER_ERROR) return 1;
        status=FX_NUMERIC_OK;
    }
    if (!numeric_result(&c->math,&c->out->real,status)) return 0;
    if (fx_number_kind(&c->out->real)==FX_NUMBER_SURD)
        return numeric_result(&c->math,&c->out->real,
            fx_number_to_decimal(&c->out->real,&c->out->real));
    return 1;
}
static int pair_samples(paired_integral *c,uint16_t node) {
    c->callback_sink=node;
    copy_constant(c->storage,PAIR,node);
    if (!records(c,PAIR,PAIR,HALF,FX_MULTIPLY,1)) return 0;
    copy_pair(c->storage,WORK,PAIR);
    if (!records(c,PAIR,PAIR,CENTER,FX_SUBTRACT,1)) return 0;
    fx_number value=load(c,PAIR);
    if (!numeric_result(&c->math,&value,fx_number_negate(&value,&value))) return 0;
    store(c,PAIR,&value);
    if (!sample(c,PAIR)) return 0;
    copy_named_pair(c->storage,PAIR,c->out);
    c->callback_sink=(uint16_t)(node|1u);
    if (!records(c,WORK,WORK,CENTER,FX_ADD,1)||!sample(c,WORK)) return 0;
    value=load(c,PAIR);
    return calculate(c,PAIR,&value,&c->out->real,FX_ADD,1)&&clean_record(c,PAIR);
}
static int weighted(paired_integral *c,unsigned sum,uint16_t weight) {
    copy_constant(c->storage,WORK,weight);
    return records(c,WORK,WORK,PAIR,FX_MULTIPLY,1)&&
           records(c,sum,sum,WORK,FX_ADD,1);
}
static int quadrature(paired_integral *c) {
    fx_number two;fx_decimal_from_u8(&two,2);
    c->callback_sink=c->output_address;
    copy_pair(c->storage,HALF,RIGHT);
    if (!records(c,HALF,HALF,LEFT,FX_SUBTRACT,1)||
        !constant(c,HALF,&two,FX_DIVIDE)) return 0;
    uint8_t classification;
    fx_number half=load(c,HALF);
    fx_numeric_status status=fx_scalar_numeric_classify(&classification,&half);
    if (status!=FX_NUMERIC_OK) { c->math.host_status=status;return 0; }
    if (classification==1||classification==0xf0) { c->math.native_error=3;return 0; }
    copy_pair(c->storage,CENTER,RIGHT);
    if (!records(c,CENTER,CENTER,LEFT,FX_ADD,1)||
        !constant(c,CENTER,&two,FX_DIVIDE)||!sample(c,CENTER)) return 0;
    copy_constant(c->storage,ERROR,0x2b08);
    fx_number value=load(c,ERROR);
    if (!calculate(c,ERROR,&value,&c->out->real,FX_MULTIPLY,0)) return 0;
    copy_constant(c->storage,RESULT,0x2b12);
    value=load(c,RESULT);
    if (!calculate(c,RESULT,&value,&c->out->real,FX_MULTIPLY,0)) return 0;
    for (unsigned i=0;i<3;++i) {
        uint16_t node=(uint16_t)(0x2b1c+30u*i);
        if (!poll(&c->math)||!pair_samples(c,node)||
            !weighted(c,RESULT,(uint16_t)(node+10u))||
            !weighted(c,ERROR,(uint16_t)(node+20u))) return 0;
    }
    for (unsigned i=0;i<4;++i) {
        uint16_t node=(uint16_t)(0x2b76+20u*i);
        if (!poll(&c->math)||!pair_samples(c,node)||
            !weighted(c,RESULT,(uint16_t)(node+10u))) return 0;
    }
    return clean_record(c,ERROR)&&decimal_record(c,ERROR)&&
        records(c,ERROR,ERROR,HALF,FX_MULTIPLY,1)&&
        clean_record(c,RESULT)&&decimal_record(c,RESULT)&&
        records(c,RESULT,RESULT,HALF,FX_MULTIPLY,1)&&
        records(c,ERROR,ERROR,RESULT,FX_SUBTRACT,1)&&
        abs_record(c,ERROR)&&clean_record(c,ERROR);
}
fx_numeric_status fx_c4_integral_run(fx_complex *out,fx_integral_storage *s,
    fx_c4_integral_function function,void *userdata,fx_c4_integral_publish publish,
    uint16_t output_address,fx_integral_storage_callback_context callback_context,
    const fx_calculus_control *control,unsigned *native_status,uint16_t *cursor) {
    if (!out||!storage_valid(s)||!function||!native_status||!cursor)
        return FX_NUMERIC_INVALID;
    if (!paired_context(s)) return FX_NUMERIC_UNIMPLEMENTED;
    if (overlaps_ram(s,out,sizeof *out)||overlaps_ram(s,native_status,sizeof *native_status)||
        overlaps_ram(s,cursor,sizeof *cursor)) return FX_NUMERIC_INVALID;
    paired_integral c={{NULL,userdata,control,FX_NUMERIC_OK,0},s,out,function,
        publish,cursor,output_address,output_address,callback_context};
    fx_number lower=load(&c,LOWER),upper=load(&c,UPPER);
    int decision=compare(&c.math,&lower,&upper,1);
    if (c.math.host_status!=FX_NUMERIC_OK) return c.math.host_status;
    if (decision==1) {
        if (!sample(&c,UPPER)||!sample(&c,LOWER)) goto done;
        memcpy(out,constant_at(0x25f0),20);
        if (!cleanup(&c.math,&out->real)) goto done;
        *native_status=0;
        *cursor=(uint16_t)(s->ram[FINAL_CURSOR]|s->ram[FINAL_CURSOR+1]<<8);
        return FX_NUMERIC_OK;
    }
    if (!sample(&c,LOWER)||!sample(&c,UPPER)) goto done;
    copy_pair(s,LEFT,LOWER);copy_pair(s,RIGHT,UPPER);
    copy_constant(s,TOTAL,0x25f0);copy_constant(s,INDEX,0x25fa);
    copy_constant(s,DENOM,0x25fa);
    s->ram[DEPTH]=47;s->ram[BUDGET]=0x44;s->ram[BUDGET+1]=1;
    copy_pair(s,SPAN,UPPER);
    if (!records(&c,SPAN,SPAN,LOWER,FX_SUBTRACT,1)||!quadrature(&c)) goto done;
    /*04696 allocates a ten-byte mathematical threshold, but169F4 copies
     * twenty into it inC4 and overwrites native locals/return state. The
     * partial storage/callback prefix is meaningful; a CPU-frame emulator
     * would be required to continue this particular original execution. */
    return FX_NUMERIC_UNIMPLEMENTED;
done:
    if (c.math.host_status!=FX_NUMERIC_OK) return c.math.host_status;
    *native_status=c.math.native_error?c.math.native_error:3;
    if (*native_status==1)
        *cursor=(uint16_t)(s->ram[FINAL_CURSOR]|s->ram[FINAL_CURSOR+1]<<8);
    return FX_NUMERIC_OK;
}
