/* Test-only semantic entry adapter; no ROM execution. */
#include "../../csrc/render/fx_result_verify.h"
#include "../../csrc/render/fx_result_special.h"
#include "../../csrc/render/fx_result_complex.h"
#include <stddef.h>

int mode137_format_address(fx_render *render, uint16_t source, int raw_leaf,
    uint8_t *tokens, size_t capacity, fx_format_result *result)
{
    fx_number value;
    value.bytes[0] = render->memory[source];
    value.bytes[1] = render->memory[(uint16_t)(source+1)];
    uint16_t tail = (uint16_t)((source+2)&0xfffeu);
    for (unsigned n=2;n<10;++n)
        value.bytes[n]=render->memory[(uint16_t)(tail+n-2)];
    if (!raw_leaf && (value.bytes[0]&0xf0)==0xf0) {
        fx_format_options options=fx_format_default_options();
        return fx_format_number(&value,&options,tokens,capacity,result);
    }
    return fx_format_verify_result(render,&value,tokens,capacity,result);
}

int mode137_display(fx_render *render, uint16_t source, unsigned entry,
                    fx_box *box)
{
    uint8_t phase=render->memory[0x80fe];
    if (entry==0x37bc || ((render->memory[0x80fc]&0x10) &&
        (phase==0 || phase==3 || phase==5)))
        return fx_display_special_real_result(render,source,box);
    return fx_display_complex_result(render,source,box);
}

size_t mode137_abi(unsigned field)
{
    switch(field) {
    case 0:return sizeof(fx_number);
    case 1:return sizeof(fx_render);
    case 2:return offsetof(fx_render,memory);
    case 3:return sizeof(fx_format_result);
    case 4:return offsetof(fx_format_result,kind);
    default:return sizeof(fx_box);
    }
}
