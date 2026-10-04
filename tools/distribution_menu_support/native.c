/* GPL-3.0-only. Passive original data bus/frame and1DF7E write observation. */
#define memorySetData distribution_original_memorySetData
#include "../nxu8/harness.c"
#undef memorySetData
uint8_t parameter_menu_frame_mask[65536];
static uint16_t distribution_initial_sp;
unsigned distribution_native_order_count,distribution_native_order_enabled;
uint16_t distribution_native_order_address[64];
uint8_t distribution_native_order_value[64];
void memorySetData(SR_t segment,EA_t offset,size_t size,uint64_t value)
{
    if(!segment)for(size_t i=0;i<size;++i) {
        uint16_t address=(uint16_t)(offset+i);
        if(address>=SP && address<distribution_initial_sp)
            parameter_menu_frame_mask[address]=1;
        if(distribution_native_order_enabled &&
            !(address>=SP && address<distribution_initial_sp) && distribution_native_order_count<64) {
            unsigned n=distribution_native_order_count++;
            distribution_native_order_address[n]=address;
            distribution_native_order_value[n]=(uint8_t)(value>>(8*i));
        }
    }
    distribution_original_memorySetData(segment,offset,size,value);
}
void parameter_menu_observer_clear(void)
{
    distribution_initial_sp=harness_get_sp();
    memset(parameter_menu_frame_mask,0,sizeof parameter_menu_frame_mask);
    distribution_native_order_count=distribution_native_order_enabled=0;
}
void distribution_original_order_begin(void)
{ distribution_native_order_count=0;distribution_native_order_enabled=1; }
int parameter_menu_observe(uint64_t budget,int unused_dispatch,int delegates)
{
    (void)unused_dispatch;
    for(uint64_t i=0;i<budget;++i) {
        uint32_t pc=harness_get_pc();
        if(pc==0xd9d6)return 250;
        if(pc==0x1824e)return 203;
        if(pc==0x1d8a4)return 200;
        if(pc==0x53ce && LCSR==0 && (LR==0xe0d2 || LR==0xe126))return 202;
        if(delegates && (pc==0xceb0 || pc==0xcfa8 || pc==0xd312))return 300;
        int result=harness_run(1,0x2fffe,false);
        if(result!=103)return result;
    }
    return 103;
}
int distribution_original_to(uint32_t stop,uint64_t budget)
{
    for(uint64_t i=0;i<budget;++i) {
        if(harness_get_pc()==stop)return 100;
        int result=harness_run(1,0x2fffe,false);
        if(result!=103)return result;
    }
    return 103;
}
