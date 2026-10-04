#include "platform/fx_runtime.h"
#include "table/fx_table_body.h"
#include <stddef.h>
size_t table_body_size(void){return sizeof(fx_table_body);}
unsigned table_body_field(const fx_table_body *s,unsigned n){const unsigned f[]={s->phase,s->returned,s->table.request,s->input.phase,s->input.request};return n<5?f[n]:0;}
int table_body_from_runtime(fx_platform *p,fx_table_body *b,fx_runtime *s){if(s->phase!=FX_RUNTIME_BODY||s->request.kind!=FX_RUNTIME_MAIN_BODY)return FX_UI_INVALID;return fx_table_body_begin(p,b,(fx_main_request)s->request.operation,&s->cancellation);}
size_t ui_size(void){return sizeof(fx_ui_controller);}
size_t ui_table_offset(void){return offsetof(fx_ui_controller,table);}
