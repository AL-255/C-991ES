/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_error_boundary.h"
#include "ui/fx_annunciator.h"
#include "ui/fx_key_dispatch.h"

static fx_key_controller_status begin_wait(fx_platform *p,fx_key_controller *s,int header)
{
    if (header && !fx_data_read(p,0,0x80fb) && fx_annunciator_draw(p))
        return FX_KEY_CONTROLLER_UNIMPLEMENTED;
    if (fx_key_wait_begin_host(p,&s->wait)) return FX_KEY_CONTROLLER_UNIMPLEMENTED;
    return FX_KEY_CONTROLLER_WAIT;
}

static fx_key_controller_status tick_key(fx_platform *p,fx_key_controller *s)
{
    if (!p || !s || !s->active) return FX_KEY_CONTROLLER_INVALID;
    if (s->event) return (fx_key_controller_status)s->event;
    if (s->export_mask && !s->wait.active) {
        s->export_mask=0;
        return begin_wait(p,s,0);
    }
    s->export_mask=0;
    int ready=fx_key_wait_tick(p,&s->wait);
    if (ready<0) return FX_KEY_CONTROLLER_UNIMPLEMENTED;
    if (!ready) return FX_KEY_CONTROLLER_WAIT;
    if (fx_key_wait_finish_host(p,&s->wait,&s->raw_key))
        return FX_KEY_CONTROLLER_UNIMPLEMENTED;
    if (s->raw_key.rows==0x80) {
        uint8_t columns=s->raw_key.columns;
        if (columns==0x80 || columns==0x40) {
            fx_host_write_framebuffer_fields(p,&s->host);
            if (fx_host_write_numeric_packet_fields(p,&s->host) ||
                fx_host_write_text_packet_fields(p,&s->host))
                return FX_KEY_CONTROLLER_UNIMPLEMENTED;
            s->export_mask=FX_KEY_EXPORT_STATUS|FX_KEY_EXPORT_FRAMEBUFFER|FX_KEY_EXPORT_NUMBER;
        } else if (columns==0x20 || columns==0x10) {
            if (columns==0x10) fx_data_write(p,0,s->host.text,0);
            if (fx_host_write_text_packet_fields(p,&s->host))
                return FX_KEY_CONTROLLER_UNIMPLEMENTED;
            s->export_mask=FX_KEY_EXPORT_STATUS;
            if (columns==0x10) {
                s->event=FX_KEY_CONTROLLER_RESET;return FX_KEY_CONTROLLER_RESET;
            }
        }
        if (s->export_mask) return FX_KEY_CONTROLLER_EXPORT;
    }
    fx_data_write(p,0,s->host.text,0);
    if (fx_host_write_text_packet_fields(p,&s->host))
        return FX_KEY_CONTROLLER_UNIMPLEMENTED;
    uint8_t mapped=fx_key_map_current(p,s->raw_key);
    int processed=fx_key_process_token(p,mapped,s->host.wait_flag,&s->token);
    if (processed<0) return FX_KEY_CONTROLLER_UNIMPLEMENTED;
    if (!processed) return begin_wait(p,s,1);
    s->event=FX_KEY_CONTROLLER_TOKEN;return FX_KEY_CONTROLLER_TOKEN;
}

fx_key_controller_status fx_error_event_tick_export_boundary(fx_platform *p,
                                                             fx_error_event *s)
{
    if (!p || !s || !s->active) return FX_KEY_CONTROLLER_INVALID;
    if (s->event) return (fx_key_controller_status)s->event;
    fx_key_controller_status status=tick_key(p,&s->key);
    if (status==FX_KEY_CONTROLLER_TOKEN) {
        uint8_t token;
        (void)fx_key_controller_finish(&s->key,&token);
        if (fx_error_accepts_token(p,token)) {
            s->token=token;s->event=FX_KEY_CONTROLLER_TOKEN;
            return FX_KEY_CONTROLLER_TOKEN;
        }
        return fx_key_controller_begin(p,&s->key);
    }
    if (status==FX_KEY_CONTROLLER_RESET) {
        (void)fx_key_controller_finish(&s->key,&s->token);
        s->event=FX_KEY_CONTROLLER_RESET;
    }
    return status;
}
