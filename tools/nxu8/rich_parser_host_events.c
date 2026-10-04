/* Passive original-ROM observer for prepared rich expression calls. */
#include "harness.c"
unsigned review_floor, review_polls;
uint8_t review_frame_writes[65536];
int review_run(void) {
    review_floor = 0x8dee;
    review_polls = 0;
    for (unsigned i = 0; i < 5000000; ++i) {
        unsigned sp = harness_get_sp();
        if (sp < review_floor) review_floor = sp;
        if (harness_get_pc() == 0x5564) {
            ++review_polls;
            ram[0x8e00] = 0;
        }
        int status = harness_run(1, 0x2fffe, false);
        if (status != 103) {
            memset(review_frame_writes, 0, sizeof review_frame_writes);
            for (unsigned address = review_floor; address < 0x8dee; ++address)
                review_frame_writes[address] = (uint8_t)(ram_write_counts[address] != 0);
            return status;
        }
    }
    memset(review_frame_writes, 0, sizeof review_frame_writes);
    for (unsigned address = review_floor; address < 0x8dee; ++address)
        review_frame_writes[address] = (uint8_t)(ram_write_counts[address] != 0);
    return 103;
}
