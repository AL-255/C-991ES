/* Passive original-ROM polynomial workflow observer. GPL-3.0-only. */
#include <stddef.h>
#include "equation_support/workflow_native.c"
typedef struct {
    uint32_t pc;
    uint64_t ordinal;
    uint8_t r0,selector,screen,submode,page,row,column;
} polynomial_point;
polynomial_point polynomial_points[128];
uint8_t polynomial_point_ram[128][65536];
unsigned polynomial_point_count;
uint64_t polynomial_instructions;
void polynomial_reset(void)
{
    lifecycle_reset();polynomial_point_count=0;polynomial_instructions=0;
}
static int watched(uint32_t pc)
{
    switch(pc) {
    case 0xe7b2:case 0xe7b6:case 0xe7bc:case 0xe884:case 0xe8c0:
    case 0xe8d8:case 0xe8e6:case 0x14f0c:case 0x15032:case 0x1503c:
    case 0x15658:case 0x13798:case 0x1387a:case 0x1e47e:return 1;
    default:return 0;
    }
}
int polynomial_run(uint64_t budget,uint32_t stop,unsigned cancel_at)
{
    for(uint64_t i=0;i<budget;++i) {
        uint32_t pc=harness_get_pc();
        unsigned sp=harness_get_sp();if(sp<lifecycle_floor)lifecycle_floor=sp;
        if(pc==stop){frames();return 100;}
        if(watched(pc)) {
            if(polynomial_point_count>=128){frames();return -41;}
            unsigned n=polynomial_point_count++;
            polynomial_points[n]=(polynomial_point){pc,polynomial_instructions,
                harness_get_reg(0),ram[0x80fa],ram[0x80fc],ram[0x80fd],
                ram[0x811c],ram[0x811d],ram[0x811e]};
            memcpy(polynomial_point_ram[n],ram,65536);
        }
        if(pc==0x5564) {
            if(lifecycle_polls>=256){frames();return -40;}
            memcpy(lifecycle_poll_ram[lifecycle_polls],ram,65536);
            ++lifecycle_polls;
            /* Physical timer response only; the original5550 body executes. */
            ram[0x8e00]=(uint8_t)(cancel_at && lifecycle_polls==cancel_at?2:0);
        }
        ++polynomial_instructions;
        int status=harness_run(1,stop,false);
        if(status!=103){frames();return status;}
    }
    frames();return 103;
}
size_t polynomial_point_size(void){return sizeof(polynomial_point);}
unsigned polynomial_point_offset(unsigned field)
{
    static const size_t offsets[]={offsetof(polynomial_point,pc),
        offsetof(polynomial_point,ordinal),offsetof(polynomial_point,r0),
        offsetof(polynomial_point,selector),offsetof(polynomial_point,screen),
        offsetof(polynomial_point,submode),offsetof(polynomial_point,page),
        offsetof(polynomial_point,row),offsetof(polynomial_point,column)};
    return field<sizeof offsets/sizeof offsets[0]?(unsigned)offsets[field]:~0u;
}
