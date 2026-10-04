/* GPL-3.0-only. Opaque real-child and installed-provider test transport. */
#include "ui/fx_distribution_menu_controller.h"
#include "platform/fx_main_loop.h"
#include "platform/fx_boot.h"
#include <stddef.h>
#include <string.h>
typedef struct {
    fx_distribution_menu_controller child;
    fx_parameter_menu_controller parent;
    fx_parameter_menu_services services;
    uint8_t wrapped;
} distribution_test_state;
size_t distribution_state_size(void) { return sizeof(distribution_test_state); }
int distribution_begin(fx_platform *p,distribution_test_state *s,uint8_t page,uint8_t wrapped)
{
    memset(s,0,sizeof *s);s->wrapped=wrapped;
    if(!wrapped)return fx_distribution_menu_controller_begin(p,&s->child,page);
    fx_distribution_menu_controller_services(&s->services,&s->child);
    return fx_parameter_menu_controller_begin(p,&s->parent,&s->services);
}
int distribution_tick(fx_platform *p,distribution_test_state *s)
{ return s->wrapped?(int)fx_parameter_menu_controller_tick(p,&s->parent):
    (int)fx_distribution_menu_controller_tick(p,&s->child); }
int distribution_timer(fx_platform *p,distribution_test_state *s)
{ return s->wrapped?(int)fx_parameter_menu_controller_resume_timer(p,&s->parent):
    (int)fx_distribution_menu_controller_resume_timer(p,&s->child); }
int distribution_finish(distribution_test_state *s,uint8_t *byte)
{ return s->wrapped?(int)fx_parameter_menu_controller_finish(&s->parent,byte):
    (int)fx_distribution_menu_controller_finish(&s->child,byte); }
unsigned distribution_field(const distribution_test_state *s,unsigned n)
{
    const unsigned f[]={s->child.initial_page,s->child.kind,s->child.menu.page,
        s->child.returned,s->parent.returned,s->parent.request.kind,
        s->parent.request.page,s->parent.request.argument};
    return n<sizeof f/sizeof f[0]?f[n]:0xffffffffu;
}
unsigned distribution_export(const distribution_test_state *s)
{ return s->wrapped?fx_parameter_menu_controller_export_mask(&s->parent):
    fx_distribution_menu_controller_export_mask(&s->child); }
unsigned distribution_period(const distribution_test_state *s)
{ return s->wrapped?fx_parameter_menu_controller_timer_period(&s->parent):
    fx_distribution_menu_controller_timer_period(&s->child); }
size_t distribution_abi(unsigned n)
{
    const size_t f[]={sizeof(fx_platform),offsetof(fx_platform,rom),
        offsetof(fx_platform,rom_size),offsetof(fx_platform,ram),
        offsetof(fx_platform,callback_pending),offsetof(fx_platform,status)};
    return n<sizeof f/sizeof f[0]?f[n]:0;
}
int distribution_main_complete(fx_platform *p,uint8_t byte,uint8_t *last,uint8_t *wait)
{
    fx_main_loop main;fx_main_loop_begin(&main);
    main.phase=FX_MAIN_HANDLER_PENDING;main.pending_request=FX_MAIN_PARAMETER_MENU;
    main.wait_required=1;
    int result=fx_main_loop_accept_handler(p,&main,byte);
    *last=main.last_menu_result;*wait=main.wait_required;
    return result;
}
/* Narrow real bus-write observation for the standalone1DF7E dependency. */
unsigned distribution_c_order_count;
uint16_t distribution_c_order_address[64];
uint8_t distribution_c_order_value[64];
static unsigned distribution_c_order_enabled;
void __real_fx_data_write(fx_platform *,uint8_t,uint16_t,uint8_t);
void __wrap_fx_data_write(fx_platform *p,uint8_t segment,uint16_t address,uint8_t value)
{
    if(distribution_c_order_enabled && !segment && distribution_c_order_count<64) {
        unsigned i=distribution_c_order_count++;
        distribution_c_order_address[i]=address;distribution_c_order_value[i]=value;
    }
    __real_fx_data_write(p,segment,address,value);
}
void distribution_initialize_mode12(fx_platform *p)
{
    distribution_c_order_count=0;distribution_c_order_enabled=1;
    fx_boot_initialize_mode12(p);
    distribution_c_order_enabled=0;
}
