/* Passive original-ROM store/checkpoint observer. Production never links it. */
#define memorySetData observed_memorySetData
#include "harness.c"
#undef memorySetData

typedef struct { uint32_t pc, link; uint16_t address, sp; uint8_t size; uint64_t value; } store_event;
typedef struct { uint32_t pc; uint16_t link, output; uint8_t kind, x[10], workspace[0x180]; } checkpoint;
store_event derivative_stores[30000];
checkpoint derivative_checkpoints[512];
unsigned derivative_store_count, derivative_checkpoint_count, derivative_polls, derivative_floor;
unsigned derivative_callback_count, derivative_mutation_kind, derivative_mutation_call;
unsigned derivative_mutation_address;
uint8_t derivative_mutation_value[10];

void memorySetData(SR_t segment, EA_t offset, size_t size, uint64_t value) {
    if (!segment && offset < 0x8680 && offset+size > 0x8500) {
        if (derivative_store_count < 30000) {
            store_event *event=&derivative_stores[derivative_store_count];
            event->pc=last_address;event->link=((uint32_t)LCSR<<16)|LR;
            event->address=offset;event->sp=SP;
            event->size=(uint8_t)size;event->value=value;
        }
        ++derivative_store_count;
    }
    observed_memorySetData(segment,offset,size,value);
}

int derivative_storage_observe(unsigned abort_poll, uint64_t limit) {
    derivative_store_count=derivative_checkpoint_count=derivative_polls=derivative_callback_count=0;
    derivative_floor=0x8dee;
    for (uint64_t i=0;i<limit;++i) {
        uint32_t pc=harness_get_pc();
        unsigned kind=0;
        if (SP<derivative_floor)derivative_floor=SP;
        if (pc==0x171ea && GR.rs[6]==1 && !LCSR && LR>=0x4a62 && LR<0x4f26) {
            kind=1;++derivative_callback_count;
        }
        if (pc==0x5564) {
            kind=2;++derivative_polls;
            ram[0x8e00]=(abort_poll && derivative_polls==abort_poll)?1:0;
        }
        if (kind) {
            if (derivative_checkpoint_count<512) {
                checkpoint *event=&derivative_checkpoints[derivative_checkpoint_count];
                event->pc=pc;event->link=LR;event->output=GR.ers[6];event->kind=(uint8_t)kind;
                memcpy(event->x,ram+0x8276,10);memcpy(event->workspace,ram+0x8500,0x180);
            }
            ++derivative_checkpoint_count;
            unsigned call=kind==1?derivative_callback_count:derivative_polls;
            if (kind==derivative_mutation_kind && call==derivative_mutation_call &&
                derivative_mutation_address>=0x8000 && derivative_mutation_address<=0xfff6)
                memcpy(ram+derivative_mutation_address,derivative_mutation_value,10);
        }
        int status=harness_run(1,0x2fffe,false);
        if (status!=103)return status;
    }
    return 103;
}
