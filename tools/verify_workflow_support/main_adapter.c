/* Private high-levelC ABI adapter; no original instruction engine. */
#include "ui/fx_verify_controller.h"
#include "platform/fx_platform.h"
#include "parse/fx_verify_chain.h"
#include "numeric/fx_verify_relation.h"
#include <stddef.h>
#include <string.h>

static fx_platform platform;
static fx_verify_controller state;
static unsigned polls,cancel_at;
static int current_status;
static int cancelled(void *unused)
{(void)unused;++polls;return cancel_at && polls==cancel_at;}

int verify_main_bind(uint8_t *ram,const uint8_t *rom,size_t size)
{
    memset(&platform,0,sizeof platform);memset(&state,0,sizeof state);
    platform.ram=ram;platform.rom=rom;platform.rom_size=size;
    return fx_copy_startup_data(&platform);
}
int verify_main_begin(unsigned cancellation)
{
    fx_calculus_control control={cancelled,NULL};
    polls=0;cancel_at=cancellation;
    current_status=fx_verify_controller_begin(&platform,&state,0,&control);
    return current_status;
}
int verify_main_tick(void)
{
    current_status=fx_verify_controller_tick(&platform,&state);
    return current_status;
}
int verify_main_finish(uint8_t *returned)
{return fx_verify_controller_finish(&state,returned);}
unsigned verify_main_polls(void){return polls;}
unsigned verify_main_action(void){return state.screen.handler_action;}
unsigned verify_main_export(void){return fx_verify_controller_export_mask(&state);}
unsigned verify_main_native_error(void){return state.screen.input.evaluator_status;}
unsigned verify_main_callback_pending(void){return platform.callback_pending;}
size_t verify_main_state_size(void){return sizeof(fx_verify_controller);}

size_t verify_main_abi(unsigned index)
{
    const size_t fields[]={
        sizeof(fx_number),offsetof(fx_number,bytes),
        sizeof(fx_eval_storage),offsetof(fx_eval_storage,ram),
        offsetof(fx_eval_storage,ram_size),offsetof(fx_eval_storage,rom),
        offsetof(fx_eval_storage,rom_size),
        sizeof(fx_verify_chain_result),offsetof(fx_verify_chain_result,source),
        offsetof(fx_verify_chain_result,operands),offsetof(fx_verify_chain_result,relations),
        offsetof(fx_verify_chain_result,cancellation_checks),offsetof(fx_verify_chain_result,truth),
        offsetof(fx_verify_chain_result,unsupported_token),offsetof(fx_verify_chain_result,native_status),
        sizeof(fx_calculus_control),offsetof(fx_calculus_control,cancelled),
        offsetof(fx_calculus_control,userdata)
    };
    return index<sizeof fields/sizeof fields[0]?fields[index]:(size_t)-1;
}
