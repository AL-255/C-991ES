/* Opaque comparison adapter; production calls stay on their named C APIs. */
#include "ui/fx_polynomial_equation_controller.h"
#include "ui/fx_mode_setup.h"
#include <stddef.h>
#include <string.h>
unsigned polynomial_c_polls,polynomial_cancel_at;
uint8_t polynomial_c_poll_ram[256][65536];
void __real_fx_timer_start(fx_platform *,uint16_t);
void __wrap_fx_timer_start(fx_platform *p,uint16_t period)
{
    __real_fx_timer_start(p,period);
    if(period==0x129a) {
        if(polynomial_c_polls<256)
            memcpy(polynomial_c_poll_ram[polynomial_c_polls],p->ram,65536);
        ++polynomial_c_polls;
    }
}
void polynomial_c_reset(unsigned cancel_at)
{polynomial_c_polls=0;polynomial_cancel_at=cancel_at;}
static int cancelled(void *userdata)
{(void)userdata;return polynomial_cancel_at&&polynomial_c_polls==polynomial_cancel_at;}
int polynomial_begin(fx_platform *p,fx_polynomial_equation_controller *s)
{fx_calculus_control control={cancelled,NULL};return fx_polynomial_equation_controller_begin(p,s,&control);}
void polynomial_initialize(fx_platform *p){fx_mode_initialize_equation(p,21);}
size_t polynomial_ui_size(void){return sizeof(fx_ui_controller);}
size_t polynomial_controller_size(void){return sizeof(fx_polynomial_equation_controller);}
unsigned polynomial_ui_return(const fx_ui_controller *s){return s->context.return_value;}
unsigned polynomial_return(const fx_polynomial_equation_controller *s){return s->returned;}
size_t polynomial_host_abi(unsigned n)
{
    const size_t values[]={sizeof(fx_platform),offsetof(fx_platform,rom),
        offsetof(fx_platform,rom_size),offsetof(fx_platform,ram),
        offsetof(fx_platform,callback_pending),offsetof(fx_platform,status),
        sizeof(fx_calculus_control),offsetof(fx_calculus_control,cancelled),
        offsetof(fx_calculus_control,userdata),FX_UI_WAIT,FX_UI_COMPLETE,
        FX_UI_PREPARED};
    return n<sizeof values/sizeof values[0]?values[n]:(size_t)-1;
}
