set(CMAKE_SYSTEM_NAME Generic)
set(CMAKE_SYSTEM_PROCESSOR aarch64)
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)

set(CMAKE_C_COMPILER aarch64-linux-gnu-gcc)
set(CMAKE_CXX_COMPILER aarch64-linux-gnu-g++)

set(ARCEOS_COMMON_FLAGS
    "-O2 -ffreestanding -fno-builtin -fno-stack-protector -fno-tree-vectorize -mstrict-align -mno-outline-atomics -ffunction-sections -fdata-sections -U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=0 -U__linux__ -U__linux -U__gnu_linux__ -Ulinux"
)
set(CMAKE_C_FLAGS_INIT "${ARCEOS_COMMON_FLAGS}")
set(CMAKE_CXX_FLAGS_INIT
    "${ARCEOS_COMMON_FLAGS} -fno-exceptions -fno-rtti"
)

set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
