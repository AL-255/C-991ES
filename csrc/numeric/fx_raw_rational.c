/* Prepared raw fraction fields with readable component arithmetic.
 * GPL-3.0-or-later. No firmware, CPU, instruction model, or host libm. */
#include "fx_raw_rational.h"
#include "fx_raw_decimal_parts.h"
#include "fx_raw_decimal_multiply_add.h"
#include "fx_raw_decimal_divide.h"
#include "fx_raw_fraction_convert.h"
#include <string.h>

typedef struct { fx_number numerator,denominator; } ratio_parts;
static void write_external(fx_number *out,const uint8_t raw[10])
{
 out->bytes[8]=raw[0];out->bytes[9]=raw[1];
 for(unsigned i=0;i<8;++i)out->bytes[7-i]=raw[2+i];
}
static void read_coordinate(uint8_t raw[10],const fx_number *in)
{
 raw[0]=in->bytes[8];raw[1]=in->bytes[9];
 for(unsigned i=0;i<8;++i)raw[2+i]=in->bytes[7-i];
}

/* High-level Euclidean read_mantissa remainders in the firmware's raw exponent
 * coordinate. This intentionally orders the stored exponent bytes, so an
 * unchecked fractional component is not reinterpreted as a signed exponent.
 * GPL-3.0-or-later. */

static int read_mantissa(uint64_t *out,const uint8_t in[10])
{
    uint64_t value=0;
    for(unsigned i=10;i>2;--i) {
        unsigned pair=in[i-1];
        if((pair&15)>9 || (pair>>4)>9)return 0;
        value=value*100+(pair>>4)*10+(pair&15);
    }
    *out=value;return 1;
}
static void write_mantissa(uint8_t out[10],uint64_t value)
{
    for(unsigned i=2;i<10;++i) {
        unsigned pair=(unsigned)(value%100);value/=100;
        out[i]=(uint8_t)((pair/10)*16+pair%10);
    }
}
static void exchange_coordinates(uint8_t left[10],uint8_t right[10])
{
    uint8_t saved[10];memcpy(saved,left,10);memcpy(left,right,10);memcpy(right,saved,10);
}
/* The ordinary path uses an integer remainder. A normalizer may expose an
 * error-classification pair as the leading read_mantissa byte; its finite packed
 * correction must then be retained instead of assigning an integer value. */
static fx_numeric_status reduce_mantissa(uint8_t a[10],const uint8_t b[10])
{
    uint64_t am,bm;
    if(read_mantissa(&am,a)&&read_mantissa(&bm,b)) {
        if(!bm)return FX_NUMERIC_UNIMPLEMENTED;
        write_mantissa(a,am%bm);return FX_NUMERIC_OK;
    }
    for(unsigned attempt=0;attempt<256;++attempt) {
        unsigned borrow=0;
        for(unsigned i=2;i<10;++i)
            a[i]=fx_raw_decimal_pair_subtract(a[i],b[i],&borrow);
        if(borrow) {
            unsigned carry=0;
            for(unsigned i=2;i<10;++i)
                a[i]=fx_raw_decimal_pair_add(a[i],b[i],&carry);
            return FX_NUMERIC_OK;
        }
    }
    return FX_NUMERIC_UNIMPLEMENTED;
}
static void append_decimal_zero(uint8_t a[10])
{
    unsigned carry=0;
    for(unsigned i=2;i<10;++i) {
        unsigned next=a[i]>>4;
        a[i]=(uint8_t)((a[i]<<4)|carry);carry=next;
    }
}
static fx_numeric_status coordinate_gcd(uint8_t out[10],const uint8_t left[10],const uint8_t right[10])
{
    uint8_t a[10],b[10];
    if(!out||!left||!right)return FX_NUMERIC_INVALID;
    memcpy(a,left,10);memcpy(b,right,10);
    if(a[9]>=0xf0||b[9]>=0xf0)return FX_NUMERIC_UNIMPLEMENTED;
    /* The initial stored-byte ordering runs once. Later Euclidean rounds
     * exchange_coordinates whole coordinates without re-sorting the wrapped exponent. */
    if(a[0]<b[0])exchange_coordinates(a,b);
    for(unsigned round=0;round<1024;++round) {
        /* Each exponent position contributes one next decimal digit to the
         * read_mantissa remainder, with a packed-prefix decrement between digits. */
        for(unsigned position=0;position<256;++position) {
            fx_numeric_status status=reduce_mantissa(a,b);
            if(status!=FX_NUMERIC_OK)return status;
            if(a[0]==b[0])break;
            append_decimal_zero(a);
            unsigned borrow=0;
            a[0]=fx_raw_decimal_pair_subtract(a[0],1,&borrow);
            a[1]=fx_raw_decimal_pair_subtract(a[1],0,&borrow);
            if(position==255)return FX_NUMERIC_UNIMPLEMENTED;
        }
        fx_raw_decimal_normalize(a);
        if(!a[9]) {
            unsigned borrow=0;
            uint8_t positive=fx_raw_decimal_pair_subtract(b[1],5,&borrow);
            if(borrow) {
                unsigned carry=0;positive=fx_raw_decimal_pair_add(positive,5,&carry);
            }
            b[1]=positive&15;memcpy(out,b,10);return FX_NUMERIC_OK;
        }
        exchange_coordinates(a,b);
    }
    return FX_NUMERIC_UNIMPLEMENTED;
}

