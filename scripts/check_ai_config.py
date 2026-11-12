#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
校验 base/config/AI_auto.ini 与 AI_auto.toml 的配置自洽性：
  1. custom_proxy_group 字段数与类型合法（自动组必须 >=5 段）
  2. [] 引用的策略组都存在
  3. ruleset 指向的策略组都存在
  4. ruleset 引用的本地规则文件都存在
  5. 规则文件每行都是 "TYPE,value" 两段
  6. INI 与 TOML 两版策略组/规则顺序一致

用法： python scripts/check_ai_config.py
"""
import io
import os
import re
import sys
import tomllib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

BASE = 'base'
INI_PATH = os.path.join(BASE, 'config', 'AI_auto.ini')
TOML_PATH = os.path.join(BASE, 'config', 'AI_auto.toml')
RULE_FILES = ('rules/OpenAI.list', 'rules/Claude.list',
              'rules/Muse.list', 'rules/AI.list')

AUTO_TYPES = ('url-test', 'fallback', 'load-balance')
ALL_TYPES = ('select', 'url-test', 'fallback', 'load-balance',
             'relay', 'ssid', 'smart')
BUILTIN = ('DIRECT', 'REJECT', 'REJECT-TINYGIF', 'PASS')

errors = []


def check_ini():
    groups, rulesets = [], []
    if not os.path.exists(INI_PATH):
        errors.append('missing ' + INI_PATH)
        return groups, rulesets

    for no, line in enumerate(io.open(INI_PATH, encoding='utf-8'), 1):
        s = line.strip()
        if not s or s[0] in ';#':
            continue
        if s.startswith('custom_proxy_group='):
            f = s.split('=', 1)[1].split('`')
            if len(f) < 3:
                errors.append('%s:%d group has <3 fields' % (INI_PATH, no))
                continue
            name, typ = f[0], f[1]
            if typ not in ALL_TYPES:
                errors.append('%s:%d bad type %r (%s)' % (INI_PATH, no, typ, name))
                continue
            if typ in AUTO_TYPES:
                if len(f) < 5:
                    errors.append('%s:%d auto group needs >=5 fields (%s)'
                                  % (INI_PATH, no, name))
                else:
                    if not re.fullmatch(r'\d+(,\d+){0,2}', f[-1]):
                        errors.append('%s:%d bad times %r (%s)'
                                      % (INI_PATH, no, f[-1], name))
                    if not re.match(r'https?://', f[-2]):
                        errors.append('%s:%d bad test url %r (%s)'
                                      % (INI_PATH, no, f[-2], name))
            groups.append((name, typ, f))
        elif s.startswith('ruleset='):
            rulesets.append(s.split('=', 1)[1])
    return groups, rulesets


def check_toml():
    if not os.path.exists(TOML_PATH):
        errors.append('missing ' + TOML_PATH)
        return [], []
    t = tomllib.load(open(TOML_PATH, 'rb'))
    if t.get('version') != 1:
        errors.append('%s: version must be 1' % TOML_PATH)
    groups = [(g.get('name'), g.get('type'), None) for g in t.get('custom_groups', [])]
    for g in t.get('custom_groups', []):
        if g.get('type') in AUTO_TYPES:
            for key in ('url', 'interval'):
                if key not in g:
                    errors.append('%s: group %r missing %s'
                                  % (TOML_PATH, g.get('name'), key))
    rulesets = ['%s,%s' % (r.get('group'), r.get('ruleset'))
                for r in t.get('rulesets', [])]
    return groups, rulesets


def check_refs(groups):
    names = set(g[0] for g in groups)
    for name, typ, f in groups:
        if f is None:
            continue
        for rule in f[2:]:
            if rule.startswith('[]'):
                ref = rule[2:]
                if ref not in names and ref not in BUILTIN:
                    errors.append('group %r references undefined group %r'
                                  % (name, ref))
    return names


def check_rulesets(rulesets, names):
    for r in rulesets:
        parts = r.split(',')
        grp = parts[0]
        if grp not in names:
            errors.append('ruleset points to undefined group %r' % grp)
        if len(parts) >= 2 and not parts[1].startswith('['):
            path = os.path.join(BASE, parts[1])
            if not os.path.exists(path):
                errors.append('missing ruleset file: ' + parts[1])


def check_rule_files():
    for f in RULE_FILES:
        p = os.path.join(BASE, f)
        if not os.path.exists(p):
            errors.append('missing rule file: ' + f)
            continue
        for no, line in enumerate(io.open(p, encoding='utf-8'), 1):
            s = line.strip()
            if not s or s[0] == '#':
                continue
            parts = s.split(',')
            if len(parts) < 2:
                errors.append('%s:%d needs at least "TYPE,value" -> %s'
                              % (f, no, s))


def check_semantics(ini_groups, toml_groups):
    """
    检查两版在语义上是否一致，而不只是组名一致：
      - 每个组的类型相同
      - 规则条目相同（顺序也算，顺序决定 Clash 客户端的可见顺序）
    这是之前真实订阅验证时发现的坑：TOML 把 []🚀 节点选择 放在了正则前面，
    导致兜底项不出现在末尾。只比对组名是发现不了的。
    """
    ini_map = {g[0]: (g[1], g[2]) for g in ini_groups}
    toml_map = {}
    for name, typ, _ in toml_groups:
        toml_map[name] = (typ, _toml_rule_list(name))
    for name in ini_map:
        if name not in toml_map:
            continue
        i_typ, i_fields = ini_map[name]
        t_typ, t_rules = toml_map[name]
        if i_typ != t_typ:
            errors.append('group %r type differs: ini=%s toml=%s'
                          % (name, i_typ, t_typ))
            continue
        if i_fields is None or t_rules is None:
            continue
        # INI 的规则字段是 [2:]，TOML 是 rule 数组
        # 自动组（url-test 等）的 INI 末尾两段是测速 URL 与时间，不算规则
        if i_typ in AUTO_TYPES:
            i_rules = i_fields[2:-2]
        else:
            i_rules = i_fields[2:]
        if i_rules != t_rules:
            errors.append('group %r rules differ:\n      ini =%r\n      toml=%r'
                          % (name, i_rules, t_rules))


_TOML_RULE_INDEX = {}


def _toml_rule_list(name):
    return _TOML_RULE_INDEX.get(name)


def main():
    ini_groups, ini_rulesets = check_ini()
    toml_groups, toml_rulesets = check_toml()

    # 建 TOML 的 rule 索引，供 check_semantics 使用
    if os.path.exists(TOML_PATH):
        t = tomllib.load(open(TOML_PATH, 'rb'))
        for g in t.get('custom_groups', []):
            _TOML_RULE_INDEX[g.get('name')] = list(g.get('rule', []))

    check_refs(ini_groups)
    check_refs(toml_groups)
    check_rulesets(ini_rulesets, check_refs(ini_groups))
    check_rulesets(toml_rulesets, check_refs(toml_groups))
    check_rule_files()
    check_semantics(ini_groups, toml_groups)

    ini_names = [g[0] for g in ini_groups]
    toml_names = [g[0] for g in toml_groups]
    if ini_names != toml_names:
        errors.append('INI/TOML group lists differ: ini-only=%r toml-only=%r'
                      % ([x for x in ini_names if x not in toml_names],
                         [x for x in toml_names if x not in ini_names]))

    print('INI  groups: %d   rulesets: %d' % (len(ini_groups), len(ini_rulesets)))
    print('TOML groups: %d   rulesets: %d' % (len(toml_groups), len(toml_rulesets)))

    if errors:
        print('\nFAILED (%d):' % len(errors))
        for e in errors:
            print('  - ' + e)
        return 1
    print('\nOK: all checks passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
