/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_linalg_controller.h"
#include "../platform/fx_persistent.h"
#include "../platform/fx_boot.h"
#include "../parse/fx_eval_storage.h"
#include "fx_keys.h"
#include <string.h>

enum { BANK_READY=1, BANK_INPUT, BANK_DONE, BANK_REQUEST, BANK_RESET };
static uint8_t get(fx_platform *p,uint16_t address)
{ return fx_data_read(p,0,address); }
static void put(fx_platform *p,uint16_t address,uint8_t value)
{ fx_data_write(p,0,address,value); }
static uint16_t word(fx_platform *p,uint16_t address)
{ return (uint16_t)(get(p,address)|(uint16_t)get(p,(uint16_t)(address+1))<<8); }
static fx_linalg_ui_status done(fx_linalg_controller *s,uint8_t returned)
{ s->returned=returned;s->phase=BANK_DONE;return FX_LINALG_UI_COMPLETE; }

fx_numeric_status fx_linalg_ui_store_cell(fx_platform *p,uint16_t source,
    uint8_t slot,uint8_t row,uint8_t column,uint8_t *native_status)
{
    if (!p || !p->ram || !native_status) return FX_NUMERIC_INVALID;
    *native_status=0;
    if (slot>5 || row>get(p,(uint16_t)(0x80e0+2u*slot)) ||
        column>get(p,(uint16_t)(0x80e1+2u*slot))) {
        *native_status=2; return FX_NUMERIC_OK;
    }
    if (!row || !column || source<0x8000 || source>65526 ||
        (source<0x8e00 && (unsigned)source+10u>0x8b00))
        return FX_NUMERIC_UNIMPLEMENTED;
    uint8_t index=(uint8_t)(9u*slot+3u*(row-1u)+column-1u);
    uint16_t destination=(uint16_t)(0x829e + 10u*index);
    for (unsigned n=10;n;n-=2) {
        uint8_t low=get(p,(uint16_t)(source+n-2));
        uint8_t high=get(p,(uint16_t)(source+n-1));
        put(p,(uint16_t)(destination+n-2),low);
        put(p,(uint16_t)(destination+n-1),high);
    }
    return FX_NUMERIC_OK;
}

fx_linalg_ui_status fx_linalg_controller_begin(fx_platform *p,
    fx_linalg_controller *s,const fx_calculus_control *control)
{
    if (!p || !p->ram || !p->rom || !s) return FX_LINALG_UI_INVALID;
    fx_calculus_control saved_control={0};
    if (control) saved_control=*control;
    memset(s,0,sizeof *s);s->active=1;s->cancellation=saved_control;
    s->slot=get(p,0x80fa);
    uint16_t dims=(uint16_t)(0x80e0+2u*s->slot);
    s->rows=get(p,dims);s->columns=get(p,(uint16_t)(dims+1));
    /* ECAA checks dimension bytes before the selected-pointer/grid body. */
    if (!s->rows || !s->columns) {
        put(p,0x80fb,0);put(p,0x80fc,1);
        if (fx_boot_initialize_editor(p,2)!=FX_BOOT_READY)
            return FX_LINALG_UI_UNIMPLEMENTED;
        return done(s,0);
    }
    if (s->slot>3 || s->rows>3 || s->columns>3 ||
        (get(p,0x80f9)!=6 && get(p,0x80f9)!=7) ||
        (get(p,0x80fc)!=19 && get(p,0x80fc)!=20))
        return FX_LINALG_UI_UNIMPLEMENTED;
    s->phase=BANK_READY;return FX_LINALG_UI_PREPARED;
}

static fx_linalg_ui_status input_status(fx_linalg_controller *s,fx_ui_status status)
{
    if (status==FX_UI_COMPLETE) {
        uint8_t context_return;
        if (fx_ui_controller_finish(&s->input,&context_return)!=FX_UI_COMPLETE)
            return FX_LINALG_UI_INVALID;
        /* ECE8 returns1 after the subordinateD9EE call, independently of
         * that wrapper's context return byte. */
        return done(s,1);
    }
    if (status==FX_UI_PREPARED) return FX_LINALG_UI_PREPARED;
    if (status==FX_UI_WAIT) return FX_LINALG_UI_WAIT;
    if (status==FX_UI_EXPORT) return FX_LINALG_UI_EXPORT;
    if (status==FX_UI_RESET) {s->phase=BANK_RESET;return FX_LINALG_UI_RESET;}
    if (status==FX_UI_HANDLER_REQUEST) {
        s->phase=BANK_REQUEST;return FX_LINALG_UI_REQUEST;
    }
    return FX_LINALG_UI_UNIMPLEMENTED;
}

