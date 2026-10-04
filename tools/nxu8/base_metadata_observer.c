/* Test-only observer of original scalar word serialization. */
#include "harness.c"
int base_metadata_stage_run(uint64_t limit) {
 for(uint64_t i=0;i<limit;++i) {
  uint32_t pc=harness_get_pc();if(pc==0x15a64)return 100;if(pc==0x2fffe)return 101;
  int status=harness_run(1,0x2fffe,false);if(status!=103)return status;
 }return 103;
}
static CoreRegister_t seen_core[260];static uint8_t seen_ram[260][65536];
unsigned base_metadata_cycle_first,base_metadata_cycle_repeat;
int base_metadata_cycle_run(uint64_t limit) {
 unsigned count=0;
 for(uint64_t i=0;i<limit;++i) {
  uint32_t pc=harness_get_pc();if(pc==0x2fffe)return 100;
  if(pc==0x15a70) {
   for(unsigned j=0;j<count;++j)
    if(!memcmp(&CoreRegister,&seen_core[j],sizeof CoreRegister)&&
       !memcmp(ram,seen_ram[j],sizeof ram)) {
     base_metadata_cycle_first=j;base_metadata_cycle_repeat=count;return 104;
    }
   if(count==260)return 105;
   memcpy(&seen_core[count],&CoreRegister,sizeof CoreRegister);
   memcpy(seen_ram[count],ram,sizeof ram);++count;
  }
  int status=harness_run(1,0x2fffe,false);if(status!=103)return status;
 }return 103;
}
