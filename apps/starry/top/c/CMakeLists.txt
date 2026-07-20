cmake_minimum_required(VERSION 3.20)

project(top-test NONE)

install(PROGRAMS ../top-test.sh DESTINATION usr/bin)

if(EXISTS "${STARRY_STAGING_ROOT}/usr/bin/top")
    set(PROCPS_TOP "${STARRY_STAGING_ROOT}/usr/bin/top")
elseif(EXISTS "${STARRY_STAGING_ROOT}/bin/top")
    set(PROCPS_TOP "${STARRY_STAGING_ROOT}/bin/top")
else()
    message(FATAL_ERROR "procps top not found in staging root")
endif()

install(PROGRAMS "${PROCPS_TOP}" DESTINATION usr/bin)