static fx_linalg_ui_status refresh(fx_platform *p,fx_linalg_controller *s)
{
    uint8_t row=get(p,0x811d),column=get(p,0x811e);
    if (!row || row>s->rows || !column || column>s->columns)
        return FX_LINALG_UI_UNIMPLEMENTED;
    uint16_t pointer_address=(uint16_t)(0xf94+18u*s->slot+6u*row+2u*column);
    s->selected_address=word(p,pointer_address);
    /* D7C6 clears imaginary BEFORE loading the selected real record. */
    for (unsigned n=0;n<10;++n) put(p,(uint16_t)(0x814a+n),0);
    fx_number selected;
    if (s->selected_address) {
        for (unsigned n=0;n<10;++n)
            selected.bytes[n]=get(p,(uint16_t)(s->selected_address+n));
    } else fx_number_error(&selected,13);
    for (unsigned n=0;n<10;++n) put(p,(uint16_t)(0x8140+n),selected.bytes[n]);
    if (fx_key_is_menu_token(p,get(p,0x80f5))) {
        if (!s->selected_address) return done(s,1);
        s->phase=BANK_INPUT;
        return input_status(s,fx_ui_controller_begin(p,&s->input,0,&s->cancellation));
    }
    /* Snapshot only after the native selected-cache writes; grid cells are
     * ordinary physical records and no callback runs during this painter. */
    fx_linalg_value value;memset(&value,0,sizeof value);
    value.rows=s->rows;value.columns=s->columns;
    uint16_t payload=(uint16_t)(0x829e + 90u*s->slot);
    for (unsigned i=0;i<9;++i)
        for (unsigned n=0;n<10;++n)
            value.cells[i].bytes[n]=get(p,(uint16_t)(payload+10u*i+n));
    fx_render render={p->rom,p->rom_size,p->ram};
    if (fx_display_linalg_value(&render,&value,s->slot,row,column)!=1)
        return FX_LINALG_UI_UNIMPLEMENTED;
    return done(s,1);
}

fx_linalg_ui_status fx_linalg_controller_tick(fx_platform *p,fx_linalg_controller *s)
{
    if (!p || !p->ram || !s || !s->active) return FX_LINALG_UI_INVALID;
    if (s->phase==BANK_DONE) return FX_LINALG_UI_COMPLETE;
    if (s->phase==BANK_RESET) return FX_LINALG_UI_RESET;
    if (s->phase==BANK_REQUEST) return FX_LINALG_UI_REQUEST;
    if (s->phase==BANK_INPUT) return input_status(s,fx_ui_controller_tick(p,&s->input));
    if (s->phase!=BANK_READY) return FX_LINALG_UI_INVALID;
    uint8_t token=get(p,0x80f5);
    if (get(p,0x80f7) && token>=23 && token<=25) {
        uint8_t destination=(uint8_t)(token-23);
        if (destination!=s->slot) {
            fx_eval_storage storage={p->ram,65536u,p->rom,p->rom_size};
            if (fx_eval_storage_copy_slot(&storage,destination,s->slot)!=FX_NUMERIC_OK)
                return FX_LINALG_UI_UNIMPLEMENTED;
        }
        s->slot=destination;put(p,0x80fa,destination);
        fx_result_reset_layout_and_flags(p);
    } else if (fx_key_is_direction_token(p,token)) {
        (void)fx_acquire_busy(p);
        fx_render render={p->rom,p->rom_size,p->ram};
        int movement=fx_linalg_selection_event(&render,s->rows,s->columns,token);
        if (movement<0) return FX_LINALG_UI_UNIMPLEMENTED;
        if (movement) {fx_clear_busy(p);return done(s,1);}
    }
    return refresh(p,s);
}

fx_linalg_ui_status fx_linalg_controller_resume_input(fx_platform *p,
    fx_linalg_controller *s,uint8_t action,uint8_t context_return)
{
    if (!p || !s || !s->active || s->phase!=BANK_REQUEST)
        return FX_LINALG_UI_INVALID;
    s->phase=BANK_INPUT;
    return input_status(s,fx_ui_controller_resume(p,&s->input,action,context_return));
}
fx_linalg_ui_status fx_linalg_controller_finish(fx_linalg_controller *s,uint8_t *returned)
{
    if (!s || !s->active || (s->phase!=BANK_DONE && s->phase!=BANK_RESET))
        return FX_LINALG_UI_INVALID;
    if (returned) *returned=s->returned;
    s->active=0;
    return s->phase==BANK_RESET ? FX_LINALG_UI_RESET : FX_LINALG_UI_COMPLETE;
}
