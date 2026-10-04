/* RAM-backed real finite-decimal Gauss-Kronrod integration.
* GPL-3.0-or-later. No CPU, firmware execution or host floating point. */
#include "fx_integral_storage.h"
#include "fx_raw_fraction_convert.h"
#include "fx_surd_components.h"
#include <string.h>
/* Original fifteen-digit nodes/weights, ROM2b08..2bbc. Keeping the stored
* constants and their evaluation order is necessary for numeric parity. */

static const fx_number gauss_center = {
    {
        0x04,0x17,0x95,0x91,0x83,0x67,0x34,0x69,0x99,0x00
    }
};

static const fx_number kronrod_center = {
    {
        0x02,0x09,0x48,0x21,0x41,0x08,0x47,0x28,0x99,0x00
    }
};

typedef struct {
    fx_number node, kronrod, gauss;
} common_node;

static const common_node common_nodes[3] = {
    {
        {
            {
                0x09,0x49,0x10,0x79,0x12,0x34,0x27,0x59,0x99,0x00
            }
        }, {
            {
                0x06,0x30,0x92,0x09,0x26,0x29,0x97,0x86,0x98,0x00
            }
        }, {
            {
                0x01,0x29,0x48,0x49,0x66,0x16,0x88,0x70,0x99,0x00
            }
        }
    }, {
        {
            {
                0x07,0x41,0x53,0x11,0x85,0x59,0x93,0x94,0x99,0x00
            }
        }, {
            {
                0x01,0x40,0x65,0x32,0x59,0x71,0x55,0x26,0x99,0x00
            }
        }, {
            {
                0x02,0x79,0x70,0x53,0x91,0x48,0x92,0x77,0x99,0x00
            }
        }
    }, {
        {
            {
                0x04,0x05,0x84,0x51,0x51,0x37,0x73,0x97,0x99,0x00
            }
        }, {
            {
                0x01,0x90,0x35,0x05,0x78,0x06,0x47,0x85,0x99,0x00
            }
        }, {
            {
                0x03,0x81,0x83,0x00,0x50,0x50,0x51,0x19,0x99,0x00
            }
        }
    }
};

typedef struct {
    fx_number node, weight;
} extra_node;

