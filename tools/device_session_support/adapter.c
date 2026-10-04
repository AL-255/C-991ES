/* Test transport: only the public opaque device API, no writable RAM seam. */
#include "app/fx_device_session.h"
#include <stddef.h>
fx_device_session *device_create_seed(const uint8_t *seed)
{
    fx_device_configuration config={seed,seed?65536u:0u,seed?seed[0xf050]:0};
    return fx_device_session_create(seed?&config:NULL);
}
unsigned device_field(const fx_device_session *session,unsigned index)
{
    fx_device_snapshot s;
    if(fx_device_session_snapshot(session,&s))return 0xffffffffu;
    const unsigned fields[]={s.phase,s.event,s.main_request,s.wait_required,
        s.last_menu_result,s.timer_pending,s.timer_period,s.export_mask,s.returned,
        s.request.kind,s.request.operation,s.request.argument,s.input_context_return,
        s.input_action,s.mode_page,s.bank_page,s.mode_request,s.steps,
        s.unsupported_token,s.mode_result,s.bank_result,s.request.expression_address,
        s.request.result_address,s.request.prepared_source,s.request.current_source,
        (unsigned)s.last_status,s.memory_status,s.active,s.callback_pending,
        s.key_columns,s.key_rows,s.host_wait};
    return index<sizeof fields/sizeof fields[0]?fields[index]:0xffffffffu;
}
int device_framebuffer(const fx_device_session *session,uint8_t *output)
{
    fx_device_snapshot s;
    if(!output || fx_device_session_snapshot(session,&s))return -1;
    for(unsigned i=0;i<FX_DEVICE_FRAMEBUFFER_BYTES;++i)output[i]=s.framebuffer[i];
    return 0;
}
/* Actual dangerous aliases must be rejected without overwriting the object. */
int device_alias_guard(fx_device_session *session,unsigned which)
{
    if(which==0)return fx_device_session_snapshot(session,(fx_device_snapshot *)session);
    if(which==1)return fx_device_session_read_ram(session,0,(uint8_t *)session,1);
    return fx_device_session_read_ram(session,0,(uint8_t *)session,0);
}
fx_device_session *device_create_config(const uint8_t *seed,size_t bytes,uint8_t variant)
{
    fx_device_configuration config={seed,bytes,variant};
    return fx_device_session_create(&config);
}
