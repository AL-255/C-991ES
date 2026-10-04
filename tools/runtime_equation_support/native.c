/* Passive original-ROM observer. No instructions or registers altered. */
#include "nxu8/harness.c"
unsigned runtime_floor=0x8dee;
uint8_t runtime_frame_writes[65536];
unsigned equation_native_polls;
unsigned equation_native_cancel_at;
uint8_t equation_poll_ram[256][65536];
void runtime_observer_reset(void)
{ runtime_floor=0x8dee; equation_native_polls=equation_native_cancel_at=0; memset(runtime_frame_writes,0,sizeof runtime_frame_writes); }
int runtime_run_to(uint32_t stop,uint64_t budget)
{
    for (uint64_t i=0;i<budget;++i) {
        if(harness_get_pc()==0x5564) {
            /* Actual external timer readiness at the original 5550 seam. */
            if(equation_native_polls<256)memcpy(equation_poll_ram[equation_native_polls],ram,65536);
            ++equation_native_polls;ram[0x8e00]=equation_native_polls==equation_native_cancel_at?2:0;
        }
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
