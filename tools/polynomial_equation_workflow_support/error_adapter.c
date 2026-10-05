/* Authored key input is delivered after the actual key timer publication. */
#define __wrap_fx_timer_start polynomial_base_timer_start
#include "adapter.c"
#undef __wrap_fx_timer_start
static uint8_t polynomial_key_columns,polynomial_key_rows;
static unsigned polynomial_key_queued;
void polynomial_c_queue_key(uint8_t columns,uint8_t rows)
{polynomial_key_columns=columns;polynomial_key_rows=rows;polynomial_key_queued=1;}
void __wrap_fx_timer_start(fx_platform *p,uint16_t period)
{
    polynomial_base_timer_start(p,period);
    if(period==0x129a && polynomial_key_queued) {
        p->ram[0x8e01]=polynomial_key_columns;p->ram[0x8e02]=polynomial_key_rows;
        polynomial_key_queued=0;
    }
}
