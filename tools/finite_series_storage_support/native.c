#define memorySetData original_memory_set
#include "../nxu8/harness.c"
#undef memorySetData
struct series_write {uint32_t pc;uint16_t address,sp;uint8_t size;uint64_t value;};
struct series_write series_writes[65536];
unsigned series_write_count,series_polls,series_abort;
uint64_t series_steps;
void memorySetData(SR_t segment,EA_t offset,size_t size,uint64_t value){
 original_memory_set(segment,offset,size,value);
 if(!segment&&offset>=0x80dc){unsigned i=series_write_count++;if(i<65536)series_writes[i]=(struct series_write){last_address,offset,SP,(uint8_t)size,value};}
}
void series_reset(void){series_write_count=series_polls=0;series_steps=0;}
uint32_t series_lr(void){return ((uint32_t)LCSR<<16)|LR;}
int series_run_to(uint64_t limit,uint32_t stop){
 for(uint64_t i=0;i<limit;++i){uint32_t pc=harness_get_pc();if(pc==stop||pc==0x2fffe)return 100;
 if(pc==0x5564){++series_polls;if(!series_abort||series_polls!=series_abort)ram[0x8e00]=0;}
 ++series_steps;int s=harness_run(1,0x2fffe,false);if(s!=103)return s;
 }return 103;
}
