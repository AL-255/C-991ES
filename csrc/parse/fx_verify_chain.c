/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_verify_chain.h"
#include "fx_eval_rich.h"
#include "../numeric/fx_verify_relation.h"
#include <string.h>

static uint16_t byte_advance(uint16_t source,int amount)
{
    return (uint16_t)((source&0xff00u)|(uint8_t)((uint8_t)source+amount));
}

static uint8_t source_byte(const fx_eval_storage *storage,uint16_t address)
{
    if(address>=0x8000u)return storage->ram[address];
    return storage->rom && address<storage->rom_size ? storage->rom[address] : 0xff;
}

static void write_boolean(uint8_t *ram,uint16_t address,uint8_t truth)
{
    fx_number value;
    fx_decimal_from_u8(&value,truth);
    /*CDAE emits five word stores. EA+ aligns after each word, so odd
     * destinations overlap the first word and retain the tenth byte.*/
    for(unsigned word=0;word<5;++word){
        ram[address]=value.bytes[2u*word];
        ram[address+1u]=value.bytes[2u*word+1u];
        address=(uint16_t)((address+2u)&0xfffeu);
    }
}

static int relation_token(uint8_t nibble,uint8_t *token)
{
    static const uint8_t tokens[6]={0x94,0x95,0x96,0x3c,0x3d,0x3e};
    uint8_t index=(uint8_t)(nibble&7u);
    if(nibble&8u)index=(uint8_t)(index+3u);
    index=(uint8_t)(index-4u);
    if(index>=6)return 0;
    *token=tokens[index];return 1;
}

static fx_eval_status operand(fx_eval_storage *storage,uint16_t *cursor,
    uint16_t sink,size_t capacity,const fx_calculus_control *control,
    fx_complex *value,fx_verify_chain_result *out)
{
    fx_eval_result parsed;
    fx_eval_source source={*cursor,sink,NULL,NULL};
    uint16_t next=*cursor;
    size_t length=0,available=65536u-*cursor;
    /*The named scalar transport admits RAM sources. A wrapped native ROM
     *continuation is a distinct explicit boundary after preceding effects.*/
    if(*cursor<0x8000u)return FX_EVAL_UNIMPLEMENTED;
    if(available>capacity)available=capacity;
    while(length<available && storage->ram[*cursor+length])++length;
    if(length==available)return FX_EVAL_RESOURCE_LIMIT;
    memset(&parsed,0,sizeof parsed);
    ++out->operands;
    fx_eval_status status=fx_evaluate_verify_operand_source(length+1u,
        storage,&source,&next,control,&parsed);
    out->unsupported_token=parsed.unsupported_token;
    if(status>=0)*cursor=next;
    value->real=parsed.value[0];value->imaginary=parsed.value[1];
    return status;
}

fx_eval_status fx_verify_chain(fx_eval_storage *storage,uint16_t source,
    uint16_t output_address,size_t input_capacity,
    const fx_calculus_control *control,fx_verify_chain_result *out)
{
    fx_complex current,other;
    fx_eval_status status;
    fx_eval_rich_context poll_context;
    uint8_t family,nibble,token,truth;
    unsigned native_status;
    fx_number value;
    if(!storage || !storage->ram || storage->ram_size!=65536u || !out ||
       storage->ram[0x80f9]!=0x89 || source<0x8000u ||
       output_address<0x8000u || output_address>65516u || !input_capacity)
        return FX_EVAL_UNIMPLEMENTED;
    memset(out,0,sizeof *out);out->source=source;out->truth=1;
    fx_eval_rich_context_default(&poll_context,0x89);
    if(control){poll_context.cancelled=control->cancelled;poll_context.userdata=control->userdata;}
    status=operand(storage,&source,output_address,input_capacity,control,&current,out);
    if(status)goto done;
    source=byte_advance(source,-1);
    nibble=source_byte(storage,source);
    if(!nibble){status=FX_EVAL_SYNTAX;goto done;}
    nibble&=15u;family=nibble==13?nibble:(uint8_t)(nibble&7u);
    for(;;){
        if(fx_eval_rich_poll(storage,&out->cancellation_checks,&poll_context)){
            status=FX_EVAL_CANCELLED;goto done;
        }
        source=byte_advance(source,1);
        status=operand(storage,&source,output_address,input_capacity,control,&other,out);
        if(status)goto done;
        if(!relation_token(nibble,&token)){status=FX_EVAL_UNIMPLEMENTED;goto done;}
        fx_numeric_status host=fx_verify_relation(&value,&current.real,&other.real,
            token,storage->ram,&truth,&native_status);
        if(host!=FX_NUMERIC_OK){status=FX_EVAL_UNIMPLEMENTED;goto done;}
        ++out->relations;
        if(native_status){status=(fx_eval_status)native_status;goto done;}
        out->truth&=truth;
        source=byte_advance(source,-1);
        nibble=source_byte(storage,source);
        if(!nibble){
            write_boolean(storage->ram,output_address,out->truth);
            write_boolean(storage->ram,(uint16_t)(output_address+10u),0);
            status=FX_EVAL_OK;goto done;
        }
        current.real=other.real; /*69AE copies only the next scalar record.*/
        nibble&=15u;
        if(nibble==13)continue;
        if(family==13)family=(uint8_t)(nibble&7u);
        else if((nibble&7u)!=family){status=FX_EVAL_SYNTAX;goto done;}
    }
done:
    out->source=source;out->native_status=status;
    return status;
}
