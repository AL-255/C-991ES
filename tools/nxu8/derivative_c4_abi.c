#include <stddef.h>
#include "numeric/fx_c4_derivative_storage.h"
size_t c4_derivative_abi(unsigned selector) {
 switch(selector) {
 case 0:return sizeof(fx_number);case 1:return offsetof(fx_number,bytes);case 2:return sizeof(((fx_number*)0)->bytes);
 case 3:return sizeof(fx_complex);case 4:return offsetof(fx_complex,real);case 5:return offsetof(fx_complex,imaginary);
 case 6:return sizeof(fx_derivative_storage);case 7:return offsetof(fx_derivative_storage,ram);case 8:return offsetof(fx_derivative_storage,ram_size);
 case 9:return sizeof(fx_calculus_control);case 10:return offsetof(fx_calculus_control,cancelled);case 11:return offsetof(fx_calculus_control,userdata);
 case 12:return sizeof(unsigned);default:return 0;
 }
}
