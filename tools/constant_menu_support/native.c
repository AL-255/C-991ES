/* SPDX-License-Identifier: GPL-3.0-only */
#include "parameter_menu_oracle.c"
int constant_original_observe(uint64_t budget)
{
    for(uint64_t i=0;i<budget;++i) {
        uint32_t pc=harness_get_pc();parameter_menu_boundary=pc;
        if(pc==0x2fffe)return 100;
        if(pc==0xd9d6)return 250;
        if(pc==0x1824e)return 203;
        if(pc==0x1d8a4)return 200;
        if(pc==0x53ce && LCSR==0 && LR==0xd372)return 202;
        int result=harness_run(1,0x2fffe,false);++parameter_menu_steps;
        if(result!=103)return result;
    }
    return 103;
}
int constant_original_to(uint32_t stop,uint64_t budget)
{
    for(uint64_t i=0;i<budget;++i) {
        if(harness_get_pc()==stop)return 100;
        int result=harness_run(1,0x2fffe,false);++parameter_menu_steps;
        if(result!=103)return result;
    }
    return 103;
}