static fx_numeric_status ratio_gcd(fx_number *out,const fx_number *a,const fx_number *b)
{
 uint8_t left[10],right[10],value[10];
 left[0]=a->bytes[8];left[1]=a->bytes[9];
 right[0]=b->bytes[8];right[1]=b->bytes[9];
 for(unsigned i=0;i<8;++i) {
  left[i+2]=a->bytes[7-i];right[i+2]=b->bytes[7-i];
 }
 fx_numeric_status status=coordinate_gcd(value,left,right);
 if(status==FX_NUMERIC_OK) {
  out->bytes[8]=value[0];out->bytes[9]=value[1];
  for(unsigned i=0;i<8;++i)out->bytes[7-i]=value[i+2];
 }
 return status;
}

static fx_numeric_status quotient_digit(uint8_t a[10],const uint8_t b[10],unsigned *digit)
{
 uint64_t am,bm;
 if(read_mantissa(&am,a)&&read_mantissa(&bm,b)) {
  if(!bm||am/bm>=256u)return FX_NUMERIC_UNIMPLEMENTED;
  *digit=(unsigned)(am/bm);write_mantissa(a,am%bm);return FX_NUMERIC_OK;
 }
 for(unsigned attempt=0;attempt<256u;++attempt) {
  unsigned borrow=0;
  for(unsigned i=2;i<10;++i)a[i]=fx_raw_decimal_pair_subtract(a[i],b[i],&borrow);
  if(borrow) {
   unsigned carry=0;
   for(unsigned i=2;i<10;++i)a[i]=fx_raw_decimal_pair_add(a[i],b[i],&carry);
   *digit=attempt;return FX_NUMERIC_OK;
  }
 }
 return FX_NUMERIC_UNIMPLEMENTED;
}
static fx_numeric_status coordinate_divmod(uint8_t remainder[10],uint8_t whole[10],
 const uint8_t left[10],const uint8_t right[10])
{
 uint8_t a[10],b[10],q[10]={0};unsigned sign_restore=5;
 if(!remainder||!whole||!left||!right)return FX_NUMERIC_INVALID;
 memcpy(a,left,10);memcpy(b,right,10);
 if(a[9]>=0xf0u){memcpy(remainder,a,10);return FX_NUMERIC_OK;}
 for(unsigned attempt=0;attempt<16u;++attempt) {
  unsigned carry=0;
  a[1]=fx_raw_decimal_pair_add(a[1],5,&carry);
  if(a[1]>=16u){a[1]&=15u;break;}
  carry=0;sign_restore=fx_raw_decimal_pair_add((uint8_t)sign_restore,5,&carry)&15u;
  if(attempt==15u)return FX_NUMERIC_UNIMPLEMENTED;
 }
 q[0]=0x14;q[1]=1;
 for(unsigned position=0;position<256u;++position) {
  uint8_t difference[2];unsigned borrow=0;
  difference[0]=fx_raw_decimal_pair_subtract(a[0],b[0],&borrow);
  difference[1]=fx_raw_decimal_pair_subtract(a[1],b[1],&borrow);
  if(borrow)break;
  if(q[9]) {
   unsigned carry=0;
   q[0]=fx_raw_decimal_pair_add(0x15,difference[0],&carry);
   q[1]=fx_raw_decimal_pair_add(1,difference[1],&carry)&15u;
   break;
  }
  append_decimal_zero(q);
  unsigned digit;fx_numeric_status status=quotient_digit(a,b,&digit);
  if(status!=FX_NUMERIC_OK)return status;
  q[2]=(uint8_t)(q[2]+digit);
  append_decimal_zero(a);borrow=0;
  a[0]=fx_raw_decimal_pair_subtract(a[0],1,&borrow);
  a[1]=fx_raw_decimal_pair_subtract(a[1],0,&borrow)&15u;
  if(position==255u)return FX_NUMERIC_UNIMPLEMENTED;
 }
 fx_raw_decimal_normalize(a);
 unsigned carry=0;
 a[1]=fx_raw_decimal_pair_add(a[1],(uint8_t)sign_restore,&carry)&15u;
 fx_raw_decimal_normalize(q);
 if(q[9]) {
  carry=0;q[1]=fx_raw_decimal_pair_add(q[1],(uint8_t)sign_restore,&carry)&15u;
 }
 memcpy(remainder,a,10);memcpy(whole,q,10);return FX_NUMERIC_OK;
}

