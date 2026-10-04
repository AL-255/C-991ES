/* Native-only D9EE oracle events and actual CPU stack extent. */
#include "input_controller_events.c"
uint16_t ui_controller_min_sp;
void ui_controller_observations_reset(void)
{
    input_controller_observations_reset();
    ui_controller_min_sp=0x8dee;
}
int ui_controller_run(uint64_t limit,uint32_t stop,unsigned abort_poll)
{
    for (uint64_t n=0;n<limit;++n) {
        uint16_t stack=harness_get_sp();
        if (stack<ui_controller_min_sp) ui_controller_min_sp=stack;
        int status=input_controller_run(1,stop,abort_poll);
        if (status!=103) return status;
    }
    return 103;
}
