/* RAM-backed real finite-decimal Richardson differentiation.
 * GPL-3.0-or-later. No CPU, ROM execution or host floating-point arithmetic. */
#include "fx_c4_derivative_storage.h"
#include "fx_raw_fraction_convert.h"
#include "fx_surd_components.h"
#include <string.h>

typedef struct {
    fx_c4_derivative_function function;
    void *userdata;
    const fx_calculus_control *control;
    fx_numeric_status host_status;
    unsigned native_error;
    fx_derivative_storage *storage;
    fx_c4_derivative_publish publish;
    fx_complex live;
} derivative_context;

static int result(derivative_context *context, fx_number *value,
                   fx_numeric_status status) {
    if (status != FX_NUMERIC_OK) { context->host_status = status; return 0; }
    if (fx_number_kind(value) == FX_NUMBER_ERROR) {
        context->native_error = 3; return 0;
    }
    return 1;
}

static int decimal(derivative_context *context, fx_number *out,
                    const fx_number *in) {
    fx_number value = *in;
    if (fx_number_kind(&value) == FX_NUMBER_SURD &&
        !result(context, &value, fx_number_to_decimal(&value, &value))) return 0;
    if (value.bytes[0] > 0x4f) { context->native_error = 3; return 0; }
    value.bytes[0] &= (uint8_t)~0x40;
    return result(context, out, fx_number_to_decimal(out, &value));
}

/*15c82 leaves an F-valued record intact. The initial base value and the
 * central divided difference have no status gate at their normalization. */
static int decimal_unchecked(derivative_context *context, fx_number *out,
                              const fx_number *in) {
    fx_number value = *in;
    fx_numeric_status status;
    if (fx_number_kind(&value) == FX_NUMBER_SURD) {
        status = fx_surd_components_convert_copy(context->storage->ram,
                                                &value, &value);
        if (status != FX_NUMERIC_OK) { context->host_status = status; return 0; }
    }
    if (value.bytes[0] > 0x4f) { *out = value; return 1; }
    value.bytes[0] &= (uint8_t)~0x40;
    status = (value.bytes[0]&0xb0)==0x20?
        fx_raw_fraction_convert(out,&value):fx_number_to_decimal(out,&value);
    if (status != FX_NUMERIC_OK) { context->host_status = status; return 0; }
    if (fx_number_kind(out) != FX_NUMBER_ERROR) out->bytes[0] &= (uint8_t)~0x40;
    return 1;
}

static fx_numeric_status binary_record(fx_number *out, const fx_number *a,
                                        const fx_number *b,
                                        fx_binary_op operation) {
    fx_number first, second;
    fx_numeric_status status;
    /* AB64 masks bit40 before ordinary scalar arithmetic. Unlike15C82,
     * it therefore admits a surviving61 reference's rational payload. */
    if ((fx_number_kind(a) != FX_NUMBER_DECIMAL && fx_number_kind(a) != FX_NUMBER_RATIONAL) ||
        (fx_number_kind(b) != FX_NUMBER_DECIMAL && fx_number_kind(b) != FX_NUMBER_RATIONAL)) {
        fx_number_error(out, 3); return FX_NUMERIC_OK;
    }
    if (fx_number_kind(a) == FX_NUMBER_RATIONAL) {
        status = fx_raw_fraction_convert(&first, a);
        if (status != FX_NUMERIC_OK) return status;
        first.bytes[0] |= a->bytes[0] & 0x40; a = &first;
    }
    if (fx_number_kind(b) == FX_NUMBER_RATIONAL) {
        status = fx_raw_fraction_convert(&second, b);
        if (status != FX_NUMERIC_OK) return status;
        second.bytes[0] |= b->bytes[0] & 0x40; b = &second;
    }
    if (fx_number_kind(a) == FX_NUMBER_ERROR || fx_number_kind(b) == FX_NUMBER_ERROR) {
        fx_number_error(out, 3); return FX_NUMERIC_OK;
    }
    return operation == FX_SUBTRACT ? fx_decimal_subtract_cancel(out, a, b) :
                                     fx_decimal_binary(out, a, b, operation);
}

static int binary(derivative_context *context, fx_number *out,
                   const fx_number *a, const fx_number *b,
                   fx_binary_op operation) {
    return result(context, out, binary_record(out, a, b, operation));
}

