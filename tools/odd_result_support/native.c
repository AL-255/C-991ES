/* SPDX-License-Identifier: GPL-3.0-only; test-only original execution. */
#include "harness.c"
uint8_t odd_result_frames[65536];
unsigned odd_result_floor;
int odd_result_native_call(uint32_t entry,uint16_t address)
{
    const uint32_t sentinel=0x2fffe;
    uint16_t argument=entry==0x1f12a?0x9d00:0x9900;
    harness_set_reg(0,(uint8_t)argument);harness_set_reg(1,(uint8_t)(argument>>8));
    if(entry==0x1f12a) {
        harness_set_reg(8,(uint8_t)argument);harness_set_reg(9,(uint8_t)(argument>>8));
    } else {
        harness_set_reg(2,(uint8_t)address);harness_set_reg(3,(uint8_t)(address>>8));
    }
    odd_result_floor=0x8dee;memset(odd_result_frames,0,sizeof odd_result_frames);
    harness_set_sp(0x8dee);harness_set_lr(sentinel);harness_set_pc(entry);
    int outcome=103;
    for(unsigned i=0;i<10000000;i++) {
        unsigned sp=harness_get_sp();if(sp<odd_result_floor)odd_result_floor=sp;
        if(harness_get_pc()==sentinel){outcome=100;break;}
        outcome=harness_run(1,sentinel,false);if(outcome!=103)break;
    }
    for(unsigned a=odd_result_floor;a<0x8dee;a++)
        odd_result_frames[a]=(uint8_t)(ram_write_counts[a]!=0);
    return outcome;
}
