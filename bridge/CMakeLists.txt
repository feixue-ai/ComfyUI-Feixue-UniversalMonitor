# CMakeLists.txt — 构建 feixue_adlx_bridge.dll
#
# ADLX SDK 以源码形式提供（ADLXHelper.cpp + WinAPIs.cpp），
# 运行时通过 LoadLibraryEx 动态加载 amd_adlx64.dll（随 AMD 驱动安装）。
# 因此不需要任何预编译的 .lib 文件，CI 可直接编译。
#
# 使用方式（本地或 CI）：
#   cmake -B build -S bridge -DADLX_SDK_PATH="/path/to/ADLX-repo" -G "Visual Studio 17 2022" -A x64
#   cmake --build build --config Release
#
# 产物：build/output/feixue_adlx_bridge.dll（x64）

cmake_minimum_required(VERSION 3.16)
project(feixue_adlx_bridge LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# ---------------------------------------------------------------------------
# ADLX SDK 路径（指向 ADLX GitHub 仓库根目录，包含 SDK/ 子目录）
# 通过 -DADLX_SDK_PATH 指定，或环境变量 ADLX_SDK_PATH
# ---------------------------------------------------------------------------
if(NOT ADLX_SDK_PATH)
    if(DEFINED ENV{ADLX_SDK_PATH})
        set(ADLX_SDK_PATH $ENV{ADLX_SDK_PATH})
    else()
        message(FATAL_ERROR
            "ADLX SDK path not specified. "
            "Pass -DADLX_SDK_PATH=/path/to/ADLX or set ADLX_SDK_PATH env var.")
    endif()
endif()

# ADLX SDK 目录结构：
#   SDK/Include/           — 头文件 (ADLX.h, ADLXDefines.h, ADLXStructures.h)
#   SDK/ADLXHelper/Windows/Cpp/  — ADLXHelper 源码 (ADLXHelper.cpp/.h)
#   SDK/Platform/Windows/  — 平台封装 (WinAPIs.cpp)
set(ADLX_INCLUDE_DIR  "${ADLX_SDK_PATH}/SDK/Include")
set(ADLX_HELPER_DIR   "${ADLX_SDK_PATH}/SDK/ADLXHelper/Windows/Cpp")
set(ADLX_PLATFORM_DIR "${ADLX_SDK_PATH}/SDK/Platform/Windows")

if(NOT EXISTS "${ADLX_INCLUDE_DIR}/ADLX.h")
    message(FATAL_ERROR "ADLX.h not found at ${ADLX_INCLUDE_DIR}")
endif()
if(NOT EXISTS "${ADLX_HELPER_DIR}/ADLXHelper.cpp")
    message(FATAL_ERROR "ADLXHelper.cpp not found at ${ADLX_HELPER_DIR}")
endif()

# ---------------------------------------------------------------------------
# 源文件：我们的 bridge + ADLX SDK 源码（纯源码编译，零 .lib 依赖）
# ---------------------------------------------------------------------------
add_library(feixue_adlx_bridge SHARED
    feixue_adlx_bridge.cpp
    feixue_adlx_bridge.h
    "${ADLX_HELPER_DIR}/ADLXHelper.cpp"
    "${ADLX_HELPER_DIR}/ADLXHelper.h"
    "${ADLX_PLATFORM_DIR}/WinAPIs.cpp"
)

target_include_directories(feixue_adlx_bridge PRIVATE
    "${ADLX_INCLUDE_DIR}"
    "${ADLX_HELPER_DIR}"
)

# 输出目录：便于 CI 收集产物
set_target_properties(feixue_adlx_bridge PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/output"
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/output"
    ARCHIVE_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/output"
)

# Windows MSVC 编译选项
if(MSVC)
    # /EHsc — C++ 异常启用（用于 try/catch 防止跨语言边界）
    # /O2 — Release 优化
    # /wd4819 — 禁止 Unicode 编码警告（ADLX 头文件可能有非 ASCII 字符）
    target_compile_options(feixue_adlx_bridge PRIVATE /EHsc /wd4819)
    target_compile_options(feixue_adlx_bridge PRIVATE $<$<CONFIG:Release>:/O2>)
endif()