static int binary_unchecked(derivative_context *context, fx_number *out,
                             const fx_number *a, const fx_number *b,
                             fx_binary_op operation) {
    fx_numeric_status status = binary_record(out, a, b, operation);
    if (status != FX_NUMERIC_OK) { context->host_status = status; return 0; }
    return 1;
}

static int absolute(derivative_context *context, fx_number *value) {
    fx_decimal decoded;
    if (!decimal(context, value, value)) return 0;
    if (fx_decimal_decode(&decoded, value) != FX_NUMERIC_OK) {
        context->host_status = FX_NUMERIC_INVALID; return 0;
    }
    return decoded.sign >= 0 || result(context, value, fx_number_negate(value, value));
}

enum {
    DERIVATIVE_EQUAL=1, DERIVATIVE_LESS=2,
    DERIVATIVE_GREATER=4, DERIVATIVE_INVALID_RELATION=0xf0
};

/* CD94/CD60 copy the records without ordinary fraction conversion. Their
 * AB3E/AB36 guard rejects raw leading bytes>=10, including marked decimals,
 * fractions, rich references and errors. NativeF0 is a comparison result;
 * it must retain each caller's exact equality/greater-than gate. */
static int relation(derivative_context *context, unsigned *ordering,
                    const fx_number *a, const fx_number *b, int cancel) {
    fx_decimal first, second, decoded;
    fx_number difference;
    fx_numeric_status status;
    if (a->bytes[0]>=10 || b->bytes[0]>=10) {
        *ordering=DERIVATIVE_INVALID_RELATION;
        return 1;
    }
    if (fx_decimal_decode(&first,a)!=FX_NUMERIC_OK ||
        fx_decimal_decode(&second,b)!=FX_NUMERIC_OK) {
        /* The bounded scalar adapter does not infer packed comparison of
         * malformed decimal coordinates. This is a host scope limit. */
        context->host_status=FX_NUMERIC_UNIMPLEMENTED;
        return 0;
    }
    if (first.sign!=second.sign) {
        *ordering=first.sign<second.sign?DERIVATIVE_LESS:DERIVATIVE_GREATER;
        return 1;
    }
    if (!first.sign) {
        *ordering=DERIVATIVE_EQUAL;
        return 1;
    }
    status=cancel?fx_decimal_subtract_cancel(&difference,a,b):
                  fx_decimal_binary(&difference,a,b,FX_SUBTRACT);
    if (status!=FX_NUMERIC_OK) {
        context->host_status=status;
        return 0;
    }
    if (fx_decimal_decode(&decoded,&difference)!=FX_NUMERIC_OK) {
        context->host_status=FX_NUMERIC_UNIMPLEMENTED;
        return 0;
    }
    *ordering=decoded.sign<0?DERIVATIVE_LESS:
              decoded.sign>0?DERIVATIVE_GREATER:DERIVATIVE_EQUAL;
    return 1;
}

static int poll(derivative_context *context) {
    if (context->control && context->control->cancelled &&
        context->control->cancelled(context->control->userdata)) {
        context->native_error = 1; return 0;
    }
    return 1;
}

/* CC80 R2=1 retains zero significant digits after its workspace guard.
 * Its away-from-zero ceiling chooses the next signed decimal power. */
static int starting_step(derivative_context *context, fx_number *step,
                          const fx_number *point) {
    fx_decimal decoded;
    fx_number scale;
    (void)fx_decimal_decode(&decoded, point);
    if (!decoded.sign) return result(context, step, fx_decimal_parse(step, ".01"));
    (void)fx_decimal_parse(&scale, "1e-3");
    if (!binary(context, step, point, &scale, FX_MULTIPLY)) return 0;
    (void)fx_decimal_decode(&decoded, step);
    if (!decoded.sign || decoded.exponent+1 < -93)
        return result(context, step, fx_decimal_parse(step, "1e-93"));
    ++decoded.exponent; decoded.mantissa = UINT64_C(100000000000000);
    return result(context, step, fx_decimal_encode(step, &decoded));
}

/* Overflow in the relative convergence error requests another table row;
 * it is not a sampling-domain error. */
static int relative_error(derivative_context *context, fx_number *out,
                           const fx_number *previous, const fx_number *current) {
    fx_numeric_status status = fx_decimal_subtract_cancel(out, previous, current);
    if (status != FX_NUMERIC_OK) { context->host_status = status; return 0; }
    if (fx_number_kind(out) == FX_NUMBER_ERROR) return 0;
    status = fx_decimal_binary(out, out, current, FX_DIVIDE);
    if (status != FX_NUMERIC_OK) { context->host_status = status; return 0; }
    if (fx_number_kind(out) == FX_NUMBER_ERROR) return 0;
    return absolute(context, out);
}

