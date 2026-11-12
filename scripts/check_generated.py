#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
校验 subconverter 生成的 Clash 配置里，AI 分流与地区自动组是否符合预期。

用法：
    python scripts/check_generated.py out_clash.yaml

检查项：
  1. 地区自动组：type 必须是 url-test，且组内节点全部属于该地区，不能混入其它地区
  2. 地区自动组不能退化成 DIRECT / REJECT，也不能混入兜底策略组
  3. AI 顶层组：必须引用 美国自动 / 新加坡自动，且末尾是兜底组 🚀 节点选择
  4. AI 规则必须排在 GEOIP,CN 与 MATCH 之前
  5. 订阅里的"剩余流量/到期时间"垃圾节点必须已被过滤

依赖：pyyaml
"""
import io
import re
import sys

try:
    import yaml
except ImportError:
    print('!! 需要 pyyaml： pip install pyyaml')
    sys.exit(2)

# 与 base/config/AI_auto.ini 保持一致
US = (r'(?i)(美国|(^|[^a-zA-Z])US|United States|洛杉矶|Los Angeles|圣何塞|San Jose|'
      r'西雅图|Seattle|达拉斯|Dallas|纽约|New York|芝加哥|Chicago|迈阿密|Miami|'
      r'硅谷|Silicon Valley|阿什本|Ashburn)')
SG = r'(?i)(新加坡|狮城|Singapore|(^|[^a-zA-Z])SG)'
JUNK = r'(?i)(距离|剩余|重置|流量|到期|过期|官网|套餐|expire|traffic)'

AUTO_GROUPS = ['🇺🇸 美国自动', '🇸🇬 新加坡自动']
AI_GROUPS = ['🤖 OpenAI', '🎭 Claude', '🎬 Muse', '🧠 其它 AI']
FALLBACK = '🚀 节点选择'


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    path = sys.argv[1]
    d = yaml.safe_load(io.open(path, encoding='utf-8').read())

    groups = {g.get('name'): g for g in d.get('proxy-groups') or []}
    proxies = [p.get('name', '') for p in d.get('proxies') or []]
    rules = d.get('rules') or []

    print('file    :', path)
    print('proxies :', len(proxies))
    print('groups  :', len(groups))
    print('rules   :', len(rules))

    errors = []

    # ---- 1/2. 地区自动组 ----
    print('\n=== 地区自动组 ===')
    for g in AUTO_GROUPS:
        if g not in groups:
            errors.append('缺少策略组: ' + g)
            continue
        grp = groups[g]
        ps = grp.get('proxies') or []
        print('%-12s type=%-9s %d 项' % (g, grp.get('type'), len(ps)))
        for n in ps:
            print('     ', n)
        if grp.get('type') != 'url-test':
            errors.append('%s 类型不是 url-test（实际 %s）' % (g, grp.get('type')))
        if not ps:
            errors.append('%s 组为空' % g)
        for n in ps:
            if n in ('DIRECT', 'REJECT') or n.startswith('[]') or n == FALLBACK:
                errors.append('%s 混入非地区项: %s' % (g, n))
                continue
            hit_us, hit_sg = re.search(US, n), re.search(SG, n)
            if g == AUTO_GROUPS[0]:
                if not hit_us:
                    errors.append('%s 混入非美国节点: %s' % (g, n))
                if hit_sg:
                    errors.append('%s 混入新加坡节点: %s' % (g, n))
            else:
                if not hit_sg:
                    errors.append('%s 混入非新加坡节点: %s' % (g, n))
                if hit_us:
                    errors.append('%s 混入美国节点: %s' % (g, n))

    # ---- 3. AI 顶层组 ----
    print('\n=== AI 策略组 ===')
    for g in AI_GROUPS:
        if g not in groups:
            errors.append('缺少策略组: ' + g)
            continue
        ps = groups[g].get('proxies') or []
        print('%-12s type=%-7s %d 项  前3=%s  末项=%s'
              % (g, groups[g].get('type'), len(ps), ps[:3], ps[-1] if ps else None))
        if groups[g].get('type') != 'select':
            errors.append('%s 类型不是 select' % g)
        for need in AUTO_GROUPS:
            if need not in ps:
                errors.append('%s 没有引用 %s' % (g, need))
        if not ps or ps[-1] != FALLBACK:
            errors.append('%s 末尾不是兜底组 %s（真实 IP 泄露风险）' % (g, FALLBACK))

    # ---- 4. 规则顺序 ----
    print('\n=== 规则顺序 ===')
    idx = {}
    for i, r in enumerate(rules):
        low = r.lower()
        if 'openai' in low:
            idx.setdefault('OpenAI', i)
        if 'anthropic' in low or 'claude' in low:
            idx.setdefault('Claude', i)
        if 'muse' in low:
            idx.setdefault('Muse', i)
        if r.startswith('GEOIP,CN'):
            idx.setdefault('GEOIP,CN', i)
        if r.startswith('MATCH'):
            idx.setdefault('MATCH', i)
    print(idx)
    for k in ('OpenAI', 'Claude', 'Muse'):
        if k not in idx:
            errors.append('规则里找不到 %s' % k)
            continue
        for late in ('GEOIP,CN', 'MATCH'):
            if late in idx and idx[k] > idx[late]:
                errors.append('%s 规则排在 %s 之后' % (k, late))

    # ---- 5. 垃圾节点 ----
    print('\n=== 垃圾节点 ===')
    junk = [p for p in proxies if re.search(JUNK, p)]
    print('命中:', junk if junk else '无')
    if junk:
        errors.append('垃圾节点未被过滤: %r' % junk)

    print()
    if errors:
        print('FAILED (%d):' % len(errors))
        for e in errors:
            print('  -', e)
        return 1
    print('ALL CHECKS PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
