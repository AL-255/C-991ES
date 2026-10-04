/* GPL-3.0-only. Typed test accessors; all behavior belongs to production C. */
#include "../csrc/ui/fx_parameter_menu_controller.h"
#include "../csrc/platform/fx_main_loop.h"
#include <stddef.h>

size_t parameter_menu_c_state_size(void)
{ return sizeof(fx_parameter_menu_controller); }
uint32_t parameter_menu_c_target(const fx_parameter_menu_controller *s)
{ return (uint32_t)s->target_segment << 16 | s->target_offset; }
unsigned parameter_menu_c_request(const fx_parameter_menu_controller *s, unsigned n)
{
    if (n == 0) return (unsigned)s->request.kind;
    if (n == 1) return s->request.page;
    if (n == 2) return s->request.argument;
    return 0;
}
/* Actual public MAIN completion, supplied with the completed C child's byte.
 * This is not a native-result-fed replacement for a pending child body. */
int parameter_menu_c_main_complete(fx_platform *p, uint8_t returned,
                                  uint8_t *last, uint8_t *wait)
{
    fx_main_loop s;
    fx_main_loop_begin(&s);
    s.phase = FX_MAIN_HANDLER_PENDING;
    s.pending_request = FX_MAIN_PARAMETER_MENU;
    s.wait_required = 1;
    int status = fx_main_loop_accept_handler(p, &s, returned);
    if (last) *last = s.last_menu_result;
    if (wait) *wait = s.wait_required;
    return status;
}