/* Fixed decimal records are semantic algorithm state, not CPU registers. */
enum {
    DERIVATIVE_PROBE_VALUE=0x8578, DERIVATIVE_BASE_VALUE=0x8582,
    DERIVATIVE_PROBE_POINT=0x858c, DERIVATIVE_RATIO_LOWER=0x8596,
    DERIVATIVE_RATIO_WIDTH=0x85a0, DERIVATIVE_TEN=0x85aa,
    DERIVATIVE_LEADING=0x85b4, DERIVATIVE_ERROR=0x85be,
    DERIVATIVE_FACTOR=0x85c8, DERIVATIVE_DOUBLE_STEP=0x85d2,
    DERIVATIVE_STEP=0x85dc, DERIVATIVE_TOLERANCE=0x85e6,
    DERIVATIVE_POINT=0x85f0, DERIVATIVE_PRIOR_ERROR=0x85fa,
    DERIVATIVE_BEST=0x8604
};

static int storage_valid(const fx_derivative_storage *storage) {
    return storage && storage->ram && storage->ram_size==65536;
}
static fx_number load_record(const derivative_context *context, unsigned address) {
    fx_number value;memcpy(value.bytes,context->storage->ram+address,10);return value;
}
static void store_record(derivative_context *context,unsigned address,const fx_number *value) {
    memcpy(context->storage->ram+address,value->bytes,10);
}
static int binary_record_at(derivative_context *context,unsigned destination,
                             const fx_number *a,const fx_number *b,
                             fx_binary_op operation,int checked) {
    fx_number value=load_record(context,destination);
    int okay=checked?binary(context,&value,a,b,operation):
                     binary_unchecked(context,&value,a,b,operation);
    if(context->host_status==FX_NUMERIC_OK)store_record(context,destination,&value);
    return okay;
}
static int binary_at(derivative_context *context,unsigned destination,
                      unsigned a,unsigned b,fx_binary_op operation,int checked) {
    fx_number first=load_record(context,a),second=load_record(context,b);
    return binary_record_at(context,destination,&first,&second,operation,checked);
}
static int normalize_at(derivative_context *context,unsigned address) {
    fx_number value=load_record(context,address);
    int okay=decimal_unchecked(context,&value,&value);
    if(context->host_status==FX_NUMERIC_OK)store_record(context,address,&value);
    return okay;
}
static int absolute_at(derivative_context *context,unsigned address) {
    fx_number value=load_record(context,address);
    int okay=absolute(context,&value);
    if(context->host_status==FX_NUMERIC_OK)store_record(context,address,&value);
    return okay;
}


