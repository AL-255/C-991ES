#include "../../csrc/numeric/fx_finite_series_storage.h"
#include <stddef.h>
size_t finite_series_abi(unsigned field) {
 const size_t values[]={
 sizeof(fx_number),sizeof(fx_complex),sizeof(fx_finite_series_storage),
 offsetof(fx_finite_series_storage,ram),offsetof(fx_finite_series_storage,ram_size),
 offsetof(fx_finite_series_storage,rom),offsetof(fx_finite_series_storage,rom_size),
 sizeof(fx_finite_series_state),offsetof(fx_finite_series_state,records),
 offsetof(fx_finite_series_state,value),offsetof(fx_finite_series_state,source),
 offsetof(fx_finite_series_state,body_source),offsetof(fx_finite_series_state,kind),
 offsetof(fx_finite_series_state,phase),offsetof(fx_finite_series_state,native_status),
 offsetof(fx_finite_series_state,spilled),sizeof(fx_finite_series_evaluation),
 offsetof(fx_finite_series_evaluation,value),offsetof(fx_finite_series_evaluation,source),
 offsetof(fx_finite_series_evaluation,condition),offsetof(fx_finite_series_evaluation,error_sink_written),
 offsetof(fx_finite_series_evaluation,error_sink),sizeof(fx_calculus_control)};
 return field < sizeof(values)/sizeof(values[0]) ? values[field] : (size_t)-1;
}
