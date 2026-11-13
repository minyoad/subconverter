#include <algorithm>
#include <atomic>
#include <mutex>
#include <thread>
#include <ctime>
#include <exception>

#include "handler/prefetch.h"
#include "handler/settings.h"
#include "handler/webget.h"
#include "utils/logger.h"
#include "utils/string.h"
#include "utils/urlencode.h"

namespace
{
    // 失败后重试的基础间隔：上游抖动很常见，一小时后再试就太晚了。
    constexpr int retry_delay = 300;
    constexpr int default_interval = 3600;

    // 配置由本模块持有并加锁：预取跑在后台线程，而 /readconf 会在请求线程里
    // 重新加载配置，两个线程同时读写同一个 std::vector 就是数据竞争。
    // 对外只暴露 prefetch_apply_config() 这一个整体替换入口，读侧统一做快照。
    //
    // generation 与配置放在同一把锁里，一起取快照。它的用途是判断
    // 「这一轮跑的是不是最新配置」：运行期间配置若被改过，跑完就不要排下一轮，
    // 而是立刻让 tick 用新配置再跑一次，否则新配置要等满一个 interval 才生效。
    std::mutex cfg_mutex;
    PrefetchOptions g_cfg;
    unsigned g_generation = 0;

    // 调度状态
    std::mutex sched_mutex;
    std::atomic_bool prefetch_running{false};
    time_t next_prefetch = 0; // 0 表示「尽快执行下一轮」

    struct prefetch_result
    {
        size_t total = 0;
        size_t failed = 0;
    };

    struct prefetch_snapshot
    {
        PrefetchOptions options;
        unsigned generation = 0;
    };

    prefetch_snapshot snapshot()
    {
        std::lock_guard<std::mutex> guard(cfg_mutex);
        return {g_cfg, g_generation};
    }

    int effective_interval(const PrefetchOptions &cfg)
    {
        return cfg.interval > 0 ? cfg.interval : default_interval;
    }

    // prefetch_url 优先，留空时回退到 default_url。
    // 只保留 http(s) 地址：data: 之类的内联内容没必要、也没法预取。
    string_array resolve_urls(const PrefetchOptions &cfg)
    {
        const string_array &urls = cfg.urls.empty() ? cfg.fallbackUrls : cfg.urls;

        string_array result;
        for(auto &x : urls)
        {
            std::string url = trim(x);
            if(url.empty())
                continue;
            if(!startsWith(url, "http://") && !startsWith(url, "https://"))
                continue;
            if(std::find(result.begin(), result.end(), url) != result.end()) // 去重
                continue;
            result.emplace_back(std::move(url));
        }
        return result;
    }

    // Bark 推送：{bark_url}/{title}/{body}?group=...&ttl=...
    // bark_url 填到 device key 为止。若用户自带查询串，保留它并补上缺失的 group/ttl，
    // 但路径部分必须插在 '?' 之前，否则 URL 结构就错了。
    void send_bark(const std::string &bark_url, const std::string &proxy, const std::string &title, const std::string &body)
    {
        if(bark_url.empty())
            return;

        std::string url = bark_url;
        // 先丢掉 #fragment：留着会被当成 device key 的一部分，拼出来的 URL 就错了
        std::string::size_type h = url.find('#');
        if(h != std::string::npos)
            url.erase(h);

        std::string query;
        std::string::size_type q = url.find('?');
        if(q != std::string::npos)
        {
            query = url.substr(q + 1);
            url.erase(q);
        }
        while(!url.empty() && url.back() == '/')
            url.pop_back();
        url += "/" + urlEncode(title) + "/" + urlEncode(body);

        if(query.empty())
            query = "group=subconverter&ttl=600";
        else
        {
            if(query.find("group=") == std::string::npos)
                query += "&group=subconverter";
            if(query.find("ttl=") == std::string::npos)
                query += "&ttl=600";
        }
        url += "?" + query;

        FetchArgument argument {HTTP_GET, url, proxy, nullptr, nullptr, nullptr, 0};
        int status_code = 0;
        std::string content;
        FetchResult fetch_res {&status_code, &content, nullptr, nullptr};
        webGet(argument, fetch_res);
        if(status_code == 200)
            writeLog(0, "Bark notification sent: " + title, LOG_LEVEL_INFO);
        else
            writeLog(0, "Bark notification failed, status code " + std::to_string(status_code), LOG_LEVEL_WARNING);
    }

