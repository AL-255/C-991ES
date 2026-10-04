#include "numeric/fx_solver_stage.h"
#include <stddef.h>
#include <stdint.h>

uint64_t solver_stage_abi(unsigned index)
{
    static const size_t fields[] = {
        sizeof(fx_number), sizeof(fx_complex), sizeof(fx_solver_context),
        sizeof(fx_solver_result), sizeof(fx_solver_linear_stage),
        offsetof(fx_solver_context, exact_math),
        offsetof(fx_solver_context, real_only),
        offsetof(fx_solver_context, cancel_at),
        offsetof(fx_solver_result, roots), offsetof(fx_solver_result, count),
        offsetof(fx_solver_result, firmware_status),
        offsetof(fx_solver_result, cancellation_checks),
        offsetof(fx_solver_result, coefficient_work),
        offsetof(fx_solver_result, root_work),
        offsetof(fx_solver_result, coefficient_rows),
        offsetof(fx_solver_result, coefficient_columns),
        offsetof(fx_solver_result, root_rows),
        offsetof(fx_solver_result, root_columns)
    };
    return index < sizeof fields / sizeof *fields ? fields[index] : UINT64_MAX;
}
