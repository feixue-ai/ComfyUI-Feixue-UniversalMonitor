/**
 * feixue_adlx_bridge.cpp — ADLX C++ Bridge 实现
 *
 * 将 AMD ADLX SDK 的 C++ COM 风格接口包装为稳定的 extern "C" 函数。
 *
 * 编译方式：与 ADLXHelper.cpp + WinAPIs.cpp 一起编译（见 CMakeLists.txt）
 * 运行时依赖：系统已安装 AMD 驱动（amd_adlx64.dll，随驱动安装）
 * 无需预编译 .lib 文件 — ADLXHelper 通过 LoadLibraryEx 动态加载
 *
 * 内部调用链：
 *   g_ADLX.Initialize()  (ADLXHelper 全局实例)
 *     → LoadLibraryEx("amd_adlx64.dll")
 *     → ADLXInitialize() → IADLXSystem
 *       → GetPerformanceMonitoringServices() → StartPerformanceMetricsTracking()
 *       → GetGPUs() → IADLXGPUList → IADLXGPU[]
 *   采集时：GetCurrentGPUMetrics(gpu) → IADLXGPUMetrics
 *     → GPUUsage / GPUTemperature / GPUVRAM / GPUChipPower
 *   关闭时：StopPerformanceMetricsTracking() → g_ADLX.Terminate()
 *
 * 异常安全：所有 extern "C" 函数用 try/catch 包裹，防止 C++ 异常跨语言边界。
 *
 * Version: 1.1.0
 * Author: Feixue Team
 */

#include "feixue_adlx_bridge.h"

#include <ADLX.h>
#include <ADLXHelper.h>   // 声明 extern ADLXHelper g_ADLX; (定义于 ADLXHelper.cpp)
#include <mutex>
#include <string>
#include <vector>

/* =========================================================================
 * 内部状态
 * ========================================================================= */

static IADLXSystem*                         g_system       = nullptr;
static IADLXPerformanceMonitoringServices*  g_perfServices = nullptr;
static std::vector<IADLXGPU*>               g_gpus;
static std::mutex                           g_mutex;
static bool                                 g_initialized  = false;

/* 线程局部错误缓冲区（避免加锁） */
static thread_local std::string g_lastError;
/* GPU 名称缓冲区（get_gpu_name 间隔调用，静态即可） */
static thread_local std::string g_nameBuf;

/* =========================================================================
 * 内部辅助
 * ========================================================================= */

static void set_error(const char* msg) {
    g_lastError = msg ? msg : "";
}

static void release_gpus() {
    for (auto* gpu : g_gpus) {
        if (gpu) gpu->Release();
    }
    g_gpus.clear();
}

static void cleanup_internal() {
    if (g_perfServices) {
        g_perfServices->StopPerformanceMetricsTracking();
        g_perfServices->Release();
        g_perfServices = nullptr;
    }
    release_gpus();
    /* g_system 由 g_ADLX.Terminate() 释放，不手动 Release */
    g_system = nullptr;
    /* 调用 g_ADLX.Terminate() 卸载 amd_adlx64.dll */
    g_ADLX.Terminate();
    g_initialized = false;
}

/* =========================================================================
 * extern "C" 实现
 * ========================================================================= */

