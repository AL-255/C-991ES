/* GPL-3.0-only. Opaque real-child and installed-provider test transport. */
#include "ui/fx_statistics_menu_controller.h"
#include "platform/fx_main_loop.h"
#include "platform/fx_boot.h"
#include <stddef.h>
#include <string.h>
typedef struct {
    fx_statistics_menu_controller child;
    fx_parameter_menu_controller parent;
    fx_parameter_menu_services services;
    uint8_t wrapped;
} statistics_test_state;
size_t statistics_state_size(void) { return sizeof(statistics_test_state); }
int statistics_begin(fx_platform *p,statistics_test_state *s,uint8_t page,uint8_t constraint,uint8_t wrapped)
{
    memset(s,0,sizeof *s);s->wrapped=wrapped;
    if(!wrapped)return fx_statistics_menu_controller_begin(p,&s->child,page,constraint);
    fx_statistics_menu_controller_services(&s->services,&s->child);
    return fx_parameter_menu_controller_begin(p,&s->parent,&s->services);
}
int statistics_tick(fx_platform *p,statistics_test_state *s)
{ return s->wrapped?(int)fx_parameter_menu_controller_tick(p,&s->parent):
    (int)fx_statistics_menu_controller_tick(p,&s->child); }
int statistics_timer(fx_platform *p,statistics_test_state *s)
{ return s->wrapped?(int)fx_parameter_menu_controller_resume_timer(p,&s->parent):
    (int)fx_statistics_menu_controller_resume_timer(p,&s->child); }
int statistics_finish(statistics_test_state *s,uint8_t *byte)
{ return s->wrapped?(int)fx_parameter_menu_controller_finish(&s->parent,byte):
    (int)fx_statistics_menu_controller_finish(&s->child,byte); }
unsigned statistics_field(const statistics_test_state *s,unsigned n)
{
    const unsigned f[]={s->child.initial_page,s->child.constraint,s->child.menu.page,
        s->child.returned,s->parent.returned,s->parent.request.kind,
        s->parent.request.page,s->parent.request.argument};
    return n<sizeof f/sizeof f[0]?f[n]:0xffffffffu;
}
unsigned statistics_export(const statistics_test_state *s)
{ return s->wrapped?fx_parameter_menu_controller_export_mask(&s->parent):
    fx_statistics_menu_controller_export_mask(&s->child); }
unsigned statistics_period(const statistics_test_state *s)
{ return s->wrapped?fx_parameter_menu_controller_timer_period(&s->parent):
    fx_statistics_menu_controller_timer_period(&s->child); }
size_t statistics_abi(unsigned n)
{
    const size_t f[]={sizeof(fx_platform),offsetof(fx_platform,rom),
        offsetof(fx_platform,rom_size),offsetof(fx_platform,ram),
        offsetof(fx_platform,callback_pending),offsetof(fx_platform,status)};
    return n<sizeof f/sizeof f[0]?f[n]:0;
}
int statistics_main_complete(fx_platform *p,uint8_t byte,uint8_t *last,uint8_t *wait)
{
    fx_main_loop main;fx_main_loop_begin(&main);
    main.phase=FX_MAIN_HANDLER_PENDING;main.pending_request=FX_MAIN_PARAMETER_MENU;
    main.wait_required=1;
    int result=fx_main_loop_accept_handler(p,&main,byte);
    *last=main.last_menu_result;*wait=main.wait_required;
    return result;
}
