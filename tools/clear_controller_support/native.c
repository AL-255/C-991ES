/* GPL-3.0-only. Passive original instruction/store observer. */
#include "parameter_menu_oracle.c"
int clear_run_to(uint32_t stop,uint64_t budget)
{
    for(uint64_t i=0;i<budget;++i) {
        if(harness_get_pc()==stop)return 100;
        int result=harness_run(1,0x2fffe,false);
        ++parameter_menu_steps;
        if(result!=103)return result;
    }
    return 103;
}
