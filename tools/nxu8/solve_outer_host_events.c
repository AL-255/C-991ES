/* GPL-3.0-or-later. Passive original-ROM outer transaction observer. */
#include "harness.c"
unsigned outer_floor=0x8dee, outer_polls, outer_cancel_at;
uint8_t outer_poll_X[256][20];
void outer_reset_floor(void) { outer_floor=0x8dee;outer_polls=outer_cancel_at=0;memset(outer_poll_X,0,sizeof outer_poll_X); }
int outer_step(void) {
    if(harness_get_sp()<outer_floor)outer_floor=harness_get_sp();
    if(harness_get_pc()==0x5564) {
        if(outer_polls<256) {memcpy(outer_poll_X[outer_polls],ram+0x8276,10);memcpy(outer_poll_X[outer_polls]+10,ram+0x8458,10);}
        ++outer_polls;ram[0x8e00]=outer_cancel_at && outer_polls>=outer_cancel_at;
    }
    return harness_run(1,0x2fffe,false);
}
