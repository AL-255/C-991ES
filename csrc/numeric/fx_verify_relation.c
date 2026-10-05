/* Finite VERIFY predicates, preserving the original guarded comparison
 *and optional quotient-equality stage. SPDX-License-Identifier: GPL-3.0-or-later */
#include "fx_verify_relation.h"
#include "fx_raw_fraction_convert.h"
#include "fx_surd_components.h"

/*15C82 converts only compactSURDs before its raw4F admission. It does
 *not clear marked rational6x into an ordinary rational20 field. */
static fx_numeric_status prepare(fx_number *out,const fx_number *input,
                                 uint8_t *ram)
{
    fx_number value=*input;
    fx_numeric_status status;
    if ((value.bytes[0]&0xf0)==0x80) {
        status=ram?fx_surd_components_convert_copy(ram,&value,&value):
                   fx_number_to_decimal(&value,&value);
        if (status!=FX_NUMERIC_OK) return status;
    }
    if (value.bytes[0]>0x4f) { *out=value; return FX_NUMERIC_OK; }
    value.bytes[0]&=(uint8_t)~0x40;
    if ((value.bytes[0]&0xb0)==0x20)
        status=fx_raw_fraction_convert(out,&value);
    else if (fx_number_kind(&value)==FX_NUMBER_DECIMAL) {
        *out=value; status=FX_NUMERIC_OK;
    } else return FX_NUMERIC_UNIMPLEMENTED;
    return status;
}

/*CD94 handles sign ordering before the guarded subtraction. The shared
 *subtraction kernel suppresses a residue after thirteen leading aligned
 *zeros; ordinary integer/mantissa ordering would miss that stage. */
static fx_numeric_status compare(uint8_t *order,const fx_number *left,
                                 const fx_number *right)
{
    fx_decimal a,b,difference;
    fx_number value;
    fx_numeric_status status;
    if (left->bytes[0]>=10 || right->bytes[0]>=10) {
        *order=0xf0; return FX_NUMERIC_OK;
    }
    if (fx_decimal_decode(&a,left)!=FX_NUMERIC_OK ||
        fx_decimal_decode(&b,right)!=FX_NUMERIC_OK)
        return FX_NUMERIC_UNIMPLEMENTED;
    if (!a.sign && !b.sign) { *order=1; return FX_NUMERIC_OK; }
    if (a.sign!=b.sign) {
        *order=(uint8_t)(a.sign<b.sign?2:4); return FX_NUMERIC_OK;
    }
    status=fx_decimal_subtract_cancel(&value,left,right);
    if (status!=FX_NUMERIC_OK) return status;
    if (fx_number_kind(&value)==FX_NUMBER_ERROR) {
        *order=0xf0; return FX_NUMERIC_OK;
    }
    if (fx_decimal_decode(&difference,&value)!=FX_NUMERIC_OK)
        return FX_NUMERIC_UNIMPLEMENTED;
    *order=(uint8_t)(!difference.sign?1:difference.sign<0?2:4);
    return FX_NUMERIC_OK;
}

fx_numeric_status fx_verify_relation(fx_number *out,
    const fx_number *left,const fx_number *right,uint8_t token,
    uint8_t ram[65536],uint8_t *truth,unsigned *native_status)
{
    fx_number rhs,lhs,quotient,one;
    fx_numeric_status status;
    uint8_t order,initial;
    int inclusive,yes;
    if (!out || !left || !right || !truth || !native_status)
        return FX_NUMERIC_INVALID;
    if (token!=0x94 && token!=0x95 && token!=0x96 &&
        token!=0x3c && token!=0x3d && token!=0x3e)
        return FX_NUMERIC_UNIMPLEMENTED;
    /*Both named inputs are saved before the eager output preparation; the
     *native right record has already been copied to its private field. */
    rhs=*right; lhs=*left;
    status=prepare(&rhs,&rhs,ram);
    if (status!=FX_NUMERIC_OK) return status;
    status=prepare(&lhs,&lhs,ram);
    if (status!=FX_NUMERIC_OK) return status;
    *out=lhs;
    status=compare(&order,&lhs,&rhs);
    if (status!=FX_NUMERIC_OK) return status;
    if (order==0xf0) {
        fx_number_error(out,3); *truth=0xf3; *native_status=3;
        return FX_NUMERIC_OK;
    }
    initial=order;
    inclusive=token==0x94 || token==0x95 || token==0x96 || token==0x3d;
    if (inclusive && order!=1) {
        status=fx_decimal_binary(&quotient,&lhs,&rhs,FX_DIVIDE);
        if (status!=FX_NUMERIC_OK) return status;
        *out=quotient;
        if (fx_number_kind(&quotient)!=FX_NUMBER_ERROR) {
            fx_decimal_from_u8(&one,1);
            status=compare(&order,&quotient,&one);
            if (status!=FX_NUMERIC_OK) return status;
            if (order!=1) order=initial;
        } else order=initial;
    }
    yes=token==0x94?(order==1 || order==2):
        token==0x96?(order==1 || order==4):
        token==0x3c?order==2:token==0x3e?order==4:order==1;
    if (token==0x95) yes=!yes;
    fx_decimal_from_u8(out,(uint8_t)yes);
    *truth=(uint8_t)yes; *native_status=0;
    return FX_NUMERIC_OK;
}
