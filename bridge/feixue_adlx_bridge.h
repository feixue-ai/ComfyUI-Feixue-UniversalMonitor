/**
 * feixue_adlx_bridge.h — ADLX C++ Bridge for Feixue UniversalMonitor
 *
 * 将 AMD ADLX SDK 的 C++ COM 风格接口包装为稳定的 extern "C" 函数，
 * 供 Python ctypes 直接调用。用户端零编译、零 pip 依赖。
 *
 * 构建方式：MSVC + ADLX SDK（见 CMakeLists.txt / GitHub Actions）
 * 运行时依赖：系统已安装 AMD 驱动（amd_adlx64.dll）
 *
 * 线程安全：init/shutdown 非线程安全（仅在启动/关闭时调用）；
 *           get_metrics 线程安全（内部加锁）。
 *
 * Version: 1.0.0
 * Author: Feixue Team
 */
#ifndef FEIXUE_ADLX_BRIDGE_H
#define FEIXUE_ADLX_BRIDGE_H

#ifdef _WIN32
#  define FEIXUE_API __declspec(dllexport)
#else
#  define FEIXUE_API
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* =========================================================================
 * 返回码定义
 * ========================================================================= */
#define FEIXUE_ADLX_OK            0   /* 成功 */
#define FEIXUE_ADLX_NOT_INIT     -1   /* 未初始化 */
#define FEIXUE_ADLX_INIT_FAILED  -2   /* 初始化失败（无 AMD 驱动/DLL 缺失） */
#define FEIXUE_ADLX_NO_GPU       -3   /* 未检测到 AMD GPU */
#define FEIXUE_ADLX_BAD_INDEX    -4   /* GPU 索引越界 */
#define FEIXUE_ADLX_METRICS_FAIL -5   /* 指标采集失败 */
#define FEIXUE_ADLX_EXCEPTION    -6   /* 内部异常 */

/* =========================================================================
 * 生命周期管理
 * ========================================================================= */

/**
 * 初始化 ADLX 运行时。
 * 必须在使用其他函数前调用一次。
 *
 * @return FEIXUE_ADLX_OK 成功；FEIXUE_ADLX_INIT_FAILED 失败（无 AMD 驱动）
 */
FEIXUE_API int feixue_adlx_init(void);

/**
 * 关闭 ADLX 运行时，释放所有资源。
 * 关闭后可重新调用 feixue_adlx_init 再次初始化。
 */
FEIXUE_API void feixue_adlx_shutdown(void);

/* =========================================================================
 * GPU 枚举
 * ========================================================================= */

/**
 * 获取 AMD GPU 数量。
 *
 * @return GPU 数量（>=0）；未初始化时返回 FEIXUE_ADLX_NOT_INIT
 */
FEIXUE_API int feixue_adlx_get_gpu_count(void);

/**
 * 获取指定 GPU 的名称。
 *
 * @param gpu_index GPU 索引（0 到 gpu_count-1）
 * @return GPU 名称字符串指针（内部静态缓冲区，下次调用覆盖）；NULL 表示失败
 */
FEIXUE_API const char* feixue_adlx_get_gpu_name(int gpu_index);

/* =========================================================================
 * 指标采集（一次调用获取全部指标，减少跨语言开销）
 * ========================================================================= */

/**
 * 获取指定 GPU 的全部指标。
 *
 * @param gpu_index   GPU 索引
 * @param gpu_usage   输出：GPU 利用率（%，0-100），可为 NULL
 * @param temperature 输出：GPU 温度（°C），可为 NULL
 * @param vram_used   输出：VRAM 已用（MB），可为 NULL
 * @param vram_total  输出：VRAM 总量（MB），可为 NULL
 * @param power       输出：GPU 功耗（W），可为 NULL
 *
 * @return FEIXUE_ADLX_OK 成功；其他为错误码
 */
FEIXUE_API int feixue_adlx_get_metrics(int gpu_index,
                                       double* gpu_usage,
                                       double* temperature,
                                       unsigned long long* vram_used,
                                       unsigned long long* vram_total,
                                       double* power);

/* =========================================================================
 * 诊断
 * ========================================================================= */

/**
 * 获取最近一次错误的描述信息。
 *
 * @return 错误描述字符串指针（内部静态缓冲区）；无错误时返回空字符串
 */
FEIXUE_API const char* feixue_adlx_last_error(void);

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* FEIXUE_ADLX_BRIDGE_H */
