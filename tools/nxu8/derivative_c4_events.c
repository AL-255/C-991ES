/* Original derivative event observer. Instructions remain unchanged; the
 * specified cancellation/mode response is an input, never an expected value. */
#define memorySetData original_memory_set
#include "harness.c"
#undef memorySetData
struct event {uint32_t pc,caller;uint16_t sink,cursor;uint8_t workspace[0x180],x[20];};
struct event c4_events[8192];
unsigned c4_event_count,c4_polls,c4_callbacks,c4_abort,c4_floor;
uint8_t c4_results[8192][20],c4_statuses[8192],c4_delimiters[8192],c4_flags[8192];
unsigned c4_pending,c4_return,c4_mode_call,c4_mode_value;
void memorySetData(SR_t s,EA_t a,size_t n,uint64_t v){original_memory_set(s,a,n,v);}
void c4_reset(void){c4_event_count=c4_polls=c4_callbacks=0;c4_floor=0x8dee;c4_pending=8192;c4_return=0;}
int c4_stage(uint64_t limit,uint32_t end){
 for(uint64_t i=0;i<limit;++i){
  uint32_t pc=harness_get_pc();
  if(c4_pending<8192&&pc==c4_return){memcpy(c4_results[c4_pending],ram+GR.ers[6],20);c4_statuses[c4_pending]=GR.rs[0];c4_delimiters[c4_pending]=GR.rs[2];c4_flags[c4_pending]=PSW.raw;c4_pending=8192;}
  if(pc==end)return 100;
  if(SP<c4_floor)c4_floor=SP;
  if(pc==0x5564||(pc==0x171ea&&GR.rs[6]==1&&!LCSR&&LR>=0x4a62&&LR<0x4f26)){
   if(c4_event_count<8192){struct event *e=c4_events+c4_event_count++;
    e->pc=pc;e->caller=LR;e->sink=GR.ers[4];e->cursor=GR.ers[7];
    memcpy(e->workspace,ram+0x8500,0x180);memcpy(e->x,ram+0x8276,10);memcpy(e->x+10,ram+0x8458,10);}
   if(pc==0x5564){++c4_polls;ram[0x8e00]=c4_abort&&c4_polls==c4_abort;}
   else {++c4_callbacks;c4_pending=c4_event_count-1;c4_return=LR;if(c4_callbacks==c4_mode_call)ram[0x80f9]=c4_mode_value;}
  }
  int status=harness_run(1,0x2fffe,false);if(status!=103)return status;
 }
 return 103;
}
