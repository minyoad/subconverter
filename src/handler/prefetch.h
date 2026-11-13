#ifndef PREFETCH_H_INCLUDED
#define PREFETCH_H_INCLUDED

#include <string>

#include "utils/string.h"

// 订阅预取
//
// 目的：客户端第一次请求 /sub 时不用等上游，也不会因为频繁刷新触发机场限流。
// 启动时按 prefetch_url（留空则回退到 default_url）把订阅抓进本地缓存，
// 之后由 looper 定期刷新；抓取失败时通过 Bark 推送告警。

// 预取的完整配置。由 readConf() 在解析完成后一次性提交，
// 所有字段都在解析线程里读好再传进来，后台线程不再碰 global.*，
// 避免 /readconf 重载配置时与预取线程读写同一份数据。
struct PrefetchOptions
{
    bool enable = false;
    int interval = 3600;
    string_array urls;
    // prefetch_url 为空时的回退列表（common 段 default_url，已按 | 拆好）
    string_array fallbackUrls;
    // 抓订阅用的代理，由 proxy_subscription 解析好
    std::string proxy;
    std::string barkUrl;
};

// 原子地替换整套预取配置。
void prefetch_apply_config(const PrefetchOptions &options);

// 启动时调用一次：后台发起第一轮预取，让服务开始接受请求时缓存尽快变热。
// 上次成功的内容会留在 cache/ 里，抓取失败时不会被清掉。
void prefetch_on_startup();

// 由 webServer 的 looper 周期性调用（默认每 200ms），内部按间隔自行节流。
void prefetch_tick();

// 供 /prefetch 接口手动触发。
// 返回抓取结果摘要，抓取失败时顺便推送 Bark 告警。
std::string prefetch_now();

#endif // PREFETCH_H_INCLUDED
