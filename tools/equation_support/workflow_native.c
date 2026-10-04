/* Passive unchanged-ROM explorer. Host only answers the real5564 timer seam. */
#include "nxu8/harness.c"
unsigned lifecycle_floor=0x8dee,lifecycle_polls;
uint8_t lifecycle_frames[65536];
uint8_t lifecycle_poll_ram[256][65536];
void lifecycle_reset(void)
{ lifecycle_floor=0x8dee;lifecycle_polls=0;memset(lifecycle_frames,0,sizeof lifecycle_frames);memset(ram_write_counts,0,sizeof ram_write_counts); }
static void frames(void)
{
    for (unsigned a=lifecycle_floor;a<0x8dee;++a)
        lifecycle_frames[a]=(uint8_t)(ram_write_counts[a]!=0);
}
int lifecycle_run(uint64_t budget,uint32_t stop,unsigned cancel_at)
{
    for (uint64_t i=0;i<budget;++i) {
        uint32_t pc=harness_get_pc();
        unsigned sp=harness_get_sp();if(sp<lifecycle_floor)lifecycle_floor=sp;
        if (pc==stop) {frames();return 100;}
        if (pc==0x5564) {
            if (lifecycle_polls>=256) {frames();return -40;}
            memcpy(lifecycle_poll_ram[lifecycle_polls],ram,65536);++lifecycle_polls;
            ram[0x8e00]=(uint8_t)(cancel_at && lifecycle_polls==cancel_at ? 2 : 0);
        }
        int status=harness_run(1,stop,false);
        if (status!=103) {frames();return status;}
    }
    frames();return 103;
}
