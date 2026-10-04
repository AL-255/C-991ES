#include "ui/fx_equation_controller.h"
#include <stddef.h>
size_t eq_ui_size(void){return sizeof(fx_ui_controller);}
unsigned eq_ui_field(const fx_ui_controller*s,unsigned n){return n==0?s->context.return_value:n==1?s->handler_action:s->request;}
int eq_grid(fx_platform*p){fx_data_write(p,0,0x8129,0);fx_data_write(p,0,0x80fd,0);return fx_equation_present_coefficients(p);}

size_t eq_controller_size(void){return sizeof(fx_equation_controller);}
unsigned eq_controller_return(const fx_equation_controller*s){return s->returned;}
size_t eq_abi(unsigned n){const size_t fields[]={sizeof(fx_platform),offsetof(fx_platform,rom),offsetof(fx_platform,rom_size),offsetof(fx_platform,ram),offsetof(fx_platform,callback_pending),offsetof(fx_platform,status),sizeof(fx_calculus_control),offsetof(fx_calculus_control,cancelled),offsetof(fx_calculus_control,userdata)};return n<sizeof fields/sizeof fields[0]?fields[n]:0;}
