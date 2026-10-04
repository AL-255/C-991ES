
#include "harness.c"
#define EVENTS 128
unsigned event_count,minimum_sp,polls,cancel_at;
uint32_t event_pc[EVENTS];
uint16_t event_sp[EVENTS];
uint8_t event_regs[EVENTS][16],event_ram[EVENTS][65536];
static int checkpoint(uint32_t pc) {
 switch(pc) {
 case 0x1f1ea: case 0x1f200: case 0x1f22e: case 0x1f256:
 case 0x1f2fe: case 0x1f32c: case 0x1f5ae: case 0xde7e: case 0xd9ee: case 0xe1d6: case 0xe3d4: case 0xe402: case 0xe438: case 0xe440: case 0xe3d2: case 0xe432: case 0xe43c: case 0xe376: case 0x1f26e: case 0x1f2ac: case 0x1f2f6: case 0x1f304:
 case 0x1f314: case 0x1f324: case 0x1f338: case 0x1f36c:
 case 0x1f39a: case 0x1f3c8: case 0x1f3d6: case 0x1f592:
 case 0x1f598: case 0x1f5a6: case 0x1d8a4: case 0x1ec72:
 case 0x5550: case 0x5578: case 0x4f26: case 0x4fe6: case 0x171f4: case 0x171ea:
 case 0xe1f6: case 0xe210: case 0xe21a: case 0xe23a:
 case 0xe266: case 0xe2b4: case 0xe34e: case 0xe444:
 case 0xe680: case 0xe6ec: case 0xe7e0: case 0xe820:
 return 1; default:return 0;
 }
}
void observer_reset(unsigned cancel) { event_count=0;minimum_sp=SP;polls=0;cancel_at=cancel; }
int observer_run(uint64_t limit,uint32_t stop) {
 for(uint64_t i=0;i<limit;i++) {
  uint32_t pc=harness_get_pc();if(SP<minimum_sp)minimum_sp=SP;
  if(checkpoint(pc) || pc==stop) {
   if(event_count>=EVENTS)return 104;
   unsigned j=event_count++;event_pc[j]=pc;event_sp[j]=SP;
   memcpy(event_regs[j],GR.rs,16);memcpy(event_ram[j],ram,65536);
  }
  if(pc==stop)return 100;
  if(pc==0x1d8a4)return 105;
  if(pc==0x5564) { ++polls;ram[0x8e00]=cancel_at&&polls==cancel_at?2:0; }
  int status=harness_run(1,stop,false);if(status!=103)return status;
 }
 return 103;
}