/* Prepared fraction-field composition. No firmware or machine-state model. */

static uint8_t length_sum(uint8_t a, uint8_t b)
{
 unsigned carry=0;
 return fx_raw_decimal_pair_add(a,b,&carry);
}
/* A delimiter and its following field share one finite packed mantissa.
 * The original writer ORs fields after decimal shifts. Prefix carries are
 * deliberately discarded; the field budget is an unsigned raw BCD pair. */
static void append_field(uint8_t mantissa[8], const uint8_t input[8],
                         uint8_t packed_positions)
{
 uint8_t field[8];
 unsigned positions=packed_positions>=16u ?
                     (packed_positions-6u)&255u : packed_positions;
 memcpy(field,input,8);field[7]|=0xa0u;
 if(positions>18u)positions=18u;
 for(unsigned p=0;p<positions;++p) {
  unsigned carry=0;
  for(unsigned i=8;i>0;--i) {
   unsigned byte=field[i-1];
   field[i-1]=(uint8_t)((byte>>4)|carry);carry=(byte&15u)<<4;
  }
 }
 for(unsigned i=0;i<8;++i)mantissa[i]|=field[i];
}
static fx_numeric_status pack_fraction_fields(fx_number *out,
 const fx_number *remainder, const fx_number *denominator,
 const fx_number *whole)
{
 uint8_t r[10],d[10],q[10],value[10],length,budget,prefix;
 if(!out||!remainder||!denominator||!whole)return FX_NUMERIC_INVALID;
 read_coordinate(r,remainder);read_coordinate(d,denominator);read_coordinate(q,whole);
 budget=length_sum(length_sum(r[0],d[0]),3);
 if(q[9])budget=length_sum(length_sum(budget,q[0]),2);
 if(budget>=0x11u) {
  uint8_t fraction[10];
  fx_numeric_status status=fx_raw_decimal_divide(fraction,r,d);
  if(status!=FX_NUMERIC_OK)return status;
  status=fx_raw_decimal_add(value,fraction,q);
  if(status!=FX_NUMERIC_OK)return status;
  fx_raw_decimal_cleanup(value);write_external(out,value);return FX_NUMERIC_OK;
 }
 memset(value,0,10);value[1]=r[1];
 if(q[9]) {
  uint8_t positions=length_sum(q[0],2);
  length=length_sum(length_sum(r[0],1),positions);
  memcpy(value+2,q+2,8);append_field(value+2,r+2,positions);
 } else {
  memcpy(value+2,r+2,8);length=length_sum(r[0],1);
 }
 prefix=length_sum(length,1);
 length=length_sum(length_sum(d[0],1),prefix);
 append_field(value+2,d+2,prefix);value[9]|=0x20u;value[0]=length;
 write_external(out,value);return FX_NUMERIC_OK;
}

static void toggle_sign(fx_number *value)
{
 unsigned carry=0;
 value->bytes[9]=fx_raw_decimal_pair_add(value->bytes[9],5,&carry)&15u;
}
/* Integer admission inspects the prepared field, before decimal decoding.
 * A zero leading byte is admitted regardless of hidden trailing payload. */
