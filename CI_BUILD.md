# 用 GitHub Actions 编译 Docker 镜像

本仓库已配置好 CI，push 到 `master` 即自动编译并推送到 **GitHub Container Registry (ghcr.io)**。

---

## 一、为什么必须自己编译

上游官方镜像 `ghcr.io/tindy2013/subconverter` **不含 VLESS 协议支持**。

VLESS/Reality 能力来自本 fork 的提交 `096a0aa`，见 `src/generator/config/subexport.cpp:1289`：

```cpp
case ProxyType::VLESS:
    continue; // VLESS only exported for Clash/Clash.Meta
```

所以官方镜像拿到你的 Reality 节点会直接丢弃。必须用本仓库代码编译。

---

## 二、CI 做什么

`.github/workflows/build.yml` 里的 `docker` job：

1. **Checkout** 本仓库代码
2. **构建**（`scripts/Dockerfile.ci`，本地代码构建，非 clone 上游）
3. **冒烟测试** —— 用虚构节点实际跑一遍，断言输出含 `reality-opts` / `public-key` / `xtls-rprx-vision`
4. 测试通过后才 **推送** 到 `ghcr.io/<你的用户名>/subconverter`
5. **清理** 测试容器

> 冒烟测试是硬性门禁：如果哪天 VLESS 支持被误删，CI 会直接失败，不会推送坏镜像。

### 另一个 workflow 已停用

`.github/workflows/docker.yml`（上游的 "Publish Docker Image"）已停用，两个 job 都是 `if: false`。原因：

1. 它写死推送 `tindy2013/subconverter` —— 上游仓库，本 fork 无权限，必然失败
2. 它用 `scripts/Dockerfile:38` 的 `git clone tindy2013/subconverter` —— 编出来是**上游代码**，不含 VLESS/Reality 支持

保留文件（不删），但不会自动运行，手动触发也不会跑。

---

## 三、如何使用

### 1. push 触发

```bash
git add .
git commit -m "ci: build docker image"
git push origin master
```

> 也可以手动触发：仓库页面 → Actions → GitHub CI → Run workflow

### 2. 等待构建

Actions 页面观察。首次约 **25–35 分钟**（要编译 quickjs / libcron / toml11 / subconverter），
之后有 GHA 缓存会快很多。

### 3. 拉取镜像

镜像地址取决于 `github.repository`：

```
ghcr.io/minyoad/subconverter:latest        # master 分支最新
ghcr.io/minyoad/subconverter:master
ghcr.io/minyoad/subconverter:sha-abc1234   # 按 commit
```

**注意**：即使仓库是公开的，ghcr 的包默认是 **private**。

拉取前需要登录（用 GitHub Personal Access Token，勾选 `read:packages`）：

```bash
echo $GHCR_TOKEN | docker login ghcr.io -u <你的GitHub用户名> --password-stdin
```

或把包改成 public：
仓库页 → Packages → 选中 subconverter → Package settings → Change visibility → Public

无登录拉取会报：

```
Error response from daemon: denied: denied
```

### 4. 运行

**必须挂载 `base/` 目录**（至少包含 `pref.ini` 和 `nodes.txt`）。
镜像里刻意不含这两个文件（`.dockerignore` 排除了它们），
因为它们是真实凭据，不能进公开镜像。

```bash
docker run -d --name subconverter \
  -p 25500:25500 \
  -v $PWD/base:/base \
  --restart unless-stopped \
  ghcr.io/minyoad/subconverter:latest
```

`base/` 里需要：

```
base/pref.ini     ← 必须有，listen=0.0.0.0
base/nodes.txt    ← 必须有，单行 base64
base/config/      ← 用镜像自带的也行；挂载整个目录时会覆盖
base/rules/       ← 同上
```

> 如果不想覆盖镜像自带的 config/rules，可以只挂两个文件：
>
> ```bash
> -v $PWD/base/pref.ini:/base/pref.ini:ro \
> -v $PWD/base/nodes.txt:/base/nodes.txt:ro
> ```

访问：

```
http://127.0.0.1:25500/sub?target=clash
```

---

## 四、⚠ 运行前必须做两件事

### 1. 准备你自己的 `base/pref.ini` 和 `base/nodes.txt`

仓库里**不含**真实配置（已在 `.gitignore` 里排除），镜像内用的是
`pref.example.ini` 的默认值。你需要自己挂载。

从示例开始：

```bash
cp base/nodes.txt.example base/nodes.txt
cp base/pref.example.ini base/pref.ini
```

