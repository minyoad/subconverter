#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
校验订阅预取 / Bark 告警这项配置在三个 pref 示例里是否写全、写对：

  1. enable_prefetch / prefetch_interval / prefetch_url / bark_url 四项都存在
  2. prefetch_interval 是正整数
  3. 如果开了 enable_prefetch，就必须能确定要预取的地址：
     prefetch_url 非空，或者 common 里的 default_url 非空
  4. bark_url 形如 https://host/DEVICE_KEY ，不能带结尾斜杠，不能带 /title/body

用法： python scripts/check_prefetch_config.py
"""
import os
import re
import sys
import tomllib

# Windows 控制台默认 GBK，只放宽错误处理、不强制改编码
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, 'reconfigure'):
        _stream.reconfigure(errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
BASE = 'base'

errors = []


def err(msg):
    errors.append(msg)


# --------------------------------------------------------------------------
# 三个格式各自读出 advanced 段
# --------------------------------------------------------------------------
def read_ini():
    path = os.path.join(BASE, 'pref.example.ini')
    section = None
    adv = {}
    multi = {}
    common_default = []
    for no, line in enumerate(open(path, encoding='utf-8'), 1):
        s = line.strip()
        if not s or s[0] in ';#':
            continue
        if s.startswith('[') and s.endswith(']'):
            section = s[1:-1].strip()
            continue
        if '=' not in s:
            continue
        k, v = s.split('=', 1)
        k, v = k.strip(), v.strip()
        if section == 'advanced':
            if k == 'prefetch_url':
                multi.setdefault(k, []).append(v)
            else:
                adv[k] = v
        elif section == 'common' and k == 'default_url' and v:
            common_default.append(v)
    adv['prefetch_url'] = multi.get('prefetch_url', [])
    return adv, '|'.join(common_default)


def read_toml():
    doc = tomllib.load(open(os.path.join(BASE, 'pref.example.toml'), 'rb'))
    adv = doc.get('advanced', {})
    # 允许写成字符串数组，也允许写成单个字符串
    urls = adv.get('prefetch_url', [])
    if isinstance(urls, str):
        urls = [urls]
    adv = dict(adv)
    adv['prefetch_url'] = urls
    default_url = doc.get('common', {}).get('default_url', '')
    if isinstance(default_url, list):
        default_url = '|'.join(default_url)
    return adv, default_url


def read_yaml():
    """只解析 common/advanced 段里的标量与字符串列表，避免依赖 pyyaml。"""
    path = os.path.join(BASE, 'pref.example.yml')
    adv, common = {}, {}
    section = None
    pending_list = None
    for line in open(path, encoding='utf-8'):
        raw = line.rstrip('\n')
        s = raw.strip()
        if not s or s.startswith('#'):
            continue
        indent = len(raw) - len(raw.lstrip())
        if indent == 0 and s.endswith(':'):
            section = s[:-1].strip()
            pending_list = None
            continue
        if section not in ('advanced', 'common'):
            continue
        target = adv if section == 'advanced' else common
        if pending_list and s.startswith('- '):
            pending_list.append(s[2:].strip().strip('"\''))
            continue
        pending_list = None
        if ':' not in s:
            continue
        k, v = s.split(':', 1)
        k, v = k.strip(), v.split('#')[0].strip()
        if v == '' or v == '[]':
            if v == '[]':
                target[k] = []
            else:
                pending_list = target.setdefault(k, [])
            continue
        target[k] = v.strip('"\'')
    default_url = common.get('default_url', '')
    if isinstance(default_url, list):
        default_url = '|'.join(default_url)
    return adv, default_url


# --------------------------------------------------------------------------
def check(name, adv, common_default):
    for key in ('enable_prefetch', 'prefetch_interval', 'prefetch_url', 'bark_url'):
        if key not in adv:
            err('%s: advanced section missing %s' % (name, key))

    enabled = str(adv.get('enable_prefetch', '')).strip().lower() in ('true', '1', 'yes', 'on')

    iv = adv.get('prefetch_interval')
    if iv is not None:
        try:
            iv_int = int(str(iv).strip())
            if iv_int <= 0:
                err('%s: prefetch_interval must be positive, got %s' % (name, iv))
        except ValueError:
            err('%s: prefetch_interval is not an integer: %s' % (name, iv))

    urls = adv.get('prefetch_url') or []
    urls = [u for u in urls if u]
    if enabled and not urls and not common_default:
        err('%s: enable_prefetch=true but neither prefetch_url nor common.default_url is set'
            % name)

    bark = adv.get('bark_url')
    if bark:
        bark = str(bark).strip()
        if not bark.startswith(('http://', 'https://')):
            err('%s: bark_url must start with http(s)://, got %s' % (name, bark))
        if bark.endswith('/'):
            err('%s: bark_url must not end with "/", got %s' % (name, bark))
        # 合法形式是 https://host/DEVICE_KEY，即 host 之后恰好一段路径。
        # 写成 /title/body 时会有两段，这里据此判断。
        path = re.sub(r'^https?://[^/]+', '', bark).strip('/')
        if path and path.count('/') >= 1:
            err('%s: bark_url should stop at the device key (no /title/body), got %s'
                % (name, bark))


def main():
    for name, read in (('pref.example.ini', read_ini),
                       ('pref.example.toml', read_toml),
                       ('pref.example.yml', read_yaml)):
        adv, common_default = read()
        check(name, adv, common_default)

    if errors:
        print('FAILED (%d):' % len(errors))
        for e in errors:
            print('  - ' + e)
        return 1

    print('OK: prefetch / bark settings are present and consistent in all 3 examples')
    return 0


if __name__ == '__main__':
    sys.exit(main())
