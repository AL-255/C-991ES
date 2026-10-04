#include "native.c"
struct series_sample {uint32_t caller;uint16_t cursor,sink,working;uint8_t mode,r6,status,delimiter,psw;uint8_t x[20],value[20];};
struct series_stage {uint32_t pc;uint16_t base,working,cursor;uint8_t status,condition,mode,psw;uint8_t records[40],value[20],x[20];};
struct series_sample series_samples[256];struct series_stage series_stages[2048];
unsigned series_sample_count,series_stage_count,series_pending;uint16_t series_base;
void series_observer_reset(void){series_reset();series_sample_count=series_stage_count=0;series_pending=256;series_base=0;}
static unsigned is_callback(uint32_t lr){return lr==0x43ba||lr==0x43c4||lr==0x43d4||lr==0x4442||lr==0x42c6||lr==0x42d0||lr==0x42e0||lr==0x434e;}
static unsigned stage_pc(uint32_t pc){switch(pc){case 0x43d0:case 0x42dc:case 0x4412:case 0x431e:case 0x4416:case 0x4322:case 0x4420:case 0x432c:case 0x4430:case 0x433c:case 0x4442:case 0x434e:case 0x444c:case 0x4358:case 0x4452:case 0x435e:case 0x4464:case 0x4370:case 0x4472:case 0x437e:case 0x447c:case 0x438e:case 0x447e:case 0x4390:case 0x448e:case 0x43a0:case 0x5564:return 1;default:return 0;}}
int series_observe_to(uint64_t limit,uint32_t stop){
 for(uint64_t i=0;i<limit;++i){uint32_t pc=harness_get_pc();if(pc==stop||pc==0x2fffe)return 100;
 if(pc==0x43b2||pc==0x42be)series_base=GR.rs[8]|GR.rs[9]<<8;
 if(series_pending<256&&pc==series_samples[series_pending].caller){struct series_sample *e=series_samples+series_pending;e->working=GR.rs[12]|GR.rs[13]<<8;memcpy(e->value,ram+e->working,20);e->status=GR.rs[0];e->delimiter=GR.rs[2];e->psw=PSW.raw;series_pending=256;}
 if(pc==0x171ea&&is_callback(series_lr())){unsigned i=series_sample_count++;if(i<256){struct series_sample *e=series_samples+i;memset(e,0,sizeof*e);e->caller=series_lr();e->cursor=GR.rs[14]|GR.rs[15]<<8;e->sink=GR.rs[8]|GR.rs[9]<<8;e->mode=ram[0x80f9];e->r6=GR.rs[6];memcpy(e->x,ram+0x8276,10);memcpy(e->x+10,ram+0x8458,10);series_pending=i;}}
 if(series_base&&stage_pc(pc)){unsigned i=series_stage_count++;if(i<2048){struct series_stage *e=series_stages+i;e->pc=pc;e->base=series_base;e->working=GR.rs[12]|GR.rs[13]<<8;e->cursor=GR.rs[14]|GR.rs[15]<<8;e->status=GR.rs[0];e->condition=GR.rs[2];e->mode=ram[0x80f9];e->psw=PSW.raw;memcpy(e->records,ram+series_base,40);memcpy(e->value,ram+e->working,20);memcpy(e->x,ram+0x8276,10);memcpy(e->x+10,ram+0x8458,10);}}
 if(pc==0x5564){++series_polls;if(!series_abort||series_polls!=series_abort)ram[0x8e00]=0;}
 ++series_steps;int s=harness_run(1,0x2fffe,false);if(s!=103)return s;
 }return 103;
}