static int overlaps_ram(const fx_derivative_storage *storage,const void *object,size_t size) {
    uintptr_t address=(uintptr_t)object,base=(uintptr_t)storage->ram;
    return address>=base?address-base<65536u:base-address<size;
}
static int pair_context(const fx_derivative_storage *storage) {
    return storage->ram[0x80f9] == 0xc4;
}
static fx_complex load_pair(const derivative_context *context,unsigned address) {
    fx_complex value=context->live;
    memcpy(&value.real,context->storage->ram+address,10);
    if(pair_context(context->storage))memcpy(&value.imaginary,context->storage->ram+address+10,10);
    return value;
}
static void store_pair(derivative_context *context,unsigned address,const fx_complex *value) {
    memcpy(context->storage->ram+address,&value->real,10);
    if(pair_context(context->storage))memcpy(context->storage->ram+address+10,&value->imaginary,10);
}
static void copy_pair(derivative_context *context,unsigned destination,unsigned source) {
    /* Native first-record stores precede the second-record source read. */
    fx_number first=load_record(context,source);
    store_record(context,destination,&first);
    if(pair_context(context->storage)) {
        fx_number second=load_record(context,source+10);
        store_record(context,destination+10,&second);
    }
}
static void publish_pair(derivative_context *context,unsigned address) {
    fx_complex value;fx_number first=load_record(context,address);
    memcpy(context->storage->ram+0x8276,&first,10);
    if(pair_context(context->storage)) {
        fx_number second=load_record(context,address+10);
        memcpy(context->storage->ram+0x8458,&second,10);
    }
    memcpy(&value.real,context->storage->ram+0x8276,10);
    memcpy(&value.imaginary,context->storage->ram+0x8458,10);
    if(context->publish)context->publish(&value,context->userdata);
}
enum callback_error_policy {
    CALLBACK_MATH_ERROR, CALLBACK_ALLOW_ERROR, CALLBACK_KEEP_ERROR
};
static int evaluate(derivative_context *context,enum callback_error_policy error_policy) {
    fx_complex x;
    memcpy(&x.real,context->storage->ram+0x8276,10);
    memcpy(&x.imaginary,context->storage->ram+0x8458,10);
    fx_numeric_status status=context->function(&context->live,&x,context->userdata);
    if((int)status==FX_CALCULUS_EVALUATION_ERROR ||
       (status==FX_NUMERIC_OK&&fx_number_kind(&context->live.real)==FX_NUMBER_ERROR)) {
        fx_number error;
        fx_number published=load_record(context,DERIVATIVE_LEADING);
        unsigned code=(int)status==FX_CALCULUS_EVALUATION_ERROR&&
            fx_number_kind(&published)==FX_NUMBER_ERROR?
            published.bytes[0]&15u:
            fx_number_kind(&context->live.real)==FX_NUMBER_ERROR?
            context->live.real.bytes[0]&15u:3;
        fx_number_error(&error,code);store_record(context,DERIVATIVE_LEADING,&error);
    }
    if((int)status==FX_CALCULUS_EVALUATION_ERROR) {
        if(error_policy==CALLBACK_ALLOW_ERROR)status=FX_NUMERIC_OK;
        else {
            /*4BAE preserves the first171EA error code. The symmetric
             * helper4AE4 deliberately replaces later evaluator errors by3. */
            fx_number published=load_record(context,DERIVATIVE_LEADING);
            context->native_error=error_policy==CALLBACK_KEEP_ERROR?
                published.bytes[0]&15u:3;
            return 0;
        }
    }
    if((int)status==FX_CALCULUS_EVALUATION_OK)return 1;
    if(status!=FX_NUMERIC_OK) {context->host_status=status;return 0;}
    if(error_policy==CALLBACK_ALLOW_ERROR&&fx_number_kind(&context->live.real)==FX_NUMBER_ERROR)return 1;
    return result(context,&context->live.real,FX_NUMERIC_OK);
}
static int evaluate_at(derivative_context *context,unsigned address,enum callback_error_policy error_policy) {
    publish_pair(context,address);return evaluate(context,error_policy);
}

fx_numeric_status fx_c4_derivative_point(fx_derivative_storage *storage,const fx_complex *point) {
    if(!storage_valid(storage)||!point)return FX_NUMERIC_INVALID;
    if(overlaps_ram(storage,point,sizeof *point))return FX_NUMERIC_INVALID;
    if(!pair_context(storage))return FX_NUMERIC_UNIMPLEMENTED;
    derivative_context context={0};context.storage=storage;
    fx_complex value=*point;
    if(!decimal_unchecked(&context,&value.real,&value.real))return context.host_status;
    store_pair(&context,DERIVATIVE_POINT,&value);return FX_NUMERIC_OK;
}
fx_numeric_status fx_c4_derivative_tolerance(fx_derivative_storage *storage,
 const fx_complex *tolerance,unsigned *native_status) {
    if(!storage_valid(storage)||!native_status)return FX_NUMERIC_INVALID;
    if(overlaps_ram(storage,native_status,sizeof *native_status)||
       (tolerance&&overlaps_ram(storage,tolerance,sizeof *tolerance)))return FX_NUMERIC_INVALID;
    if(!pair_context(storage))return FX_NUMERIC_UNIMPLEMENTED;
    derivative_context context={0};context.storage=storage;
    fx_complex value;fx_decimal decoded;
    if(tolerance) {
        value=*tolerance;
        if(!decimal_unchecked(&context,&value.real,&value.real))return context.host_status;
        if(fx_decimal_decode(&decoded,&value.real)!=FX_NUMERIC_OK||decoded.sign<=0) {
            *native_status=8;return FX_NUMERIC_OK;
        }
        store_pair(&context,DERIVATIVE_TOLERANCE,&value);
        storage->ram[DERIVATIVE_PRIOR_ERROR]=0xff;
    } else {
        /* Default constants use the two consecutive ROM objects1,2. The
         * scalar exponent edits keep that second record, overwriting point. */
        fx_decimal_from_u8(&value.imaginary,2);
        (void)fx_decimal_parse(&value.real,"1e-10");
        store_pair(&context,DERIVATIVE_TOLERANCE,&value);
        (void)fx_decimal_parse(&value.real,"1e-7");
        store_pair(&context,DERIVATIVE_PRIOR_ERROR,&value);
        storage->ram[DERIVATIVE_BEST]=0xff;
    }
    *native_status=0;return FX_NUMERIC_OK;
}

