/* Test-only named host state/control adapter. No oracle-output substitution. */
#include "ui/fx_solve_outer.h"
#include <stdlib.h>
#include <string.h>
typedef struct {fx_solve_outer state;unsigned cancel_at,polls;fx_platform *platform;uint8_t poll_X[256][20];} test_state;
static int cancelled(void *userdata) {
    test_state *s=userdata;
    if(s->platform && s->polls<256) {
        memcpy(s->poll_X[s->polls],s->platform->ram+0x8276,10);
        memcpy(s->poll_X[s->polls]+10,s->platform->ram+0x8458,10);
    }
    ++s->polls;return s->cancel_at && s->polls>=s->cancel_at;
}
void *outer_test_new(void) { return calloc(1,sizeof(test_state)); }
void outer_test_free(void *state) { free(state); }
void outer_test_begin(void *state) { fx_solve_outer_begin(state,NULL,NULL,NULL); }
void outer_test_cancel_at(void *state,unsigned at) {
    test_state *s=state;s->cancel_at=at;s->polls=0;
    s->state.cancellation.cancelled=cancelled;s->state.cancellation.userdata=s;
}
unsigned outer_test_polls(void *state) {return ((test_state *)state)->polls;}
void outer_test_poll_X(void *state,unsigned index,uint8_t *output) {
    test_state *s=state;if(index<256)memcpy(output,s->poll_X[index],20);
}
int outer_test_dispatch(fx_platform *p,void *state,unsigned request,unsigned refresh) {
    ((test_state *)state)->platform=p;
    return fx_solve_outer_dispatch(p,state,(fx_main_request)request,(uint8_t)refresh);
}
unsigned outer_test_action(void *state) { return ((fx_solve_outer *)state)->handler_action; }
unsigned outer_test_return(void *state) { return ((fx_solve_outer *)state)->context_return; }
unsigned outer_test_pending(void *state) { return ((fx_solve_outer *)state)->pending_owner; }
int outer_test_load(fx_platform *p,unsigned id,unsigned destination)
{ return fx_solve_outer_load_variable(p,(uint8_t)id,(uint16_t)destination); }
size_t outer_test_size(void) {return sizeof(fx_solve_outer);}
int outer_test_adopt(fx_platform *p,void *state) {return fx_solve_outer_adopt(p,state);}
int outer_test_restore(fx_platform *p,void *state) {return fx_solve_outer_restore(p,state);}
