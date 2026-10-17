cmake_minimum_required(VERSION 3.20.0)

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(software_virq_latency_suspend)

if(NOT DEFINED VIRQ_SAMPLES)
  set(VIRQ_SAMPLES 300)
endif()
if(NOT VIRQ_SAMPLES MATCHES "^[0-9]+$" OR VIRQ_SAMPLES LESS 1 OR VIRQ_SAMPLES GREATER 1000)
  message(FATAL_ERROR "VIRQ_SAMPLES must be between 1 and 1000")
endif()
target_compile_definitions(app PRIVATE SAMPLE_COUNT=${VIRQ_SAMPLES})
target_sources(app PRIVATE src/main.c)
