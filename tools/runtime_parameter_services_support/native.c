/* GPL-3.0-only. Reuse independently proved passive memory-write observation. */
#define parameter_menu_observe parameter_menu_original_observe
#include "parameter_menu_oracle.c"
#undef parameter_menu_observe
int parameter_menu_observe(uint64_t budget,int dispatch_only,int delegates)
{
    for(uint64_t i=0;i<budget;++i) {
        if(harness_get_pc()==0x53ce && LCSR==0 && LR==0xd372)return 202;
        int status=parameter_menu_original_observe(1,dispatch_only,delegates);
        if(status!=103)return status;
    }
    return 103;
}
int runtime_parameter_run_to(uint32_t stop,uint64_t budget)
{
    for(uint64_t i=0;i<budget;++i) {
        if(harness_get_pc()==stop)return 100;
        int status=harness_run(1,0x2fffe,false);
        ++parameter_menu_steps;
        if(status!=103)return status;
    }
    return 103;
}