然后改 `base/nodes.txt`：

```bash
printf '%s' '你的订阅明文' | base64 -w 0 > base/nodes.txt
```

必须是**单行 base64、末尾无换行**（原因见 `base/nodes.txt.example` 里的说明）。

### 2. `pref.ini` 里 `listen` 必须是 `0.0.0.0`

```ini
[server]
listen=0.0.0.0
port=25500
```

写 `127.0.0.1` 会导致「容器内自测 200，宿主机 curl 却是 000」。

原因：Docker 端口转发是从网关 `172.17.0.1` 进入容器，`127.0.0.1`
只接受容器自身回环，内核直接拒绝。

---

## 五、常见问题

### Q: 构建失败在 `git clone` / `git submodule`

有两个不同的原因，症状不同：

**(1) 子模块 `Catch2` 克隆中断（已修复）**

错误特征：

```
error: 7840 bytes of body are still expected
fetch-pack: unexpected disconnect while reading sideband packet
fatal: early EOF
fatal: clone of 'https://github.com/catchorg/Catch2.git' into submodule path
       '/libcron/test/externals/Catch2' failed
```

原因：`libcron` 有两个子模块，`git submodule update --init` 会**全拉**：

| 子模块 | 是否必需 | 大小 |
|---|---|---|
| `libcron/externals/date` | ✅ 编译必需 | 小 |
| `test/externals/Catch2` | ❌ 只是单元测试 | 大，易断流 |

现在 `scripts/Dockerfile.ci` 已改成只拉必需的那个：

```dockerfile
git submodule update --init --depth=1 libcron/externals/date
```

如果你从旧版本迁移过来，确认这行带上了具体路径。

**(2) 网络问题（仅本地）**

如果错误是 `SSL_ERROR_SYSCALL` / 证书校验失败，见下面那条 FAQ。

### Q: 构建很慢

主要耗时在编译 quickjs 和 subconverter 本身。GHA 有 `cache-from: type=gha`，
第二次会快很多。

### Q: 想同时要 arm64

把 workflow 里两处改掉：

```yaml
platforms: linux/amd64,linux/arm64
load: false      # 多平台不能 load
```

并删掉「Smoke test」和「Push image」步骤，把 `Build` 步骤改回 `push: true`。
代价是 QEMU 模拟编译明显更慢。

### Q: 本地验证构建时报 `git clone` 失败（exit code 128）

这是本地网络问题，不是 Dockerfile 的问题。症状：

```
容器内能解析 github.com，但 https 连接被重置 / 证书校验失败
```

原因：本机的 GitHub 访问走代理（如 `127.0.0.1:10809`），而容器内的
`127.0.0.1` 指容器自己，且默认 bridge 网络访问不到宿主机代理。

解决办法：用 `--network host` 让构建容器共享宿主机网络，并显式传代理：

```bash
docker build --network host \
  --build-arg HTTP_PROXY=http://127.0.0.1:10809 \
  --build-arg HTTPS_PROXY=http://127.0.0.1:10809 \
  --build-arg http_proxy=http://127.0.0.1:10809 \
  --build-arg https_proxy=http://127.0.0.1:10809 \
  --build-arg GIT_SSL_NO_VERIFY=true \
  -f scripts/Dockerfile.ci -t sc-ci-test:latest .
```

**GitHub Actions 上不需要这些参数** —— runner 直连 GitHub，Dockerfile 保持原样即可。

如果代理端口不同，换成你自己的；用 `env | grep -i proxy` 查看 WSL 里的实际值。

### Q: 日志里一堆 `toml::parse_*` 报错

正常。那是「先试 TOML、失败回退 INI」的流程噪声，
看到 `Load preference settings in INI format completed.` 就说明成功。

---

## 六、⚠ 服务端版本约束

服务器 Xray **必须固定在 26.6.27**，不要升级到 26.7.11 及以上。

Xray 从 26.7.11 起给 REALITY 加了 `minClientVer` 校验（默认 26.3.27），
而 mihomo 把客户端版本硬编码成 `1.8.2`，会被拒绝，表现为：

```
connect error: REALITY authentication failed
```

相关 issue：`MetaCubeX/mihomo#3039`、`XTLS/Xray-core#6477`

实测**无效**的规避手段：服务端加 `minClientVer`、客户端加
`support-x25519mlkem768: true`、去掉 `flow`。

唯一有效方案：服务端用 26.6.27。
