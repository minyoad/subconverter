#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用真实订阅节点名验证 base/config/AI_auto.ini 里的地区正则是否命中正确。

用法：
    python scripts/verify_ai_regex.py <clash.yaml|URL>
"""
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze_nodes import load_names  # noqa: E402

US = r"(?i)(美国|(^|[^a-zA-Z])US|United States|洛杉矶|Los Angeles|圣何塞|San Jose|" \
     r"西雅图|Seattle|达拉斯|Dallas|纽约|New York|芝加哥|Chicago|迈阿密|Miami|" \
     r"硅谷|Silicon Valley|阿什本|Ashburn)"
SG = r"(?i)(新加坡|狮城|Singapore|(^|[^a-zA-Z])SG)"

# 期望：命中后还应该被"排除"的垃圾节点
JUNK = r"(?i)(距离|剩余|重置|流量|到期|官网|expire|traffic|套餐)"

# 期望：绝对不能命中的其它地区（防止 Australia/US 误伤）
OTHER = {
    "澳大利亚": r"(?i)(澳大利亚|澳洲|Australia|Sydney)",
    "马来西亚": r"(?i)(Malaysia)",
    "荷兰": r"(?i)(Netherlands)",
    "香港": r"(?i)(Hong Kong|香港)",
    "日本": r"(?i)(Japan|日本)",
    "台湾": r"(?i)(Taiwan|台湾)",
    "韩国": r"(?i)(Korea|韩国)",
    "英国": r"(?i)(United Kingdom|英国)",
    "德国": r"(?i)(Germany|德国)",
}


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "mybacc.yaml"
    names = load_names(src)
    if not names:
        return 1

    print("共 %d 个节点\n" % len(names))

    us = [n for n in names if re.search(US, n) and not re.search(JUNK, n)]
    sg = [n for n in names if re.search(SG, n) and not re.search(JUNK, n)]
    junk = [n for n in names if re.search(JUNK, n)]

    print("美国组命中 %d 个：" % len(us))
    for n in us:
        print("   ", n)
    print("\n新加坡组命中 %d 个：" % len(sg))
    for n in sg:
        print("   ", n)
    print("\n按 JUNK 排除的节点 %d 个：" % len(junk))
    for n in junk:
        print("   ", n)

    errors = []
    # 1) 美/新 互斥
    for n in us:
        if re.search(SG, n):
            errors.append("US/SG 同时命中: " + n)
    # 2) 不能误伤其它地区
    for label, pat in OTHER.items():
        for n in us + sg:
            if re.search(pat, n):
                errors.append("误命中 %s: %s" % (label, n))
    # 3) 垃圾节点不能进组
    for n in us + sg:
        if re.search(JUNK, n):
            errors.append("垃圾节点进组: " + n)

    print("\n" + "=" * 60)
    if errors:
        print("FAILED:")
        for e in errors:
            print("  -", e)
        return 1
    print("OK: 美/新分组互斥、无误伤、无垃圾节点")
    return 0


if __name__ == "__main__":
    sys.exit(main())
