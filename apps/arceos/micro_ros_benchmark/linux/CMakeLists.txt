cmake_minimum_required(VERSION 3.16)
project(micro_ros_benchmark C)

if(NOT MICROROS_PREFIX)
    message(FATAL_ERROR "Set MICROROS_PREFIX to the generated micro-ROS install prefix")
endif()

set(BENCHMARK_PLATFORM "linux" CACHE STRING "Platform label in benchmark output")
set(BENCHMARK_AGENT_ADDRESS "127.0.0.1" CACHE STRING "micro-ROS Agent IPv4 address")

add_executable(micro_ros_benchmark ../c/main.c)
target_compile_features(micro_ros_benchmark PRIVATE c_std_11)
target_compile_options(micro_ros_benchmark PRIVATE -O2 -Wall -Wextra -Werror)
target_compile_definitions(micro_ros_benchmark PRIVATE
    BENCHMARK_PLATFORM="${BENCHMARK_PLATFORM}"
    BENCHMARK_AGENT_ADDRESS="${BENCHMARK_AGENT_ADDRESS}"
)
file(GLOB MICROROS_INCLUDE_CANDIDATES LIST_DIRECTORIES true "${MICROROS_PREFIX}/include/*")
set(MICROROS_INCLUDE_DIRS "${MICROROS_PREFIX}/include")
foreach(candidate IN LISTS MICROROS_INCLUDE_CANDIDATES)
    if(IS_DIRECTORY "${candidate}")
        list(APPEND MICROROS_INCLUDE_DIRS "${candidate}")
    endif()
endforeach()
target_include_directories(micro_ros_benchmark PRIVATE ${MICROROS_INCLUDE_DIRS})
target_link_libraries(micro_ros_benchmark PRIVATE
    "${MICROROS_PREFIX}/libmicroros.a"
    pthread
    rt
    m
)