static int choose_pair_step(derivative_context *context) {
    fx_number value;
    fx_decimal decoded;
    (void)fx_decimal_from_integer(&value,10);store_record(context,DERIVATIVE_TEN,&value);
    (void)fx_decimal_parse(&value,".2");store_record(context,DERIVATIVE_RATIO_WIDTH,&value);
    (void)fx_decimal_parse(&value,".9");store_record(context,DERIVATIVE_RATIO_LOWER,&value);
    if(!evaluate_at(context,DERIVATIVE_POINT,CALLBACK_MATH_ERROR)||
       !decimal_unchecked(context,&context->live.real,&context->live.real))return 0;
    store_pair(context,DERIVATIVE_BASE_VALUE,&context->live);
    fx_number_zero(&value);store_record(context,DERIVATIVE_PROBE_VALUE,&value);
    for(unsigned attempt=0;attempt<7;++attempt) {
        value=load_record(context,DERIVATIVE_POINT);
        /*69AE is the ordinary scalar copy; its ratio-lower mate stays live. */
        store_record(context,DERIVATIVE_PROBE_POINT,&value);
        if(!binary_at(context,DERIVATIVE_PROBE_POINT,DERIVATIVE_PROBE_POINT,DERIVATIVE_STEP,FX_ADD,1))return 0;
        value=load_record(context,DERIVATIVE_PROBE_VALUE);
        if(fx_number_kind(&value)==FX_NUMBER_ERROR&&(value.bytes[0]&15u)) {
            fx_number probe=load_record(context,DERIVATIVE_PROBE_POINT),point=load_record(context,DERIVATIVE_POINT);
            unsigned ordering;
            if(!relation(context,&ordering,&probe,&point,1))return 0;
            if(ordering==DERIVATIVE_EQUAL){context->native_error=3;return 0;}
        }
        if(!evaluate_at(context,DERIVATIVE_PROBE_POINT,CALLBACK_ALLOW_ERROR)||
           !decimal_unchecked(context,&context->live.real,&context->live.real))return 0;
        store_pair(context,DERIVATIVE_PROBE_VALUE,&context->live);
        value=load_record(context,DERIVATIVE_PROBE_VALUE);
        unsigned error=fx_number_kind(&value)==FX_NUMBER_ERROR?value.bytes[0]&15u:0;
        if(error&&error!=3){context->native_error=3;return 0;}
        if(!error) {
            fx_number base=load_record(context,DERIVATIVE_BASE_VALUE);
            if(base.bytes[0]<=0x4f&&fx_decimal_decode(&decoded,&base)==FX_NUMERIC_OK&&!decoded.sign)break;
            if(value.bytes[0]<=0x4f&&fx_decimal_decode(&decoded,&value)==FX_NUMERIC_OK&&!decoded.sign)break;
            context->live=load_pair(context,DERIVATIVE_PROBE_VALUE);
            fx_numeric_status status=binary_record(&context->live.real,&context->live.real,&base,FX_DIVIDE);
            if(status!=FX_NUMERIC_OK){context->host_status=status;return 0;}
            int positive=fx_number_kind(&context->live.real)!=FX_NUMBER_ERROR&&
                fx_decimal_decode(&decoded,&context->live.real)==FX_NUMERIC_OK&&decoded.sign>=0;
            if(positive) {
                fx_number lower=load_record(context,DERIVATIVE_RATIO_LOWER);
                if(!absolute(context,&context->live.real)||
                   !result(context,&context->live.real,fx_decimal_binary(&context->live.real,&context->live.real,&lower,FX_SUBTRACT)))return 0;
                (void)fx_decimal_decode(&decoded,&context->live.real);
                fx_number width=load_record(context,DERIVATIVE_RATIO_WIDTH);unsigned ordering;
                if(!relation(context,&ordering,&context->live.real,&width,0))return 0;
                if(decoded.sign>=0&&(ordering==DERIVATIVE_EQUAL||ordering==DERIVATIVE_LESS))break;
            }
        }
        if(!binary_at(context,DERIVATIVE_STEP,DERIVATIVE_STEP,DERIVATIVE_TEN,FX_DIVIDE,1))return 0;
    }
    return 1;
}
static int central_pair_sample(derivative_context *context,unsigned destination) {
    publish_pair(context,DERIVATIVE_POINT);
    if(!binary_at(context,0x8276,0x8276,DERIVATIVE_STEP,FX_ADD,0)||!evaluate(context,CALLBACK_MATH_ERROR))return 0;
    store_pair(context,destination,&context->live);
    publish_pair(context,DERIVATIVE_POINT);
    if(!binary_at(context,0x8276,0x8276,DERIVATIVE_STEP,FX_SUBTRACT,0)||!evaluate(context,CALLBACK_MATH_ERROR))return 0;
    fx_number plus=load_record(context,destination);
    if(!binary_record_at(context,destination,&plus,&context->live.real,FX_SUBTRACT,0)||
       !binary_at(context,destination,destination,DERIVATIVE_DOUBLE_STEP,FX_DIVIDE,0)||
       !normalize_at(context,destination))return 0;
    fx_number value=load_record(context,destination);
    int okay=result(context,&value,fx_decimal_integer_cleanup(&value));
    if(context->host_status==FX_NUMERIC_OK)store_record(context,destination,&value);
    return okay;
}
static void zero_pair(derivative_context *context) {
    /* Native success shortcut copies consecutive ROM objects0,1. */
    fx_number_zero(&context->live.real);
    if(pair_context(context->storage))fx_decimal_from_u8(&context->live.imaginary,1);
}
fx_numeric_status fx_c4_derivative_run(fx_complex *out,fx_derivative_storage *storage,
 fx_c4_derivative_function function,void *userdata,fx_c4_derivative_publish publish,
 const fx_calculus_control *control,unsigned *native_status) {
    if(!out||!storage_valid(storage)||!function||!native_status)return FX_NUMERIC_INVALID;
    if(overlaps_ram(storage,out,sizeof *out)||overlaps_ram(storage,native_status,sizeof *native_status))return FX_NUMERIC_INVALID;
    if(!pair_context(storage))return FX_NUMERIC_UNIMPLEMENTED;
    derivative_context context={0};context.function=function;context.userdata=userdata;
    context.publish=publish;context.control=control;context.storage=storage;context.live=*out;
    fx_number point,value,step;fx_decimal decoded;
    if(!evaluate_at(&context,DERIVATIVE_POINT,CALLBACK_KEEP_ERROR))goto done;
    context.live=load_pair(&context,DERIVATIVE_POINT);point=context.live.real;
    if(fx_decimal_decode(&decoded,&point)==FX_NUMERIC_OK) {
        if(!starting_step(&context,&step,&point))goto done;
    } else {
        fx_number scale;(void)fx_decimal_parse(&scale,"1e-3");
        if(!binary_unchecked(&context,&step,&point,&scale,FX_MULTIPLY))goto done;
        if(fx_decimal_decode(&decoded,&step)!=FX_NUMERIC_OK||!decoded.sign||decoded.exponent+1 < -93)
            (void)fx_decimal_parse(&step,"1e-93");
        else {++decoded.exponent;decoded.mantissa=UINT64_C(100000000000000);
            if(!result(&context,&step,fx_decimal_encode(&step,&decoded)))goto done;}
    }
    context.live.real=step;store_pair(&context,DERIVATIVE_STEP,&context.live);
    if(!choose_pair_step(&context)||!absolute_at(&context,DERIVATIVE_STEP))goto done;
    copy_pair(&context,DERIVATIVE_DOUBLE_STEP,DERIVATIVE_STEP);
    /* Native4C2A keeps a numerical error until the symmetric helper
     * completes both callbacks and applies its final scalar status gate. */
    if(!binary_at(&context,DERIVATIVE_DOUBLE_STEP,DERIVATIVE_DOUBLE_STEP,DERIVATIVE_STEP,FX_ADD,0)||
       !central_pair_sample(&context,DERIVATIVE_LEADING))goto done;
    for(unsigned iteration=1;;++iteration) {
        if(!poll(&context))goto done;
        copy_pair(&context,DERIVATIVE_DOUBLE_STEP,DERIVATIVE_STEP);
        fx_number two;(void)fx_decimal_from_integer(&two,2);step=load_record(&context,DERIVATIVE_STEP);
        if(!binary_record_at(&context,DERIVATIVE_STEP,&step,&two,FX_DIVIDE,0))goto done;
        copy_pair(&context,DERIVATIVE_ERROR,DERIVATIVE_LEADING);
        unsigned newest=DERIVATIVE_LEADING-10*iteration;
        if(!central_pair_sample(&context,newest))goto done;
        /* The factor initializer copies consecutive ROM records3,4 before
         * negating the first, replacing the adjacent doubled-step record. */
        fx_complex factor_pair;
        (void)fx_decimal_from_integer(&factor_pair.real,-3);
        fx_decimal_from_u8(&factor_pair.imaginary,4);
        store_pair(&context,DERIVATIVE_FACTOR,&factor_pair);
        for(unsigned column=iteration;column>0;--column) {
            unsigned newer=DERIVATIVE_LEADING-10*column,older=newer+10;
            if(!binary_at(&context,older,older,newer,FX_SUBTRACT,0)||
               !binary_at(&context,older,older,DERIVATIVE_FACTOR,FX_DIVIDE,0)||
               !binary_at(&context,older,older,newer,FX_ADD,1))goto done;
            if(column>1) {
                fx_number factor=load_record(&context,DERIVATIVE_FACTOR),four,three;
                (void)fx_decimal_from_integer(&four,4);(void)fx_decimal_from_integer(&three,3);
                if(!binary_record_at(&context,DERIVATIVE_FACTOR,&factor,&four,FX_MULTIPLY,0))goto done;
                factor=load_record(&context,DERIVATIVE_FACTOR);
                if(!binary_record_at(&context,DERIVATIVE_FACTOR,&factor,&three,FX_SUBTRACT,0))goto done;
            }
        }
        value=load_record(&context,DERIVATIVE_LEADING);
        if(!value.bytes[0]) {
            if(storage->ram[DERIVATIVE_ERROR])zero_pair(&context);
            else context.live=load_pair(&context,DERIVATIVE_LEADING);
            goto success;
        }
        fx_number previous=load_record(&context,DERIVATIVE_ERROR),error;
        int have_error=relative_error(&context,&error,&previous,&value);
        if(context.host_status!=FX_NUMERIC_OK)goto done;
        store_record(&context,DERIVATIVE_ERROR,&error);
        if(have_error) {
            fx_number precision=load_record(&context,DERIVATIVE_TOLERANCE);unsigned ordering;
            if(!relation(&context,&ordering,&error,&precision,1))goto done;
            if(ordering!=DERIVATIVE_GREATER){context.live=load_pair(&context,DERIVATIVE_LEADING);goto success;}
            while(storage->ram[DERIVATIVE_PRIOR_ERROR]!=0xff&&storage->ram[DERIVATIVE_PRIOR_ERROR]) {
                fx_number prior=load_record(&context,DERIVATIVE_PRIOR_ERROR);
                if(!relation(&context,&ordering,&error,&prior,1))goto done;
                if(ordering==DERIVATIVE_GREATER)break;
                copy_pair(&context,DERIVATIVE_BEST,DERIVATIVE_LEADING);
                if(storage->ram[DERIVATIVE_PRIOR_ERROR+8]==0x91){storage->ram[DERIVATIVE_PRIOR_ERROR]=0;break;}
                --storage->ram[DERIVATIVE_PRIOR_ERROR+8];
            }
            value=load_record(&context,DERIVATIVE_LEADING);
            (void)fx_decimal_decode(&decoded,&value);
            if(decoded.exponent < -10){zero_pair(&context);goto success;}
        }
        unsigned maximum=storage->ram[DERIVATIVE_PRIOR_ERROR]==0xff?15:10;
        if(iteration>=maximum) {
            if(maximum==10&&storage->ram[DERIVATIVE_BEST]!=0xff) {
                copy_pair(&context,DERIVATIVE_LEADING,DERIVATIVE_BEST);
                context.live=load_pair(&context,DERIVATIVE_LEADING);goto success;
            }
            context.native_error=11;goto done;
        }
    }
done:
    if(context.host_status!=FX_NUMERIC_OK)return context.host_status;
    *out=context.live;*native_status=context.native_error?context.native_error:3;return FX_NUMERIC_OK;
success:
    *out=context.live;*native_status=0;return FX_NUMERIC_OK;
}
