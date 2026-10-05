/* GPL-3.0-only. Reuse independently proved passive memory-write observation. */
#include "../parameter_menu_oracle.c"
int statistics_original_to(uint32_t stop,uint64_t budget)
{
    for(uint64_t i=0;i<budget;++i) {
        if(harness_get_pc()==stop)return 100;
        int status=harness_run(1,0x2fffe,false);
        ++parameter_menu_steps;
        if(status!=103)return status;
    }
    return 103;
}
