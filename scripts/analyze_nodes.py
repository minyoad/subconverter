#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分析 Clash 订阅里的节点命名，输出可用于 subconverter 正则/策略组的统计结果。

用法：
    python scripts/analyze_nodes.py <订阅yaml或本地文件|URL> [更多...]

输出：
    1. 节点总数
    2. 地区关键词命中统计
    3. 未命中任何地区关键词的节点（需人工确认命名习惯）
    4. 美国/新加坡 结论，以及可直接粘贴的 custom_proxy_group 正则

依赖：pyyaml（flow 风格 YAML 必需）
"""
import io
import os
import re
import sys

try:
    import yaml
except ImportError:
    yaml = None

REGIONS = [
    ("美国", r"(?i)(美国|(^|[^a-zA-Z])US\d|United States|洛杉矶|Los Angeles|圣何塞|San Jose|"
             r"西雅图|Seattle|达拉斯|Dallas|纽约|New York|芝加哥|Chicago|迈阿密|Miami|"
             r"硅谷|Silicon Valley|阿什本|Ashburn|凤凰城|Phoenix|拉斯维加斯|Las Vegas)"),
    ("新加坡", r"(?i)(新加坡|狮城|Singapore|(^|[^a-zA-Z])SG\d)"),
    ("香港", r"(?i)(香港|(^|[^a-zA-Z])HK\d|Hong ?Kong|HKG)"),
    ("日本", r"(?i)(日本|(^|[^a-zA-Z])JP\d|Japan|东京|Tokyo|大阪|Osaka)"),
    ("台湾", r"(?i)(台湾|台灣|(^|[^a-zA-Z])TW\d|Taiwan|台北)"),
    ("韩国", r"(?i)(韩国|韓國|(^|[^a-zA-Z])KR\d|Korea|首尔|Seoul)"),
    ("英国", r"(?i)(英国|(^|[^a-zA-Z])UK\d|United Kingdom|London|伦敦)"),
    ("德国", r"(?i)(德国|(^|[^a-zA-Z])DE\d|Germany|Frankfurt|法兰克福)"),
    ("马来西亚", r"(?i)(马来西亚|(^|[^a-zA-Z])MY\d|Malaysia)"),
    ("澳大利亚", r"(?i)(澳大利亚|澳洲|(^|[^a-zA-Z])AU\d|Australia|Sydney|悉尼)"),
    ("加拿大", r"(?i)(加拿大|(^|[^a-zA-Z])CA\d|Canada|Toronto|多伦多)"),
    ("印度", r"(?i)(印度|(^|[^a-zA-Z])IN\d|India|Mumbai|孟买)"),
    ("土耳其", r"(?i)(土耳其|(^|[^a-zA-Z])TR\d|Turkey|Istanbul)"),
    ("阿根廷", r"(?i)(阿根廷|(^|[^a-zA-Z])AR\d|Argentina)"),
]


def load_text(src):
    if src.startswith("http://") or src.startswith("https://"):
        from urllib.request import Request, urlopen
        req = Request(src, headers={"User-Agent": "clash-verge/v1.7.0"})
        return urlopen(req, timeout=180).read().decode("utf-8", "replace")
    return io.open(src, encoding="utf-8", errors="replace").read()


def load_names(src):
    text = load_text(src)
    if yaml is None:
        print("!! 需要 pyyaml： pip install pyyaml")
        return []
    try:
        doc = yaml.safe_load(text)
    except Exception as e:
        print("!! YAML 解析失败: %s" % e)
        return []
    if not isinstance(doc, dict):
        print("!! 不是 clash 配置（顶层不是 dict）")
        return []
    proxies = doc.get("proxies") or doc.get("Proxy") or []
    if not isinstance(proxies, list):
        return []
    names = []
    for p in proxies:
        if isinstance(p, dict) and p.get("name"):
            names.append(str(p["name"]))
    return names


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    all_names, seen = [], set()
    for src in sys.argv[1:]:
        ns = load_names(src)
        print("== %s : %d 个节点 ==" % (src, len(ns)))
        for n in ns:
            if n not in seen:
                seen.add(n)
                all_names.append(n)

    if not all_names:
        print("没有解析到任何节点名。")
        return 1

    print("\n去重后共 %d 个节点\n" % len(all_names))

    matched = set()
    print("%-10s %6s  样例" % ("地区", "数量"))
    print("-" * 72)
    for label, pat in REGIONS:
        hit = [n for n in all_names if re.search(pat, n)]
        for n in hit:
            matched.add(n)
        print("%-10s %6d  %s" % (label, len(hit), ", ".join(hit[:3])))

    unmatched = [n for n in all_names if n not in matched]
    print("\n未命中任何地区关键词：%d 个" % len(unmatched))
    for n in unmatched[:30]:
        print("   ", n)
    if len(unmatched) > 30:
        print("    ... 还有 %d 个" % (len(unmatched) - 30))

    us = [n for n in all_names if re.search(REGIONS[0][1], n)]
    sg = [n for n in all_names if re.search(REGIONS[1][1], n)]
    print("\n" + "=" * 72)
    print("美国 %d 个：" % len(us))
    for n in us:
        print("   ", n)
    print("新加坡 %d 个：" % len(sg))
    for n in sg:
        print("   ", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