    prefetch_result prefetch_all(const PrefetchOptions &cfg)
    {
        prefetch_result res;
        string_array urls = resolve_urls(cfg);
        if(urls.empty())
        {
            writeLog(0, "Prefetch skipped: neither prefetch_url nor default_url is configured.", LOG_LEVEL_INFO);
            return res;
        }

        string_array failed;
        for(auto &url : urls)
        {
            // 强制回源，成功即写入 webGet 使用的同一份缓存，客户端随后能直接命中
            if(!webGetAndCache(url, cfg.proxy))
                failed.emplace_back(url);
        }

        res.total = urls.size();
        res.failed = failed.size();
        if(!failed.empty())
        {
            writeLog(0, "Prefetch failed for " + std::to_string(failed.size()) + " subscription(s).", LOG_LEVEL_WARNING);
            send_bark(cfg.barkUrl, cfg.proxy, "订阅刷新失败",
                      join(failed, "\n") + "\n\n" +
                      std::to_string(res.total - res.failed) + "/" + std::to_string(res.total) + " succeeded");
        }
        else
            writeLog(0, "Prefetch succeeded for all " + std::to_string(res.total) + " subscription(s).", LOG_LEVEL_INFO);
        return res;
    }

    // 失败就早点重试，成功则按配置的间隔。
    // generation 是这一轮开始时配置的代次；如果跑完发现代次已经变了，
    // 说明期间 /readconf 改过配置，此时把排期清 0 让 tick 立刻用新配置再跑一轮。
    void schedule_next(const PrefetchOptions &cfg, unsigned generation, const prefetch_result &res)
    {
        int interval = effective_interval(cfg);
        int delay = res.failed > 0 ? std::min(interval, retry_delay) : interval;

        bool stale;
        {
            std::lock_guard<std::mutex> guard(cfg_mutex);
            stale = (generation != g_generation);
        }

        std::lock_guard<std::mutex> guard(sched_mutex);
        next_prefetch = stale ? 0 : time(nullptr) + delay;
    }

    // 在后台线程里跑，避免拖住 webServer 的 looper（默认 200ms 一跳，还在跑 cron）。
    // 返回 false 表示上一轮还没跑完、本轮被跳过（或线程起不来）。
    bool prefetch_in_background(const prefetch_snapshot &snap)
    {
        // 先占住 running 再排期：running 才是真正的互斥闸门，
        // 这样不会出现「先改写 next_prefetch 又被跳过」导致的额外一轮。
        if(prefetch_running.exchange(true))
            return false; // 上一轮还没跑完，跳过本轮

        // 占位，避免后台线程起来之前又被 tick 一次。
        // 线程跑完时由 schedule_next() 按成败改写这个时间点。
        {
            std::lock_guard<std::mutex> guard(sched_mutex);
            next_prefetch = time(nullptr) + effective_interval(snap.options);
        }

        try
        {
            std::thread([snap]()
            {
                // 无论正常结束还是抛异常都要复位，否则预取会永久卡死。
                struct reset_guard
                {
                    ~reset_guard() { prefetch_running.store(false); }
                } guard;
                // 线程里抛出去就是 std::terminate，这里必须全部接住。
                try
                {
                    prefetch_result res = prefetch_all(snap.options);
                    schedule_next(snap.options, snap.generation, res);
                }
                catch(const std::exception &e)
                {
                    writeLog(0, std::string("Prefetch aborted: ") + e.what(), LOG_LEVEL_WARNING);
                    schedule_next(snap.options, snap.generation, prefetch_result {0, 1});
                }
                catch(...)
                {
                    writeLog(0, "Prefetch aborted: unknown exception.", LOG_LEVEL_WARNING);
                    schedule_next(snap.options, snap.generation, prefetch_result {0, 1});
                }
            }).detach();
        }
        catch(...)
        {
            {
                std::lock_guard<std::mutex> guard(sched_mutex);
                next_prefetch = 0;
            }
            prefetch_running.store(false);
            writeLog(0, "Prefetch failed to start a background thread.", LOG_LEVEL_WARNING);
            return false;
        }
        return true;
    }
}

