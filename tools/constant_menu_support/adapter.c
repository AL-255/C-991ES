/* SPDX-License-Identifier: GPL-3.0-only */
#include "fx_constant_menu_controller.h"
#include "platform/fx_main_loop.h"
#include <stddef.h>
#include <string.h>
typedef struct {
    fx_constant_menu_controller child;
    fx_parameter_menu_controller parent;
    fx_parameter_menu_services services;
    uint8_t entry;
} constant_test_state;
size_t constant_state_size(void) { return sizeof(constant_test_state); }
int constant_begin(fx_platform *p,constant_test_state *s,uint8_t entry,uint8_t trigger)
{
    memset(s,0,sizeof *s);s->entry=entry;
    if(entry!=3)return fx_constant_menu_controller_begin(p,&s->child,
        (fx_constant_menu_kind)entry,trigger);
    fx_constant_menu_controller_services(&s->services,&s->child);
    return fx_parameter_menu_controller_begin(p,&s->parent,&s->services);
}
int constant_tick(fx_platform *p,constant_test_state *s)
{ return s->entry==3?(int)fx_parameter_menu_controller_tick(p,&s->parent):
    (int)fx_constant_menu_controller_tick(p,&s->child); }
int constant_timer(fx_platform *p,constant_test_state *s)
{ return s->entry==3?(int)fx_parameter_menu_controller_resume_timer(p,&s->parent):
    (int)fx_constant_menu_controller_resume_timer(p,&s->child); }
int constant_finish(constant_test_state *s,uint8_t *byte)
{ return s->entry==3?(int)fx_parameter_menu_controller_finish(&s->parent,byte):
    (int)fx_constant_menu_controller_finish(&s->child,byte); }
unsigned constant_export(const constant_test_state *s)
{ return s->entry==3?fx_parameter_menu_controller_export_mask(&s->parent):
    fx_constant_menu_controller_export_mask(&s->child); }
unsigned constant_period(const constant_test_state *s)
{ return s->entry==3?fx_parameter_menu_controller_timer_period(&s->parent):
    fx_constant_menu_controller_timer_period(&s->child); }
size_t constant_abi(unsigned n)
{
    const size_t f[]={sizeof(fx_platform),offsetof(fx_platform,rom),
        offsetof(fx_platform,rom_size),offsetof(fx_platform,ram),
        offsetof(fx_platform,callback_pending),offsetof(fx_platform,status)};
    return n<sizeof f/sizeof f[0]?f[n]:0;
}
int constant_main_complete(fx_platform *p,uint8_t byte,uint8_t *last,uint8_t *wait)
{
    fx_main_loop main;fx_main_loop_begin(&main);
    main.phase=FX_MAIN_HANDLER_PENDING;main.pending_request=FX_MAIN_PARAMETER_MENU;
    main.wait_required=1;
    int result=fx_main_loop_accept_handler(p,&main,byte);
    *last=main.last_menu_result;*wait=main.wait_required;
    return result;
}
/* Host invalid/no-provider requests are not firmware completion injection. */
int constant_unknown_service(fx_platform *p,uint8_t kind)
{
    fx_constant_menu_controller s;fx_parameter_menu_services services;
    fx_parameter_menu_request request={(fx_parameter_menu_child)kind,0,0};
    fx_constant_menu_controller_services(&services,&s);
    int status=services.begin(p,services.context,&request);
    if(status!=FX_PARAMETER_MENU_REQUEST)return -99;
    if(services.tick(p,services.context)!=FX_PARAMETER_MENU_REQUEST ||
       services.resume_timer(p,services.context)!=FX_PARAMETER_MENU_REQUEST ||
       services.finish(services.context,0)!=FX_PARAMETER_MENU_INVALID)return -98;
    return status;
}
