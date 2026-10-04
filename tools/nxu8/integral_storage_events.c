/* Passive original integral workspace observer. No CPU instruction replacement. */
#define memorySetData integral_original_memory_set
#include "harness.c"
#undef memorySetData
#define WRITE_LIMIT 100000
#define EVENT_LIMIT 8192
struct integral_write { uint32_t pc,anchor; uint16_t address; uint8_t size; uint64_t value; };
struct integral_event { uint32_t pc,caller; uint16_t cursor,sink; uint8_t workspace[0xc6],x[20]; };
struct integral_write integral_writes[WRITE_LIMIT];
struct integral_event integral_events[EVENT_LIMIT];
unsigned integral_write_count,integral_event_count,integral_callbacks,integral_polls,integral_floor;
unsigned integral_anchor,integral_abort,integral_mutation_call,integral_mutation_address;
uint8_t integral_mutation_value[10];
void memorySetData(SR_t segment, EA_t offset, size_t size, uint64_t value) {
    integral_original_memory_set(segment,offset,size,value);
    if(!segment && offset<0x867c && offset+size>0x850a) {
        unsigned index=integral_write_count++;
        if(index<WRITE_LIMIT)integral_writes[index]=(struct integral_write){last_address,integral_anchor,offset,(uint8_t)size,value};
    }
}
void integral_observer_reset(void) {
    integral_write_count=integral_event_count=integral_callbacks=integral_polls=integral_anchor=0;
    integral_floor=0x8dee;
}
static void event(uint32_t pc) {
    unsigned index=integral_event_count++;
    if(index<EVENT_LIMIT){struct integral_event *e=integral_events+index;e->pc=pc;e->caller=((uint32_t)LCSR<<16)|LR;e->cursor=GR.rs[14]|GR.rs[15]<<8;e->sink=GR.rs[8]|GR.rs[9]<<8;memcpy(e->workspace,ram+0x850a,sizeof(e->workspace));memcpy(e->x,ram+0x8276,10);memcpy(e->x+10,ram+0x8458,10);}
}
int integral_observer_run(uint64_t limit,uint32_t stop) {
    for(uint64_t n=0;n<limit;++n){uint32_t pc=harness_get_pc();if(pc==stop)return 100;
        if(SP<integral_floor)integral_floor=SP;
        if(pc>=0x4490 && pc<0x4a62)integral_anchor=pc;
        if(pc==0x171ea && GR.rs[6]==1 && !LCSR && (LR==0x47aa||LR==0x47c4||LR==0x47ea||LR==0x4804||LR==0x4504||LR==0x45b4)){
            ++integral_callbacks;
            if(integral_mutation_call==integral_callbacks && integral_mutation_address>=0x8000 && integral_mutation_address<=0xfff6)memcpy(ram+integral_mutation_address,integral_mutation_value,10);
            event(pc);
        }
        if(pc==0x1cde4 && ((uint32_t)LCSR<<16|LR)==0x17254)event(pc);
        if(pc==0x5564){++integral_polls;ram[0x8e00]=(integral_abort==integral_polls)?1:0;event(pc);}
        int status=harness_run(1,0x2fffe,false);if(status!=103)return status;
    }return 103;
}
/* Preparation may return early through04A5C. Preserve that boundary instead
 * of running into the enclosing parser's output normalization. */
int integral_stage_run(uint64_t limit,uint32_t stop) {
    for(uint64_t n=0;n<limit;++n) {
        uint32_t pc=harness_get_pc();
        if(pc==stop || pc==0x4a5c)return 100;
        int status=integral_observer_run(1,stop);
        if(status!=103)return status;
    }
    return 103;
}
