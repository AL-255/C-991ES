/* GPL-3.0-only. Passive composed 71EC observer, no post-entry inputs. */
#define memorySetData screen_original_memory_set_data
#include "../diagnostic_rom_status_support/native.c"
#undef memorySetData
static uint8_t frame_mask[65536], flush_frames[3*384];
static uint32_t flush_events[3];
static unsigned flush_count;
static uint16_t initial_sp;
void memorySetData(SR_t segment, EA_t offset, size_t size, uint64_t value) {
    if (!segment) for (size_t n=0;n<size;++n) {
        uint16_t address=(uint16_t)(offset+n);
        if (address>=SP && address<initial_sp) frame_mask[address]=1;
    }
    screen_original_memory_set_data(segment,offset,size,value);
}
void screen_native_clear(void) {
    initial_sp=SP; flush_count=0;
    memset(frame_mask,0,sizeof frame_mask);
    memset(flush_frames,0,sizeof flush_frames);
    memset(flush_events,0,sizeof flush_events);
    diagnostic_native_seed(0);
}
int screen_native_run(uint64_t limit,uint32_t stop) {
    for(uint64_t n=0;n<limit;++n) {
        uint32_t address=harness_get_pc(); CORE_STATUS status;
        if(address==stop) return 100;
        if(address>=sizeof rom) return 101;
        if(address==0x3cfcu) {
            if(flush_count>=3) return 104;
            memcpy(flush_frames+384*flush_count,ram+0x87d0,384);
            flush_events[flush_count++]=(uint32_t)diagnostic_event_count;
        }
        last_address=address; ++execution_counts[address>>1];
        if(address==0x734au||address==0x7368u) diagnostic_event(3,0,0,PSW.raw);
        if(address==0x7374u) diagnostic_event(5,0,0,GR.rs[9]);
        status=coreStep();
        if(address==0x7348u||address==0x7366u) diagnostic_event(2,0,0,PSW.raw);
        if(address==0x7356u) diagnostic_event(4,0,0,GR.rs[9]);
        if(status!=CORE_OK) return status;
    }
    return 103;
}
const uint8_t *screen_native_mask(void) {return frame_mask;}
const uint8_t *screen_native_flush_frames(void) {return flush_frames;}
const uint32_t *screen_native_flush_events(void) {return flush_events;}
unsigned screen_native_flush_count(void) {return flush_count;}