static const extra_node extra_nodes[4] = {
    {
        {
            {
                0x09,0x91,0x45,0x53,0x71,0x12,0x08,0x13,0x99,0x00
            }
        }, {
            {
                0x02,0x29,0x35,0x32,0x20,0x10,0x52,0x92,0x98,0x00
            }
        }
    }, {
        {
            {
                0x08,0x64,0x86,0x44,0x23,0x35,0x97,0x69,0x99,0x00
            }
        }, {
            {
                0x01,0x04,0x79,0x00,0x10,0x32,0x22,0x50,0x99,0x00
            }
        }
    }, {
        {
            {
                0x05,0x86,0x08,0x72,0x35,0x46,0x76,0x91,0x99,0x00
            }
        }, {
            {
                0x01,0x69,0x00,0x47,0x26,0x63,0x92,0x68,0x99,0x00
            }
        }
    }, {
        {
            {
                0x02,0x07,0x78,0x49,0x55,0x00,0x78,0x99,0x99,0x00
            }
        }, {
            {
                0x02,0x04,0x43,0x29,0x40,0x07,0x52,0x99,0x99,0x00
            }
        }
    }
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

static int evaluate(integral_context *context, fx_number *value, const fx_number *x) {
    fx_numeric_status status = context->function(value, x, context->userdata);
    if ((int)status == FX_CALCULUS_EVALUATION_ERROR) {
        context->native_error = 3;
        return 0;
    }
    if ((int)status == FX_CALCULUS_EVALUATION_OK) {
        if (fx_number_kind(value) == FX_NUMBER_ERROR) return 1;
        status = FX_NUMERIC_OK;
    }
    if (!numeric_result(context, value, status)) return 0;
    if (fx_number_kind(value) == FX_NUMBER_SURD) return numeric_result(context, value, fx_number_to_decimal(value, value));
    return 1;
}

static int poll(integral_context *context) {
    if (context->control && context->control->cancelled && context->control->cancelled(context->control->userdata)) {
        context->native_error = 1;
        return 0;
    }
    return 1;
}

static int converged(integral_context *context, const fx_number *result, const fx_number *error, const fx_number *tolerance) {
    fx_number threshold, minimum;
    fx_numeric_status status = fx_decimal_binary(&threshold, tolerance, result, FX_MULTIPLY);
    if (status != FX_NUMERIC_OK) {
        context->host_status = status;
        return 0;
    }
    if (fx_number_kind(&threshold) == FX_NUMBER_ERROR) return 4;
    if (!absolute(context, &threshold)) return 0;
    (void)fx_decimal_parse(&minimum, "1e-10");
    if (compare(context,&threshold,&minimum,1)==2) threshold = minimum;
    return compare(context,&threshold,error,1);
}

static int storage_valid(const fx_integral_storage *storage) {
    return storage && storage->ram && storage->ram_size == 65536;
}

static int scalar_context(const fx_integral_storage *storage) {
    unsigned mode = storage->ram[0x80f9];
    return mode == 0xc1 || mode == 6 || mode == 7;
}

static int overlaps_ram(const fx_integral_storage *storage,const void *object,size_t size) {
    uintptr_t address=(uintptr_t)object,base=(uintptr_t)storage->ram;
    return address>=base ? address-base<65536 : base-address<size;
}
/* Unchecked15C82 conversion preserves headers above4F. Native173FA
* materializes the six SURD components before converting their value. */

static fx_numeric_status prepare_record(fx_integral_storage *storage, fx_number *out,const fx_number *in) {
    fx_number value=*in;
    fx_numeric_status status;
    if(fx_number_kind(&value)==FX_NUMBER_SURD) {
        status=fx_surd_components_convert_copy(storage->ram,&value,&value);
        if(status!=FX_NUMERIC_OK)return status;
    }
    if(value.bytes[0]>0x4f) {
        *out=value;
        return FX_NUMERIC_OK;
    }
    value.bytes[0]&=(uint8_t)~0x40;
    status=(value.bytes[0]&0xb0)==0x20 ? fx_raw_fraction_convert(out,&value) : fx_number_to_decimal(out,&value);
    if(status==FX_NUMERIC_OK && fx_number_kind(out)!=FX_NUMBER_ERROR) out->bytes[0]&=(uint8_t)~0x40;
    return status;
}

static fx_numeric_status prepare_bound(fx_integral_storage *storage, const fx_number *in,unsigned destination) {
    fx_number value;
    if(!storage_valid(storage)||!in)return FX_NUMERIC_INVALID;
    if(!scalar_context(storage))return FX_NUMERIC_UNIMPLEMENTED;
    fx_numeric_status status=prepare_record(storage,&value,in);
    if(status!=FX_NUMERIC_OK)return status;
    memcpy(storage->ram+destination,value.bytes,8);
    memcpy(storage->ram+destination+8,value.bytes+8,2);
    return FX_NUMERIC_OK;
}

fx_numeric_status fx_integral_storage_lower(fx_integral_storage *storage, const fx_number *lower) {
    return prepare_bound(storage,lower,0x850a);
}

fx_numeric_status fx_integral_storage_upper(fx_integral_storage *storage, const fx_number *upper) {
    return prepare_bound(storage,upper,0x8514);
}

fx_numeric_status fx_integral_storage_tolerance(fx_integral_storage *storage, const fx_number *tolerance,uint16_t final_cursor,unsigned *native_status) {
    fx_number value;
    if(!storage_valid(storage)||!native_status)return FX_NUMERIC_INVALID;
    if(!scalar_context(storage))return FX_NUMERIC_UNIMPLEMENTED;
    if(overlaps_ram(storage,native_status,sizeof *native_status))return FX_NUMERIC_INVALID;
    *native_status=0;
    if(tolerance) {
        fx_numeric_status status=prepare_record(storage,&value,tolerance);
        if(status!=FX_NUMERIC_OK)return status;
        /* CCF6 classifies the normalized raw header/exponent word. F/rich
        * headers are not negative; their unchecked payload remains live. */
        if(value.bytes[0] && (value.bytes[0]&0xf0)<0x50 && (value.bytes[8]||value.bytes[9]) && value.bytes[9]>=4) {
            *native_status=8;
            return FX_NUMERIC_OK;
        }
    } else (void)fx_decimal_parse(&value,"1e-5");
    memcpy(storage->ram+0x851e,value.bytes,8);
    memcpy(storage->ram+0x8526,value.bytes+8,2);
    storage->ram[0x85c8]=(uint8_t)final_cursor;
    storage->ram[0x85c9]=(uint8_t)(final_cursor>>8);
    return FX_NUMERIC_OK;
}

enum {
    LOWER=0x850a,UPPER=0x8514,TOL=0x851e,LEFT=0x8528,RIGHT=0x8532, TOTAL=0x8546,INDEX=0x855a,DENOM=0x8564,SPAN=0x8578,HALF=0x8582, CENTER=0x858c,ERROR=0x8596,RESULT=0x85a0,PAIR=0x85aa,WORK=0x85b4, FINAL_CURSOR=0x85c8,BUDGET=0x85ca,DEPTH=0x85cd
};

typedef struct {
    integral_context math;
    uint8_t *ram;
    fx_number *out;
    fx_integral_storage_publish publish;
    uint16_t *cursor;
    uint16_t output_address,callback_sink;
    fx_integral_storage_callback_context callback_context;
} storage_context;

static fx_number load(storage_context *c,unsigned address){
    fx_number v;
    memcpy(v.bytes,c->ram+address,10);
    return v;
}
/*169C0/16A0A ten-byte copies load8 then2, store8 then2. */

static void store(storage_context *c,unsigned address,const fx_number *v){
    memcpy(c->ram+address,v->bytes,8);
    memcpy(c->ram+address+8,v->bytes+8,2);
}

static void copy_record(storage_context *c,unsigned dst,unsigned src){
    fx_number v=load(c,src);
    store(c,dst,&v);
}

static unsigned word(storage_context *c,unsigned a){
    return c->ram[a]|c->ram[a+1]<<8;
}

static void set_word(storage_context *c,unsigned a,unsigned v){
    c->ram[a]=(uint8_t)v;
    c->ram[a+1]=(uint8_t)(v>>8);
}

static int calculate(storage_context *c,unsigned dst,const fx_number *a,const fx_number *b,fx_binary_op op,int checked){
    fx_number v;
    fx_numeric_status status=binary_record(&v,a,b,op);
    if(status!=FX_NUMERIC_OK){
        c->math.host_status=status;
        return 0;
    }
    store(c,dst,&v);
    return !checked||numeric_result(&c->math,&v,status);
}

static int records(storage_context *c,unsigned dst,unsigned a,unsigned b,fx_binary_op op,int checked){
    fx_number x=load(c,a),y=load(c,b);
    return calculate(c,dst,&x,&y,op,checked);
}

static int constant(storage_context *c,unsigned dst,const fx_number *b,fx_binary_op op){
    fx_number a=load(c,dst);
    return calculate(c,dst,&a,b,op,1);
}

static int clean_record(storage_context *c,unsigned a){
    fx_number v=load(c,a);
    fx_numeric_status s=fx_decimal_integer_cleanup(&v);
    if(s!=FX_NUMERIC_OK){
        c->math.host_status=s;
        return 0;
    }
    store(c,a,&v);
    return numeric_result(&c->math,&v,s);
}

static int decimal_record(storage_context *c,unsigned a){
    fx_number v=load(c,a),result;
    if(!decimal(&c->math,&result,&v))return 0;
    store(c,a,&result);
    return 1;
}

static int abs_record(storage_context *c,unsigned a){
    fx_number v=load(c,a);
    if(!absolute(&c->math,&v))return 0;
    store(c,a,&v);
    return 1;
}

static int sample(storage_context *c,unsigned a){
    fx_number x=load(c,a);
    if(c->publish)c->publish(&x,c->math.userdata);
    if(c->callback_context)c->callback_context(c->callback_sink,c->cursor,c->math.userdata);
    return evaluate(&c->math,c->out,&x);
}

static int pair_storage(storage_context *c,const fx_number *node,uint16_t rom_address){
    c->callback_sink=rom_address;
    store(c,PAIR,node);
    if(!records(c,PAIR,PAIR,HALF,FX_MULTIPLY,1))return 0;
    copy_record(c,WORK,PAIR);
    if(!records(c,PAIR,PAIR,CENTER,FX_SUBTRACT,1))return 0;
    fx_number x=load(c,PAIR);
    if(!numeric_result(&c->math,&x,fx_number_negate(&x,&x)))return 0;
    store(c,PAIR,&x);
    if(!sample(c,PAIR))return 0;
    store(c,PAIR,c->out);
    c->callback_sink=(uint16_t)(rom_address|1);
    if(!records(c,WORK,WORK,CENTER,FX_ADD,1)||!sample(c,WORK))return 0;
    x=load(c,PAIR);
    if(!calculate(c,PAIR,&x,c->out,FX_ADD,1))return 0;
    return clean_record(c,PAIR);
}

static int weighted_storage(storage_context *c,unsigned sum,const fx_number *weight){
    store(c,WORK,weight);
    return records(c,WORK,WORK,PAIR,FX_MULTIPLY,1)&&records(c,sum,sum,WORK,FX_ADD,1);
}

static int quadrature_storage(storage_context *c){
    c->callback_sink=c->output_address;
    fx_number two;
    (void)fx_decimal_from_integer(&two,2);
    copy_record(c,HALF,RIGHT);
    if(!records(c,HALF,HALF,LEFT,FX_SUBTRACT,1)||!constant(c,HALF,&two,FX_DIVIDE))return 0;
    fx_decimal width;
    fx_number half=load(c,HALF);
    if(fx_decimal_decode(&width,&half)!=FX_NUMERIC_OK||!width.sign){
        c->math.native_error=3;
        return 0;
    }
    copy_record(c,CENTER,RIGHT);
    if(!records(c,CENTER,CENTER,LEFT,FX_ADD,1)||!constant(c,CENTER,&two,FX_DIVIDE)||!sample(c,CENTER))return 0;
    store(c,ERROR,&gauss_center);
    fx_number v=load(c,ERROR);
    if(!calculate(c,ERROR,&v,c->out,FX_MULTIPLY,0))return 0;
    store(c,RESULT,&kronrod_center);
    v=load(c,RESULT);
    if(!calculate(c,RESULT,&v,c->out,FX_MULTIPLY,0))return 0;
    for(unsigned i=0;i<3;++i){
        if(!poll(&c->math)||!pair_storage(c,&common_nodes[i].node,(uint16_t)(0x2b1c+30*i))||!weighted_storage(c,RESULT,&common_nodes[i].kronrod)||!weighted_storage(c,ERROR,&common_nodes[i].gauss))return 0;
    }
    for(unsigned i=0;i<4;++i){
        if(!poll(&c->math)||!pair_storage(c,&extra_nodes[i].node,(uint16_t)(0x2b76+20*i))||!weighted_storage(c,RESULT,&extra_nodes[i].weight))return 0;
    }
    return clean_record(c,ERROR)&&decimal_record(c,ERROR)&&records(c,ERROR,ERROR,HALF,FX_MULTIPLY,1)&&clean_record(c,RESULT)&&decimal_record(c,RESULT)&&records(c,RESULT,RESULT,HALF,FX_MULTIPLY,1)&&records(c,ERROR,ERROR,RESULT,FX_SUBTRACT,1)&&abs_record(c,ERROR)&&clean_record(c,ERROR);
}

static int convergence(storage_context *c){
    fx_number result=load(c,RESULT),error=load(c,ERROR),tol=load(c,TOL);
    return converged(&c->math,&result,&error,&tol);
}

static int endpoint_storage(storage_context *c,unsigned dst,int next){
    fx_number one;
    (void)fx_decimal_from_integer(&one,1);
    copy_record(c,dst,INDEX);
    return (!next||constant(c,dst,&one,FX_ADD))&&records(c,dst,dst,DENOM,FX_SUBTRACT,1)&&records(c,dst,dst,DENOM,FX_DIVIDE,1)&&records(c,dst,dst,SPAN,FX_MULTIPLY,1)&&records(c,dst,dst,LOWER,FX_ADD,1);
}

fx_numeric_status fx_number_integral_storage(fx_number *out,fx_integral_storage *storage, fx_calculus_function function,void *userdata,fx_integral_storage_publish publish, uint16_t output_address,fx_integral_storage_callback_context callback_context, const fx_calculus_control *control,unsigned *native_status,uint16_t *cursor){
    if(!out||!storage_valid(storage)||!function||!native_status||!cursor)return FX_NUMERIC_INVALID;
    if(!scalar_context(storage))return FX_NUMERIC_UNIMPLEMENTED;
    if(overlaps_ram(storage,out,sizeof *out)||overlaps_ram(storage,native_status,sizeof *native_status)||overlaps_ram(storage,cursor,sizeof *cursor))return FX_NUMERIC_INVALID;
    uint8_t *ram=storage->ram;
    storage_context c={
        {
            function,userdata,control,FX_NUMERIC_OK,0
        },ram,out,publish,cursor,output_address,output_address,callback_context
    };
    fx_number a=load(&c,LOWER),b=load(&c,UPPER),zero,one,two;
    fx_number_zero(&zero);
    (void)fx_decimal_from_integer(&one,1);
    (void)fx_decimal_from_integer(&two,2);
    int decision;
    decision=compare(&c.math,&a,&b,1);
    if(c.math.host_status!=FX_NUMERIC_OK)goto done;
    if(decision==1){
        if(!sample(&c,UPPER)||!sample(&c,LOWER))goto done;
        *out=zero;
        goto success;
    }
    if(!sample(&c,LOWER)||!sample(&c,UPPER))goto done;
    copy_record(&c,LEFT,LOWER);
    copy_record(&c,RIGHT,UPPER);
    store(&c,TOTAL,&zero);
    store(&c,INDEX,&one);
    store(&c,DENOM,&one);
    ram[DEPTH]=47;
    set_word(&c,BUDGET,324);
    copy_record(&c,SPAN,UPPER);
    if(!records(&c,SPAN,SPAN,LOWER,FX_SUBTRACT,1)||!quadrature_storage(&c))goto done;
    decision=convergence(&c);
    if(c.math.host_status!=FX_NUMERIC_OK)goto done;
    if(decision==4){
        *out=load(&c,RESULT);
        goto success;
    }
    for(;;){
        unsigned budget=(word(&c,BUDGET)-1)&0xffff;
        set_word(&c,BUDGET,budget);
        if(!budget){
            c.math.native_error=11;
            goto done;
        }
        if(!quadrature_storage(&c))goto done;
        decision=convergence(&c);
        if(c.math.host_status!=FX_NUMERIC_OK)goto done;
        if(decision==2){
            if(!constant(&c,DENOM,&two,FX_MULTIPLY))goto done;
            --ram[DEPTH];
            if(!ram[DEPTH]){
                copy_record(&c,PAIR,TOTAL);
                if(!records(&c,PAIR,PAIR,RESULT,FX_ADD,1))goto done;
                fx_number sum=load(&c,PAIR),total=load(&c,TOTAL);
                decision=compare(&c.math,&sum,&total,0);
                if(c.math.host_status!=FX_NUMERIC_OK)goto done;
                if(decision!=1){
                    c.math.native_error=11;
                    goto done;
                }
                ++ram[DEPTH];
                if(!constant(&c,DENOM,&two,FX_DIVIDE))goto done;
            } else{
                if(!constant(&c,INDEX,&two,FX_MULTIPLY)||!endpoint_storage(&c,RIGHT,1))goto done;
                continue;
            }
        }
        if(!records(&c,TOTAL,TOTAL,RESULT,FX_ADD,1))goto done;
        for(;;){
            fx_number index=load(&c,INDEX);
            decision=compare(&c.math,&index,&one,1);
            if(c.math.host_status!=FX_NUMERIC_OK)goto done;
            if(decision==1){
                *out=load(&c,TOTAL);
                goto success;
            }
            int64_t integer;
            if(fx_decimal_to_integer(&integer,&index)!=FX_NUMERIC_OK){
                c.math.host_status=FX_NUMERIC_UNIMPLEMENTED;
                goto done;
            }
            if(!(integer&1))break;
            ++ram[DEPTH];
            if(!constant(&c,DENOM,&two,FX_DIVIDE)||!constant(&c,INDEX,&one,FX_SUBTRACT)||!constant(&c,INDEX,&two,FX_DIVIDE)||!endpoint_storage(&c,LEFT,0))goto done;
        }
        if(!constant(&c,INDEX,&one,FX_ADD))goto done;
        copy_record(&c,LEFT,RIGHT);
        if(!endpoint_storage(&c,RIGHT,1))goto done;
    }
    success: if(!cleanup(&c.math,out))goto done;
    *native_status=0;
    *cursor=(uint16_t)word(&c,FINAL_CURSOR);
    return FX_NUMERIC_OK;
    done: if(c.math.host_status!=FX_NUMERIC_OK)return c.math.host_status;
    *native_status=c.math.native_error?c.math.native_error:3;
    if(*native_status==1)*cursor=(uint16_t)word(&c,FINAL_CURSOR);
    return FX_NUMERIC_OK;
}