void prefetch_apply_config(const PrefetchOptions &options)
{
    bool changed;
    {
        std::lock_guard<std::mutex> guard(cfg_mutex);
        changed = !(g_cfg.enable == options.enable
                    && g_cfg.interval == options.interval
                    && g_cfg.urls == options.urls
                    && g_cfg.fallbackUrls == options.fallbackUrls
                    && g_cfg.proxy == options.proxy
                    && g_cfg.barkUrl == options.barkUrl);
        g_cfg = options;
        if(changed)
            ++g_generation;
    }

    // 配置真的变了就重新排期：否则改完地址还要等满一个 interval 才生效。
    // 配置没变时不动，避免 reload_conf_on_request 每隔一个请求就回源一次。
    if(changed)
    {
        std::lock_guard<std::mutex> guard(sched_mutex);
        next_prefetch = 0;
    }
}

void prefetch_on_startup()
{
    prefetch_snapshot snap = snapshot();
    if(!snap.options.enable)
        return;

    // 预取写的是 webGet() 的缓存，cacheSubscription 为 0 时客户端根本不会读缓存，
    // 预取就成了空转，这里明确提醒一下。启动阶段单线程，直接读 global 是安全的。
    if(global.cacheSubscription <= 0)
        writeLog(0, "Prefetch is enabled but cache_subscription is 0, clients will not read the prefetched cache. Set enable_cache=true.", LOG_LEVEL_WARNING);

    // 放到后台线程：上游挂掉时每个地址最多要等 15 秒超时，
    // 同步跑会把「开始监听端口」一起拖住，客户端反而连不上。
    // 后台跑不影响正确性——首个请求若没赶上缓存，会按原有逻辑自己回源一次。
    writeLog(0, "Prefetch started on startup.", LOG_LEVEL_INFO);
    prefetch_in_background(snap);
}

void prefetch_tick()
{
    prefetch_snapshot snap = snapshot();
    if(!snap.options.enable)
        return;
    {
        std::lock_guard<std::mutex> guard(sched_mutex);
        if(next_prefetch != 0 && time(nullptr) < next_prefetch)
            return;
    }
    prefetch_in_background(snap);
}

std::string prefetch_now()
{
    prefetch_snapshot snap = snapshot();
    if(!snap.options.enable)
        return "prefetch disabled";
    if(prefetch_running.exchange(true))
        return "prefetch already running";

    // 先占位，避免手动执行期间 looper 的 tick 又拉一轮。
    {
        std::lock_guard<std::mutex> guard(sched_mutex);
        next_prefetch = time(nullptr) + effective_interval(snap.options);
    }

    prefetch_result res;
    try
    {
        res = prefetch_all(snap.options);
    }
    catch(const std::exception &e)
    {
        prefetch_running.store(false);
        writeLog(0, std::string("Prefetch aborted: ") + e.what(), LOG_LEVEL_WARNING);
        schedule_next(snap.options, snap.generation, prefetch_result {0, 1});
        return "prefetch aborted";
    }
    catch(...)
    {
        prefetch_running.store(false);
        writeLog(0, "Prefetch aborted: unknown exception.", LOG_LEVEL_WARNING);
        schedule_next(snap.options, snap.generation, prefetch_result {0, 1});
        return "prefetch aborted";
    }
    prefetch_running.store(false);

    // 与后台线程一致：正常按成败排下一轮；若期间配置变过则清 0，让 tick 立刻用新配置跑。
    schedule_next(snap.options, snap.generation, res);

    if(res.total == 0)
        return "no url configured";
    return std::to_string(res.total - res.failed) + "/" + std::to_string(res.total) + " succeeded";
}
