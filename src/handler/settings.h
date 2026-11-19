#ifndef SETTINGS_H_INCLUDED
#define SETTINGS_H_INCLUDED

#include <string>

#include "config/crontask.h"
#include "config/regmatch.h"
#include "config/proxygroup.h"
#include "config/ruleset.h"
#include "generator/config/ruleconvert.h"
#include "generator/template/templates.h"
#include "utils/logger.h"
#include "utils/string.h"
#include "utils/stl_extra.h"
#include "utils/tribool.h"

// 所有远程请求（订阅 / 规则集 / 外部配置 / 预取）默认使用的 User-Agent。
// 部分机场的 Cloudflare 只放行 Clash 系 UA，用这个可以让预取也正常工作。
constexpr const char *DEFAULT_USER_AGENT = "clash-verge/v1.5.0";

struct Settings
{
    //common settings
    std::string prefPath = "pref.ini", defaultExtConfig;
    string_array excludeRemarks, includeRemarks;
    RulesetConfigs customRulesets;
    RegexMatchConfigs streamNodeRules, timeNodeRules;
    std::vector<RulesetContent> rulesetsContent;
    std::string listenAddress = "127.0.0.1", defaultUrls, insertUrls, managedConfigPrefix;
    int listenPort = 25500, maxPendingConns = 10, maxConcurThreads = 4;
    bool prependInsert = true, skipFailedLinks = false;
    bool APIMode = true, writeManagedConfig = false, enableRuleGen = true, updateRulesetOnRequest = false, overwriteOriginalRules = true;
    bool printDbgInfo = false, CFWChildProcess = false, appendUserinfo = true, asyncFetchRuleset = false, surgeResolveHostname = true;
    std::string accessToken, basePath = "base";
    // 所有远程请求统一使用的 User-Agent，可在配置文件 [common] 段用
    // user_agent 覆盖；留空则回退到 DEFAULT_USER_AGENT。
    std::string userAgent = DEFAULT_USER_AGENT;
    std::string custom_group;
    int logLevel = LOG_LEVEL_VERBOSE;
    long maxAllowedDownloadSize = 1048576L;
    string_map aliases;

    //global variables for template
    std::string templatePath = "templates";
    string_map templateVars;

    //generator settings
    bool generatorMode = false;
    std::string generateProfiles;

    //preferences
    bool reloadConfOnRequest = false;
    RegexMatchConfigs renames, emojis;
    bool addEmoji = false, removeEmoji = false, appendType = false, filterDeprecated = true;
    tribool UDPFlag, TFOFlag, skipCertVerify, TLS13Flag, enableInsert;
    bool enableSort = false, updateStrict = false;
    bool clashUseNewField = false, singBoxAddClashModes = true;
    std::string clashProxiesStyle = "flow", clashProxyGroupsStyle = "block";
    std::string proxyConfig, proxyRuleset, proxySubscription;
    int updateInterval = 0;
    std::string sortScript, filterScript;

    std::string clashBase;
    ProxyGroupConfigs customProxyGroups;
    std::string surgeBase, surfboardBase, mellowBase, quanBase, quanXBase, loonBase, SSSubBase, singBoxBase;
    std::string surgeSSRPath, quanXDevID;

    //cache system
    bool serveCacheOnFetchFail = false;
    int cacheSubscription = 60, cacheConfig = 300, cacheRuleset = 21600;

    //subscription prefetch system
    //解析阶段的暂存值。真正生效的副本由 handler/prefetch.cpp 自己持有并加锁，
    //配置解析完成后通过 prefetch_apply_config() 整体提交，避免后台线程
    //与 /readconf 并发读写同一个 vector。
    bool enablePrefetch = false;
    int prefetchInterval = 3600;
    string_array prefetchUrls;
    std::string barkUrl;

    //limits
    size_t maxAllowedRulesets = 64, maxAllowedRules = 32768;
    bool scriptCleanContext = false;

    //cron system
    bool enableCron = false;
    CronTaskConfigs cronTasks;
};


struct ExternalConfig
{
    ProxyGroupConfigs custom_proxy_group;
    RulesetConfigs surge_ruleset;
    std::string clash_rule_base;
    std::string surge_rule_base;
    std::string surfboard_rule_base;
    std::string mellow_rule_base;
    std::string quan_rule_base;
    std::string quanx_rule_base;
    std::string loon_rule_base;
    std::string sssub_rule_base;
    std::string singbox_rule_base;
    RegexMatchConfigs rename;
    RegexMatchConfigs emoji;
    string_array include;
    string_array exclude;
    template_args *tpl_args = nullptr;
    bool overwrite_original_rules = false;
    bool enable_rule_generator = true;
    tribool add_emoji;
    tribool remove_old_emoji;
};

extern Settings global;

int importItems(string_array &target, bool scope_limit = true);
int loadExternalConfig(std::string &path, ExternalConfig &ext);

template <class... Args>
void parseGroupTimes(const std::string &src, Args... args)
{
    std::array<int*, sizeof...(args)> ptrs {args...};
    string_size bpos = 0, epos = src.find(",");
    for(int *x : ptrs)
    {
        if(x != nullptr)
            *x = to_int(src.substr(bpos, epos - bpos), 0);
        if(epos != src.npos)
        {
            bpos = epos + 1;
            epos = src.find(",", bpos);
        }
        else
            return;
    }
    return;
}

#endif // SETTINGS_H_INCLUDED
