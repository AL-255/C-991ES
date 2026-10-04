/* Passive full F12A address/workspace observer; original instructions execute. */
#define harness_run harness_original_run
#define input_controller_run input_controller_original_run
#define input_controller_observations_reset input_controller_original_reset
#include "input_controller_events.c"
#undef harness_run
#undef input_controller_run
#undef input_controller_observations_reset
unsigned input_physical_floor,input_physical_entry_count;
uint16_t input_physical_cursor_word,input_physical_source,input_physical_output,input_physical_returned_source;
uint8_t input_physical_poll_workspace[8192][0xc6];
void input_controller_observations_reset(void) {
 input_controller_original_reset();input_physical_floor=0x8dee;input_physical_entry_count=0;
 input_physical_cursor_word=input_physical_source=input_physical_output=input_physical_returned_source=0;
 memset(input_physical_poll_workspace,0,sizeof input_physical_poll_workspace);
}
int input_controller_run(uint64_t limit,uint32_t stop,unsigned abort_poll) {
 for(uint64_t n=0;n<limit;++n) {
  uint32_t pc=harness_get_pc();if(pc==stop)return 100;
  if(SP<input_physical_floor)input_physical_floor=SP;
  if(pc==0x171f4) {
   ++input_physical_entry_count;
   input_physical_cursor_word=GR.rs[0]|GR.rs[1]<<8;
   input_physical_source=ram[input_physical_cursor_word]|ram[input_physical_cursor_word+1]<<8;
   input_physical_output=GR.rs[2]|GR.rs[3]<<8;
  }
  if(pc==0x1f36a)input_physical_returned_source=ram[input_physical_cursor_word]|ram[input_physical_cursor_word+1]<<8;
  if(pc==0x5564 && input_controller_polls<8192)
   memcpy(input_physical_poll_workspace[input_controller_polls],ram+0x850a,0xc6);
  int status=input_controller_original_run(1,stop,abort_poll);if(status!=103)return status;
 }
 return 103;
}

int harness_run(uint64_t limit,uint32_t stop,bool stop_callback) {
 for(uint64_t n=0;n<limit;++n) {
  if(SP<input_physical_floor)input_physical_floor=SP;
  int status=harness_original_run(1,stop,stop_callback);if(status!=103)return status;
 }
 return 103;
}
