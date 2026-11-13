#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
校验 base/config/AI_auto.ini 与 AI_auto.toml 的配置自洽性：

  1. custom_proxy_group 字段数与类型合法（自动组必须 >=5 段）
  2. [] 引用的策略组都存在（含 !!import: / import 展开后的内置组）
  3. ruleset 指向的策略组都存在
  4. ruleset 引用的本地规则文件都存在
  5. 规则文件每行都是 "TYPE,value" 两段
  6. INI 与 TOML 两版「自定义部分」的组名、类型、规则顺序完全一致
     （内置部分不比对：INI 走 snippets/groups.txt，TOML 走
      snippets/groups.toml，这两个仓库自带文件本来就是不同内容）
  7. 三个 pref 示例文件里的 default_external_config 都指向存在的文件

用法： python scripts/check_ai_config.py
"""
import io
import os
import re
import sys
import tomllib

# Windows 控制台默认 GBK，而分流的组名/规则里带 emoji。
# 不处理时，脚本一旦报错又抛 UnicodeEncodeError，真正的问题反而看不到。
# 这里只放宽错误处理、不强制改编码：GBK 终端里中文照常显示，emoji 变成 ?，
# 而 UTF-8 终端（chcp 65001 / Windows Terminal）不受影响。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, 'reconfigure'):
        _stream.reconfigure(errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

BASE = 'base'
INI_PATH = os.path.join(BASE, 'config', 'AI_auto.ini')
TOML_PATH = os.path.join(BASE, 'config', 'AI_auto.toml')
RULE_FILES = ('rules/OpenAI.list', 'rules/Claude.list',
              'rules/Muse.list', 'rules/AI.list')
PREF_FILES = (os.path.join(BASE, 'pref.example.ini'),
              os.path.join(BASE, 'pref.example.toml'),
              os.path.join(BASE, 'pref.example.yml'))

AUTO_TYPES = ('url-test', 'fallback', 'load-balance')
ALL_TYPES = ('select', 'url-test', 'fallback', 'load-balance',
             'relay', 'ssid', 'smart')
BUILTIN = ('DIRECT', 'REJECT', 'REJECT-TINYGIF', 'PASS')

errors = []


# --------------------------------------------------------------------------
# 通用工具
# --------------------------------------------------------------------------
def _import_path(target):
    """把 !!import:xxx 或 import = "xxx" 里的路径解析成 base 下的绝对路径。"""
    return os.path.join(BASE, target)


def _ini_file_items(path):
    """读取一个 INI 片段文件，返回非注释非空行。"""
    out = []
    for no, line in enumerate(io.open(path, encoding='utf-8'), 1):
        s = line.strip()
        if not s or s[0] in ';#':
            continue
        out.append((s, '%s:%d' % (path, no)))
    return out


def _validate_ini_group(value, where):
    """校验单条 INI custom_proxy_group，返回 (name, type, fields) 或 None。"""
    f = value.split('`')
    if len(f) < 3:
        errors.append('%s group has <3 fields' % where)
        return None
    name, typ = f[0], f[1]
    if typ not in ALL_TYPES:
        errors.append('%s bad type %r (%s)' % (where, typ, name))
        return None
    if typ in AUTO_TYPES:
        if len(f) < 5:
            errors.append('%s auto group needs >=5 fields (%s)' % (where, name))
        else:
            if not re.fullmatch(r'\d+(,\d+){0,2}', f[-1]):
                errors.append('%s bad times %r (%s)' % (where, f[-1], name))
            if not re.match(r'https?://', f[-2]):
                errors.append('%s bad test url %r (%s)' % (where, f[-2], name))
    return (name, typ, f)


# --------------------------------------------------------------------------
# INI 解析
# --------------------------------------------------------------------------
def check_ini():
    """返回 (own_groups, imported_groups, own_rulesets, imported_rulesets)。"""
    own_groups, imp_groups = [], []
    own_rulesets, imp_rulesets = [], []
    if not os.path.exists(INI_PATH):
        errors.append('missing ' + INI_PATH)
        return own_groups, imp_groups, own_rulesets, imp_rulesets

    for no, line in enumerate(io.open(INI_PATH, encoding='utf-8'), 1):
        s = line.strip()
        if not s or s[0] in ';#':
            continue
        where = '%s:%d' % (INI_PATH, no)

        if s.startswith('custom_proxy_group='):
            value = s.split('=', 1)[1]
            if value.startswith('!!import:'):
                target = value[len('!!import:'):]
                path = _import_path(target)
                if not os.path.exists(path):
                    errors.append('%s import target not found: %s'
                                  % (where, target))
                    continue
                for item, src in _ini_file_items(path):
                    g = _validate_ini_group(item, src)
                    if g:
                        imp_groups.append(g)
            else:
                g = _validate_ini_group(value, where)
                if g:
                    own_groups.append(g)

        elif s.startswith('ruleset='):
            value = s.split('=', 1)[1]
            if value.startswith('!!import:'):
                target = value[len('!!import:'):]
                path = _import_path(target)
                if not os.path.exists(path):
                    errors.append('%s import target not found: %s'
                                  % (where, target))
                    continue
                for item, _src in _ini_file_items(path):
                    imp_rulesets.append(item)
            else:
                own_rulesets.append(value)

    return own_groups, imp_groups, own_rulesets, imp_rulesets


# --------------------------------------------------------------------------
# TOML 解析
# --------------------------------------------------------------------------
def check_toml():
    """返回 (own_groups, imported_groups, own_rulesets, imported_rulesets)。"""
    own_groups, imp_groups = [], []
    own_rulesets, imp_rulesets = [], []
    if not os.path.exists(TOML_PATH):
        errors.append('missing ' + TOML_PATH)
        return own_groups, imp_groups, own_rulesets, imp_rulesets

    t = tomllib.load(open(TOML_PATH, 'rb'))
    if t.get('version') != 1:
        errors.append('%s: version must be 1' % TOML_PATH)

    for g in t.get('custom_groups', []):
        if 'import' in g:
            target = g['import']
            path = _import_path(target)
            if not os.path.exists(path):
                errors.append('%s import target not found: %s'
                              % (TOML_PATH, target))
                continue
            sub = tomllib.load(open(path, 'rb'))
            for sg in sub.get('custom_groups', []):
                name, typ = sg.get('name'), sg.get('type')
                if typ not in ALL_TYPES:
                    errors.append('%s: bad type %r (%s)' % (path, typ, name))
                    continue
                imp_groups.append((name, typ, None))
        else:
            name, typ = g.get('name'), g.get('type')
            if typ not in ALL_TYPES:
                errors.append('%s: bad type %r (%s)' % (TOML_PATH, typ, name))
                continue
            if typ in AUTO_TYPES:
                for key in ('url', 'interval'):
                    if key not in g:
                        errors.append('%s: group %r missing %s'
                                      % (TOML_PATH, name, key))
            own_groups.append((name, typ, g))

    for r in t.get('rulesets', []):
        if 'import' in r:
            target = r['import']
            path = _import_path(target)
            if not os.path.exists(path):
                errors.append('%s import target not found: %s'
                              % (TOML_PATH, target))
                continue
            sub = tomllib.load(open(path, 'rb'))
            for sr in sub.get('rulesets', []):
                imp_rulesets.append('%s,%s'
                                    % (sr.get('group'), sr.get('ruleset')))
        else:
            own_rulesets.append('%s,%s' % (r.get('group'), r.get('ruleset')))

    return own_groups, imp_groups, own_rulesets, imp_rulesets


# --------------------------------------------------------------------------
# 引用 / 文件 / 语义校验
# --------------------------------------------------------------------------
def check_refs(groups, all_names):
    for name, typ, payload in groups:
        if payload is None:
            continue
        # INI 是字段列表（f[2:] 为规则），TOML 是配置字典（conf['rule']）
        rules = payload.get('rule', []) if isinstance(payload, dict) else payload[2:]
        for rule in rules:
            if rule.startswith('[]'):
                ref = rule[2:]
                if ref not in all_names and ref not in BUILTIN:
                    errors.append('group %r references undefined group %r'
                                  % (name, ref))


def check_rulesets(rulesets, all_names):
    for r in rulesets:
        parts = r.split(',')
        grp = parts[0]
        if grp not in all_names:
            errors.append('ruleset points to undefined group %r' % grp)
        if len(parts) >= 2 and not parts[1].startswith('['):
            path = _import_path(parts[1])
            if not os.path.exists(path):
                errors.append('missing ruleset file: ' + parts[1])


def check_rule_files():
    for f in RULE_FILES:
        p = _import_path(f)
        if not os.path.exists(p):
            errors.append('missing rule file: ' + f)
            continue
        for no, line in enumerate(io.open(p, encoding='utf-8'), 1):
            s = line.strip()
            if not s or s[0] == '#':
                continue
            if len(s.split(',')) < 2:
                errors.append('%s:%d needs at least "TYPE,value" -> %s'
                              % (f, no, s))


def _ini_rules(g):
    name, typ, f = g
    return f[2:-2] if typ in AUTO_TYPES else f[2:]


def _toml_rules(g):
    name, typ, conf = g
    return list(conf.get('rule', [])) if conf else None


def check_semantics(ini_groups, toml_groups):
    """INI 与 TOML 的自定义部分必须逐组等价（含规则顺序）。

    顺序很关键：曾出现 TOML 把 []🚀 节点选择 放在正则前面，
    导致兜底项不在末尾，只比对组名是发现不了的。
    """
    ini_map = {g[0]: g for g in ini_groups}
    toml_map = {g[0]: g for g in toml_groups}

    only_ini = [n for n in ini_map if n not in toml_map]
    only_toml = [n for n in toml_map if n not in ini_map]
    if only_ini or only_toml:
        errors.append('INI/TOML custom groups differ: ini-only=%r toml-only=%r'
                      % (only_ini, only_toml))

    ini_order = [g[0] for g in ini_groups]
    toml_order = [g[0] for g in toml_groups]
    if ini_order != toml_order:
        errors.append('INI/TOML custom group order differs:\n'
                      '      ini =%r\n      toml=%r'
                      % (ini_order, toml_order))

    for name in ini_map:
        if name not in toml_map:
            continue
        i_typ = ini_map[name][1]
        t_typ = toml_map[name][1]
        if i_typ != t_typ:
            errors.append('group %r type differs: ini=%s toml=%s'
                          % (name, i_typ, t_typ))
            continue
        i_rules = _ini_rules(ini_map[name])
        t_rules = _toml_rules(toml_map[name])
        if t_rules is None:
            continue
        if i_rules != t_rules:
            errors.append('group %r rules differ:\n'
                          '      ini =%r\n      toml=%r'
                          % (name, i_rules, t_rules))


def check_snippets():
    """INI 与 TOML 各自 import 的内置片段必须内容等价。

    AI_auto.ini 引入 snippets/*.txt，AI_auto.toml 引入 snippets/*.toml。
    这两套文件由上游分别维护，曾经不同步：.txt 里 NETFLIX、广告拦截、
    运营劫持三个组和 NETFLIX 规则集被注释掉，而 .toml 里是启用的，
    于是「INI/TOML 语义等价」被悄悄破坏（组数 16 vs 19）。
    这里逐个比对，任何一边被注释掉都会被抓出来。
    """
    pairs = (('groups.txt', 'groups.toml'), ('rulesets.txt', 'rulesets.toml'))
    for txt, toml in pairs:
        p_txt, p_toml = _import_path('snippets/' + txt), _import_path('snippets/' + toml)
        if not (os.path.exists(p_txt) and os.path.exists(p_toml)):
            errors.append('missing snippet pair: %s / %s' % (txt, toml))
            continue

        # INI 片段：每行 "name`type`..."，注释行以 ; 开头
        txt_items = [s for s, _ in _ini_file_items(p_txt)]

        # TOML 片段：按行序遍历，保证顺序也一致
        doc = tomllib.load(open(p_toml, 'rb'))
        if txt.startswith('groups'):
            toml_items = doc.get('custom_groups', [])
            txt_keys = [x.split('`')[0] for x in txt_items]
            toml_keys = [g.get('name') for g in toml_items]
        else:
            toml_items = doc.get('rulesets', [])
            txt_keys = [tuple(x.split(',', 1)) for x in txt_items]
            toml_keys = [(r.get('group'), r.get('ruleset')) for r in toml_items]

        if txt_keys != toml_keys:
            only_txt = [k for k in txt_keys if k not in toml_keys]
            only_toml = [k for k in toml_keys if k not in txt_keys]
            errors.append('snippets/%s vs %s differ:\n'
                          '      .txt only =%r\n      .toml only=%r'
                          % (txt, toml, only_txt, only_toml))


def check_default_config():
    """三个 pref 示例文件都应把 default_external_config 指向存在的文件。"""
    for p in PREF_FILES:
        if not os.path.exists(p):
            errors.append('missing ' + p)
            continue
        text = io.open(p, encoding='utf-8', errors='replace').read()

        m = re.search(r'^\s*;?\s*default_external_config\s*[:=]\s*(.+)$',
                      text, re.M)
        if not m:
            errors.append('%s: default_external_config not found' % p)
            continue

        raw = m.group(1).split('#')[0].strip().strip('"\'')
        enabled = not re.match(r'^\s*;', m.group(0)) and bool(raw)
        if not enabled:
            errors.append('%s: default_external_config is disabled/empty' % p)
            continue

        target = _import_path(raw)
        if not os.path.exists(target):
            errors.append('%s: default_external_config points to missing %s'
                          % (p, raw))
        elif not re.search(r'(AI_auto|example_external_config)',
                           os.path.basename(raw)):
            errors.append('%s: default_external_config unexpected target %s'
                          % (p, raw))


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main():
    ini_own, ini_imp, ini_rules, ini_imp_rules = check_ini()
    toml_own, toml_imp, toml_rules, toml_imp_rules = check_toml()

    ini_names = set(g[0] for g in ini_own + ini_imp)
    toml_names = set(g[0] for g in toml_own + toml_imp)

    check_refs(ini_own, ini_names)
    check_refs(ini_imp, ini_names)
    check_refs(toml_own, toml_names)
    check_refs(toml_imp, toml_names)

    check_rulesets(ini_rules, ini_names)
    check_rulesets(ini_imp_rules, ini_names)
    check_rulesets(toml_rules, toml_names)
    check_rulesets(toml_imp_rules, toml_names)

    check_rule_files()
    check_snippets()
    check_semantics(ini_own, toml_own)
    check_default_config()

    print('INI  custom=%d  imported=%d  rulesets=%d(+%d imported)'
          % (len(ini_own), len(ini_imp), len(ini_rules), len(ini_imp_rules)))
    print('TOML custom=%d  imported=%d  rulesets=%d(+%d imported)'
          % (len(toml_own), len(toml_imp), len(toml_rules), len(toml_imp_rules)))

    if errors:
        print('\nFAILED (%d):' % len(errors))
        for e in errors:
            print('  - ' + e)
        return 1
    print('\nOK: all checks passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
