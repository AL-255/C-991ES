cmake_minimum_required(VERSION 3.16)
project(fx991_firmware_c VERSION 0.1.0 LANGUAGES C)
set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)
option(FX_ENABLE_SANITIZERS "Build C ports with address and undefined-behavior sanitizers" OFF)

add_library(fx991_firmware STATIC
    data/fx_rom_data.c
    parse/fx_tokens.c
    parse/fx_eval.c
    platform/fx_platform.c
    platform/fx_boot.c
    platform/fx_host_bridge.c
    ui/fx_keys.c
    ui/fx_cursor.c
    ui/fx_key_dispatch.c
    ui/fx_key_wait.c
    ui/fx_editor.c
    ui/fx_construct_editor.c
    ui/fx_natural_editor.c
    ui/fx_input_codec.c
    numeric/fx_transcend.c
    numeric/fx_power.c
    numeric/fx_root.c
    numeric/fx_combinatorics.c
    numeric/fx_logbase.c
    numeric/fx_numeric.c
    complex/fx_complex.c
    complex/fx_complex_angle.c
    complex/fx_complex_round.c
    stats/fx_stats.c
    stats/fx_stats_cache.c
    stats/normal/fx_stats_normal.c
    trig/fx_trig.c
    trig/fx_trig_math.c
    trig/fx_trig_inverse.c
    trig/fx_trig_hyperbolic.c
    trig/fx_math_context.c
    render/fx_render.c
    render/fx_render_memory.c
    render/fx_render_context.c
    render/fx_layout.c
    render/fx_layout_validate.c
    render/fx_viewport.c
    render/fx_result.c
    render/fx_result_linear.c
    render/fx_result_special.c
    render/fx_result_format_state.c
    render/fx_result_inequality.c
    format/fx_format.c
    format/fx_format_budget.c
    format/fx_format_base.c)
target_include_directories(fx991_firmware PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(fx991_firmware PRIVATE -Wall -Wextra -Werror)
    if(FX_ENABLE_SANITIZERS)
        target_compile_options(fx991_firmware PUBLIC -fsanitize=address,undefined -fno-omit-frame-pointer)
        target_link_options(fx991_firmware PUBLIC -fsanitize=address,undefined)
    endif()
endif()

add_executable(fx991c app/fx991c.c)
target_link_libraries(fx991c PRIVATE fx991_firmware)
if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(fx991c PRIVATE -Wall -Wextra -Werror)
endif()

include(CTest)
if(BUILD_TESTING)
    add_executable(fx991c_safety tests/behavior_safety.c)
    target_link_libraries(fx991c_safety PRIVATE fx991_firmware)
    # Assertions are the safety harness contract, including Release builds.
    if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
        target_compile_options(fx991c_safety PRIVATE -Wall -Wextra -Werror -UNDEBUG)
    endif()
    add_test(NAME public_api_bounds COMMAND fx991c_safety)
    set_tests_properties(public_api_bounds PROPERTIES
        ENVIRONMENT "ASAN_OPTIONS=detect_leaks=0:halt_on_error=1;UBSAN_OPTIONS=halt_on_error=1")
    find_package(Python3 REQUIRED COMPONENTS Interpreter)
    foreach(subsystem tokens platform boot keys key_dispatch key_wait cursor editor editor_construct input_codec numeric numeric_transcend numeric_power numeric_root numeric_logbase combinatorics complex complex_angles complex_round stats stats_cache stats_normal trig trig_math trig_inverse trig_hyperbolic math_context render format format_base format_budget eval cli)
        add_test(NAME differential_${subsystem}
                 COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/../tools/test_${subsystem}_c.py)
        set_tests_properties(differential_${subsystem} PROPERTIES
                             WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}/..)
    endforeach()
endif()