extern "C" {

FEIXUE_API int feixue_adlx_init(void) {
    try {
        if (g_initialized) {
            return FEIXUE_ADLX_OK;
        }

        /* 1. 初始化 ADLXHelper（全局实例 g_ADLX 定义于 ADLXHelper.cpp）
         *    内部通过 LoadLibraryEx 加载 amd_adlx64.dll（随 AMD 驱动安装） */
        ADLX_RESULT res = g_ADLX.Initialize();
        if (res != ADLX_OK) {
            set_error("ADLXHelper.Initialize failed — AMD driver may not be installed");
            return FEIXUE_ADLX_INIT_FAILED;
        }

        /* 2. 获取 SystemServices */
        g_system = g_ADLX.GetSystemServices();
        if (g_system == nullptr) {
            set_error("GetSystemServices returned null");
            g_ADLX.Terminate();
            return FEIXUE_ADLX_INIT_FAILED;
        }

        /* 3. 获取 PerformanceMonitoringServices */
        res = g_system->GetPerformanceMonitoringServices(&g_perfServices);
        if (res != ADLX_OK || g_perfServices == nullptr) {
            set_error("GetPerformanceMonitoringServices failed");
            g_ADLX.Terminate();
            g_system = nullptr;
            return FEIXUE_ADLX_INIT_FAILED;
        }

        /* 4. 启动性能指标追踪 */
        res = g_perfServices->StartPerformanceMetricsTracking();
        if (res != ADLX_OK) {
            set_error("StartPerformanceMetricsTracking failed");
            /* 追踪失败不一定是致命错误，继续尝试获取 GPU 列表 */
        }

        /* 5. 枚举 GPU */
        IADLXGPUList* gpuList = nullptr;
        res = g_system->GetGPUs(&gpuList);
        if (res != ADLX_OK || gpuList == nullptr) {
            set_error("GetGPUs failed");
            cleanup_internal();
            return FEIXUE_ADLX_NO_GPU;
        }

        adlx_uint gpuCount = gpuList->Size();
        for (adlx_uint i = 0; i < gpuCount; i++) {
            IADLXGPU* gpu = nullptr;
            res = gpuList->Item(i, &gpu);
            if (res == ADLX_OK && gpu != nullptr) {
                g_gpus.push_back(gpu);
            }
        }
        gpuList->Release();

        if (g_gpus.empty()) {
            set_error("No AMD GPU detected");
            cleanup_internal();
            return FEIXUE_ADLX_NO_GPU;
        }

        g_initialized = true;
        set_error("");
        return FEIXUE_ADLX_OK;

    } catch (const std::exception& e) {
        set_error(e.what());
        cleanup_internal();
        return FEIXUE_ADLX_EXCEPTION;
    } catch (...) {
        set_error("Unknown C++ exception during init");
        cleanup_internal();
        return FEIXUE_ADLX_EXCEPTION;
    }
}

FEIXUE_API void feixue_adlx_shutdown(void) {
    try {
        std::lock_guard<std::mutex> lock(g_mutex);
        cleanup_internal();
    } catch (...) {
        /* 静默吞掉，避免异常跨边界 */
    }
}

FEIXUE_API int feixue_adlx_get_gpu_count(void) {
    if (!g_initialized) {
        set_error("Not initialized");
        return FEIXUE_ADLX_NOT_INIT;
    }
    return static_cast<int>(g_gpus.size());
}

FEIXUE_API const char* feixue_adlx_get_gpu_name(int gpu_index) {
    if (!g_initialized) {
        set_error("Not initialized");
        return nullptr;
    }
    try {
        if (gpu_index < 0 || gpu_index >= static_cast<int>(g_gpus.size())) {
            set_error("GPU index out of range");
            return nullptr;
        }

        IADLXGPU* gpu = g_gpus[gpu_index];
        char nameBuf[256] = {0};
        ADLX_RESULT res = gpu->Name(nameBuf, sizeof(nameBuf));
        if (res != ADLX_OK) {
            set_error("GPU.Name failed");
            return nullptr;
        }
        g_nameBuf = nameBuf;
        return g_nameBuf.c_str();
    } catch (...) {
        set_error("Exception in get_gpu_name");
        return nullptr;
    }
}

FEIXUE_API int feixue_adlx_get_metrics(int gpu_index,
                                       double* gpu_usage,
                                       double* temperature,
                                       unsigned long long* vram_used,
                                       unsigned long long* vram_total,
                                       double* power) {
    if (!g_initialized) {
        set_error("Not initialized");
        return FEIXUE_ADLX_NOT_INIT;
    }

    try {
        if (gpu_index < 0 || gpu_index >= static_cast<int>(g_gpus.size())) {
            set_error("GPU index out of range");
            return FEIXUE_ADLX_BAD_INDEX;
        }

        std::lock_guard<std::mutex> lock(g_mutex);

        IADLXGPU* gpu = g_gpus[gpu_index];

        /* 获取当前 GPU 指标快照 */
        IADLXGPUMetrics* metrics = nullptr;
        ADLX_RESULT res = g_perfServices->GetCurrentGPUMetrics(gpu, &metrics);
        if (res != ADLX_OK || metrics == nullptr) {
            set_error("GetCurrentGPUMetrics failed");
            return FEIXUE_ADLX_METRICS_FAIL;
        }

        /* 读取各字段，每个字段独立获取，部分失败不影响其他字段 */
        bool anySuccess = false;

        if (gpu_usage != nullptr) {
            adlx_uint usage = 0;
            res = metrics->GPUUsage(&usage);
            if (res == ADLX_OK) {
                *gpu_usage = static_cast<double>(usage);
                anySuccess = true;
            } else {
                *gpu_usage = 0.0;
            }
        }

        if (temperature != nullptr) {
            adlx_double temp = 0.0;
            res = metrics->GPUTemperature(&temp);
            if (res == ADLX_OK) {
                *temperature = temp;
                anySuccess = true;
            } else {
                *temperature = 0.0;
            }
        }

        if (vram_used != nullptr || vram_total != nullptr) {
            adlx_uint vramUsed = 0;
            adlx_uint vramTotal = 0;
            res = metrics->GPUVRAM(&vramUsed, &vramTotal);
            if (res == ADLX_OK) {
                /*
                 * ADLX GPUVRAM 返回值单位为 MB（adlx_uint 32 位，>4GB 显存以 MB 表达）。
                 * 转为 unsigned long long 输出，Python 端按 MB 使用。
                 */
                if (vram_used != nullptr)  *vram_used  = static_cast<unsigned long long>(vramUsed);
                if (vram_total != nullptr) *vram_total = static_cast<unsigned long long>(vramTotal);
                anySuccess = true;
            } else {
                if (vram_used != nullptr)  *vram_used  = 0;
                if (vram_total != nullptr) *vram_total = 0;
            }
        }

        if (power != nullptr) {
            adlx_double chipPower = 0.0;
            res = metrics->GPUChipPower(&chipPower);
            if (res == ADLX_OK) {
                *power = chipPower;
                anySuccess = true;
            } else {
                *power = 0.0;
            }
        }

        metrics->Release();

        if (!anySuccess) {
            set_error("All metrics fields failed");
            return FEIXUE_ADLX_METRICS_FAIL;
        }

        set_error("");
        return FEIXUE_ADLX_OK;

    } catch (const std::exception& e) {
        set_error(e.what());
        return FEIXUE_ADLX_EXCEPTION;
    } catch (...) {
        set_error("Unknown exception in get_metrics");
        return FEIXUE_ADLX_EXCEPTION;
    }
}

FEIXUE_API const char* feixue_adlx_last_error(void) {
    return g_lastError.c_str();
}

} /* extern "C" */
