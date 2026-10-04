/* Native-only F12A oracle event adapter. GPL-3.0-or-later.
 * The original CPU executes every instruction. The host supplies only the
 *5550 timer/cancellation response and observes each sampled persistent X. */
#include "harness.c"
unsigned input_controller_polls;
uint8_t input_controller_poll_x[8192][10];
void input_controller_observations_reset(void)
{
    input_controller_polls=0;
    memset(input_controller_poll_x,0,sizeof input_controller_poll_x);
}
int input_controller_run(uint64_t limit, uint32_t stop, unsigned abort_poll)
{
    for (uint64_t n=0;n<limit;++n) {
        if (harness_get_pc()==stop) return 100;
        if (harness_get_pc()==0x5564) {
            if (input_controller_polls<8192)
                memcpy(input_controller_poll_x[input_controller_polls],ram+0x8276,10);
            ++input_controller_polls;
            if (!abort_poll || input_controller_polls!=abort_poll) ram[0x8e00]=0;
        }
        int status=harness_run(1,stop,false);
        if (status!=103) return status;
    }
    return 103;
}
