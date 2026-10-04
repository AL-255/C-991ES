/* Passive original-ROM observer for fresh persistent-device controls. No instructions or registers altered. */
#include "nxu8/harness.c"
unsigned runtime_floor=0x8dee;
uint8_t runtime_frame_writes[65536];
void runtime_observer_reset(void)
{ runtime_floor=0x8dee; memset(runtime_frame_writes,0,sizeof runtime_frame_writes); }
int runtime_run_to(uint32_t stop,uint64_t budget)
{
    for (uint64_t i=0;i<budget;++i) {
        unsigned sp=harness_get_sp();
        if (sp<runtime_floor) runtime_floor=sp;
        uint32_t target=stop;
        if (stop==0x53ce && (ram[0xf020]!=0x70 || ram[0xf021]!=7)) target=0x2fffe;
        int status=harness_run(1,target,false);
        if (status!=103) {
            for (unsigned a=runtime_floor;a<0x8dee;++a)
                runtime_frame_writes[a]=(uint8_t)(ram_write_counts[a]!=0);
            return status;
        }
    }
    for (unsigned a=runtime_floor;a<0x8dee;++a)
        runtime_frame_writes[a]=(uint8_t)(ram_write_counts[a]!=0);
    return 103;
}