static int raw_integer(const fx_number *input)
{
 fx_number value=*input;value.bytes[0]&=(uint8_t)~0x40u;
 if(!value.bytes[0])return 1;
 if(value.bytes[0]>=10u)return 0;
 unsigned sign=value.bytes[9];if(sign>=5u)sign-=5u;
 if(!sign||value.bytes[8]>0x14u)return 0;
 unsigned count=0;
 for(unsigned i=8;i>0;--i) {
  unsigned pair=value.bytes[i-1];
  if(pair&15u)break;
  ++count;
  if(pair>>4)break;
  ++count;
 }
 uint8_t packed_count=(uint8_t)(count>=10u?count+6u:count);
 unsigned borrow=0;
 uint8_t needed=fx_raw_decimal_pair_subtract(0x14,value.bytes[8],&borrow);
 return packed_count>=needed;
}
static fx_numeric_status parts(ratio_parts *out,const fx_number *input)
{
 fx_number value=*input;value.bytes[0]&=(uint8_t)~0x40u;
 if((value.bytes[0]&0xf0u)==0x20u) {
  fx_raw_fraction_parts split;fx_numeric_status status=FX_NUMERIC_OK;
  fx_raw_fraction_split(&split,&value);fx_raw_decimal_normalize(split.whole);
  if(split.has_middle) {
   status=fx_raw_decimal_multiply(split.whole,split.whole,split.denominator);
   if(status==FX_NUMERIC_OK)status=fx_raw_decimal_add(split.whole,split.whole,split.middle);
  }
  if(status!=FX_NUMERIC_OK)return status;
  write_external(&out->numerator,split.whole);write_external(&out->denominator,split.denominator);
  return FX_NUMERIC_OK;
 }
 if(!raw_integer(&value))return FX_NUMERIC_UNIMPLEMENTED;
 out->numerator=value;fx_decimal_from_u8(&out->denominator,1);return FX_NUMERIC_OK;
}
static fx_numeric_status arithmetic(fx_number *out,const fx_number *a,
                                    const fx_number *b,fx_binary_op op)
{
 uint8_t left[10],right[10],value[10];
 read_coordinate(left,a);read_coordinate(right,b);
 if(op==FX_SUBTRACT&&right[9]<0xf0u) {
  unsigned carry=0;right[1]=fx_raw_decimal_pair_add(right[1],5,&carry)&15u;
 }
 fx_numeric_status status=op==FX_MULTIPLY ?
  fx_raw_decimal_multiply(value,left,right):op==FX_DIVIDE ?
  fx_raw_decimal_divide(value,left,right):fx_raw_decimal_add(value,left,right);
 if(status==FX_NUMERIC_OK)write_external(out,value);
 return status;
}
static fx_numeric_status reduce_components(fx_number *out,
 fx_number numerator,fx_number denominator,fx_binary_op operation)
{
 fx_number common,whole,remainder;fx_numeric_status status;
 if(operation==FX_DIVIDE&&denominator.bytes[9]!=1) {
  denominator.bytes[9]=1;toggle_sign(&numerator);
 }
 if(numerator.bytes[0]>=0xf0u){*out=numerator;return FX_NUMERIC_OK;}
 if(!numerator.bytes[0]||!denominator.bytes[0]) {
  status=arithmetic(out,&numerator,&denominator,FX_DIVIDE);
  if(status==FX_NUMERIC_OK) {
   uint8_t coordinate_value[10];read_coordinate(coordinate_value,out);
   fx_raw_decimal_cleanup(coordinate_value);write_external(out,coordinate_value);
  }
  return status;
 }
 if(denominator.bytes[0]>=0xf0u){*out=denominator;return FX_NUMERIC_OK;}
 status=ratio_gcd(&common,&numerator,&denominator);
 if(status==FX_NUMERIC_OK)status=arithmetic(&numerator,&numerator,&common,FX_DIVIDE);
 if(status==FX_NUMERIC_OK)status=arithmetic(&denominator,&denominator,&common,FX_DIVIDE);
 if(status!=FX_NUMERIC_OK)return status;
 if(numerator.bytes[0]>=0xf0u){*out=numerator;return FX_NUMERIC_OK;}
 /* A denominator error created by reduction still enters raw divmod.
  * The prepared divider has no divisor-error admission. */
 if(denominator.bytes[8]<1&&denominator.bytes[0]<2) {
  uint8_t cleaned[10];read_coordinate(cleaned,&numerator);
  fx_raw_decimal_cleanup(cleaned);write_external(out,cleaned);return FX_NUMERIC_OK;
 }
 uint8_t nraw[10],draw[10],rraw[10],qraw[10];
 read_coordinate(nraw,&numerator);read_coordinate(draw,&denominator);
 status=coordinate_divmod(rraw,qraw,nraw,draw);
 if(status!=FX_NUMERIC_OK)return status;
 write_external(&remainder,rraw);write_external(&whole,qraw);
 return pack_fraction_fields(out,&remainder,&denominator,&whole);
}
static int is_fraction(const fx_number *value)
{
 return (value->bytes[0]&0xb0u)==0x20u;
}
static int is_integer(const fx_number *value)
{
 return raw_integer(value);
}
static fx_numeric_status plain_scalar(fx_number *out,const fx_number *input)
{
 fx_number unmarked=*input;unmarked.bytes[0]&=(uint8_t)~0x40u;
 if(is_fraction(&unmarked))return fx_raw_fraction_convert(out,&unmarked);
 if((unmarked.bytes[0]&0xf0u)!=0)return FX_NUMERIC_UNIMPLEMENTED;
 *out=unmarked;return FX_NUMERIC_OK;
}
static fx_numeric_status rational_value(fx_number *out,
 const fx_number *left,const fx_number *right,fx_binary_op operation,
 int fraction_preferred)
{
 ratio_parts a,b;fx_number numerator,denominator,first,second,result;
 fx_numeric_status status;unsigned markers;
 if(!out||!left||!right||operation>FX_DIVIDE)return FX_NUMERIC_INVALID;
 if(left->bytes[0]>=0xf0u||right->bytes[0]>=0xf0u) {
  fx_number_error(out,3);return FX_NUMERIC_OK;
 }
 markers=(left->bytes[0]&0x40u)+(right->bytes[0]&0x40u);
 /* Ordinary arithmetic keeps decimal operands. A fraction-preferred divide
  * additionally admits two integer scalars; raw fraction fields always enter
  * the component path when their counterpart is a fraction or integer. */
 int fraction_branch=(is_fraction(left)||is_integer(left))&&
                     (is_fraction(right)||is_integer(right))&&
                     (fraction_preferred||is_fraction(left)||is_fraction(right));
 if(!fraction_branch) {
  status=plain_scalar(&first,left);
  if(status==FX_NUMERIC_OK)status=plain_scalar(&second,right);
  if(status==FX_NUMERIC_OK)status=arithmetic(&result,&first,&second,operation);
  if(status!=FX_NUMERIC_OK)return status;
  goto finish;
 }
 status=parts(&a,left);if(status==FX_NUMERIC_OK)status=parts(&b,right);
 if(status!=FX_NUMERIC_OK)return status;
 if(operation==FX_ADD||operation==FX_SUBTRACT) {
  status=arithmetic(&first,&a.numerator,&b.denominator,FX_MULTIPLY);
  if(status==FX_NUMERIC_OK)status=arithmetic(&second,&b.numerator,&a.denominator,FX_MULTIPLY);
  if(status==FX_NUMERIC_OK)status=arithmetic(&denominator,&b.denominator,&a.denominator,FX_MULTIPLY);
  if(status==FX_NUMERIC_OK)status=arithmetic(&numerator,&first,&second,operation);
 } else {
  const fx_number *btop=operation==FX_MULTIPLY?&b.numerator:&b.denominator;
  const fx_number *bbottom=operation==FX_MULTIPLY?&b.denominator:&b.numerator;
  status=arithmetic(&numerator,&a.numerator,btop,FX_MULTIPLY);
  if(status==FX_NUMERIC_OK)status=arithmetic(&denominator,bbottom,&a.denominator,FX_MULTIPLY);
 }
 if(status==FX_NUMERIC_OK)status=reduce_components(&result,numerator,denominator,operation);
 if(status!=FX_NUMERIC_OK)return status;
finish:
 if(markers&&!fraction_preferred) {
  fx_decimal decimal;
  if(result.bytes[0]>=0xf0u)fx_number_error(&result,3);
  if((result.bytes[0]&0xf0u)==0x20u)status=fx_raw_fraction_convert(&result,&result);
  if(status!=FX_NUMERIC_OK)return status;
  if(((operation==FX_ADD||operation==FX_SUBTRACT)?markers==0x80u:markers==0x40u)&&
      fx_decimal_decode(&decimal,&result)==FX_NUMERIC_OK&&
      (!decimal.sign||decimal.exponent<7))result.bytes[0]|=0x40u;
 }
 *out=result;return FX_NUMERIC_OK;
}


fx_numeric_status fx_raw_rational_binary(fx_number *out,
                                         const fx_number *left,
                                         const fx_number *right,
                                         fx_binary_op operation,
                                         unsigned fraction_preferred,
                                         unsigned *native_status)
{
    fx_number a, b, result;
    fx_numeric_status status;
    if (!out || !left || !right || !native_status ||
        (unsigned)operation > (unsigned)FX_DIVIDE ||
        fraction_preferred > 1 ||
        (fraction_preferred && operation != FX_DIVIDE))
        return FX_NUMERIC_INVALID;
    a = *left;
    b = *right;
    status = rational_value(&result, &a, &b, operation,
                            (int)fraction_preferred);
    if (status != FX_NUMERIC_OK)
        return status;
    *out = result;
    *native_status = result.bytes[0] >= 0xf0 ? result.bytes[0] & 15u : 0;
    return FX_NUMERIC_OK;
}
