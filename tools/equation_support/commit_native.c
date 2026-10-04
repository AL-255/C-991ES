/* SPDX-License-Identifier: GPL-3.0-only */
/* Original-only verification adapter. No original body enters production C. */
#include "harness.c"
uint8_t equation_commit_frames[65536];
unsigned equation_commit_floor;
void equation_commit_native_init(const void *rom, size_t length)
{ harness_init(rom,length); }
uint8_t *equation_commit_native_ram(void) { return ram; }
unsigned equation_commit_native_return(void) { return harness_get_reg(0); }
int equation_commit_native_call(uint16_t source)
{
    const uint32_t sentinel=0x2fffe;
    equation_commit_floor=0x8dee;
    memset(equation_commit_frames,0,sizeof equation_commit_frames);
    harness_set_reg(0,(uint8_t)source);
    harness_set_reg(1,(uint8_t)(source>>8));
    harness_set_sp(0x8dee);harness_set_lr(sentinel);harness_set_pc(0xe680);
    int outcome=103;
    for(unsigned i=0;i<1000000;i++) {
        unsigned sp=harness_get_sp();
        if(sp<equation_commit_floor)equation_commit_floor=sp;
        if(harness_get_pc()==sentinel){outcome=100;break;}
        outcome=harness_run(1,sentinel,false);
        if(outcome!=103)break;
    }
    for(unsigned a=equation_commit_floor;a<0x8dee;a++)
        equation_commit_frames[a]=(uint8_t)(ram_write_counts[a]!=0);
    return outcome;
}
