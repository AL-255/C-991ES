/* Passive polynomial error continuation observer; original instructions run. */
#define polynomial_run polynomial_base_run
#include "native.c"
#undef polynomial_run
static uint8_t polynomial_key_columns,polynomial_key_rows;
static unsigned polynomial_key_queued;
void polynomial_queue_key(uint8_t columns,uint8_t rows)
{polynomial_key_columns=columns;polynomial_key_rows=rows;polynomial_key_queued=1;}
int polynomial_run(uint64_t budget,uint32_t stop,unsigned cancel_at)
{
    for(uint64_t i=0;i<budget;++i) {
        uint32_t pc=harness_get_pc();
        unsigned sp=harness_get_sp();if(sp<lifecycle_floor)lifecycle_floor=sp;
        if(pc==stop && !(stop==0x53ce &&
            (ram[0xf020]!=0x70 || ram[0xf021]!=7))) {frames();return 100;}
        if(watched(pc)) {
            if(polynomial_point_count>=128){frames();return -41;}
            unsigned n=polynomial_point_count++;
            polynomial_points[n]=(polynomial_point){pc,polynomial_instructions,
                harness_get_reg(0),ram[0x80fa],ram[0x80fc],ram[0x80fd],
                ram[0x811c],ram[0x811d],ram[0x811e]};
            memcpy(polynomial_point_ram[n],ram,65536);
        }
        if(pc==0x5564 || pc==0x1d8b6) {
            if(lifecycle_polls>=256){frames();return -40;}
            memcpy(lifecycle_poll_ram[lifecycle_polls],ram,65536);
            ++lifecycle_polls;
            /* Only5550 requests the external cancellation response. The
             * key timer's actual538A call observes authored8E01/8E02. */
            if(pc==0x5564)
                ram[0x8e00]=(uint8_t)(cancel_at && lifecycle_polls==cancel_at?2:0);
            else if(polynomial_key_queued) {
                ram[0x8e01]=polynomial_key_columns;ram[0x8e02]=polynomial_key_rows;
                polynomial_key_queued=0;
            }
        }
        ++polynomial_instructions;
        int status=harness_run(1,stop,false);
        if(status==100 && stop==0x53ce &&
           (ram[0xf020]!=0x70 || ram[0xf021]!=7)) continue;
        if(status!=103){frames();return status;}
    }
    frames();return 103;
}
