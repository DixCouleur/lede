# Redmi AX6000 精简固件 + OpenClash + AdGuard Home + MosDNS + Turbo ACC

适配 `xiaomi,redmi-router-ax6000`、`mediatek/filogic`，Linux 6.12.112。
采用现有 LEDE 分区：BL2 1 MiB、Nvram/Bdata 各 256 KiB、Factory/FIP 各 2 MiB、
crash/crash_log 各 256 KiB、ubi 110 MiB（起始地址 0x600000）。

保留双频 Wi-Fi 6、DHCP/DNS、IPv4、PPPoE、firewall3/iptables、SSH、opkg、
简体中文 LuCI-light/Argon 3.1.0 r1（默认主题），以及 OpenClash 0.48.002、Mihomo 1.19.33 ARM64 和 AdGuard Home 0.107.79、MosDNS 5.3.4。
内置 Turbo ACC 中文面板、FW3 Flow Offloading 和 BBR 模块。
内核保留必要的 IPv6 依赖，默认禁用 IPv6 地址、路由、DHCPv6 和 RA。
内置 Argon 主题设置页及简体中文翻译；Bootstrap 作为 luci-light 的依赖保留。
OpenClash 的依赖保留，面板仅内置 Zashboard，GeoSite 按实际引用裁剪；DDNS、UPnP、
FTP、流量统计、定时重启和跑分工具移除。

## 2026-10-24 上游同步与构建准备

当前构建输入更新为 LEDE `cbe28467`、LuCI `c80fbecc`、packages `0ede3e22`、
helloworld `9213963c`；相比 10 月 22 日的准备版本分别新增 3、5、4、8 个提交。
routing、telephony 和订阅模板没有新增提交；AX6000 内核仍为 Linux 6.12.112。

Mihomo 更新到官方稳定版 1.19.33，包含 DNS 查询取消后限制 DoH 连接继续拨号、
重载时保留 Fake-IP 地址池分配状态等上游修复。ARM64 核心归档和解压后的 ELF
均固定 SHA-256。packages 与 helloworld 新增的 AN7581 EIP93 加速不适用于
AX6000 的 MT7986，继续排除发行源中的 Mihomo/Xray 包。

Argon 更新到官方 3.1.0，使用本地修订 r1，保留颜色值完整字符串校验补丁。
主题增加主动检查与安装稳定版更新的面板，补齐 `flock`、`coreutils` 和
`coreutils-timeout` 依赖；进入设置页不会自动检查或安装更新。设置、中文翻译、
空兼容包和升级保留清单继续使用上游实现。OpenClash 0.48.002、AdGuard Home
0.107.79、MosDNS 5.3.4 和 Zashboard 3.29.1 的最新稳定版本未变。

GeoSite 更新到 `202610222206`，由 11,381,894 字节裁剪为 2,698,402 字节，
保留同样的 10 类及完整条目字节。Country lite 固定到 `fa049a8d`，国内 IPv4/IPv6
网段刷新到本次快照；Telegram 网段摘要及 Go 1.27.3 引导工具版本未变。
LuCI 新变更主要涉及 MT7621 硬件卸载和交换机状态查询，不能据此推断 AX6000
转发性能提高。现有 DNS 结构、IPv4 运行策略、双频默认开启等设置保持原样。

隔离准备及 238 个所选软件包的依赖检查通过；Argon 的 66 项界面/模板检查与
21 项更新 RPC 隔离测试、LuCI 状态页 3 项回归通过。189 个 Argon 运行源文件
与已打补丁的官方源码一致，JavaScript 压缩和中文翻译编译通过。Mihomo 1.19.33
的两种 GeoSite 加载器、订阅模板及 AdGuard Home 本机 DNS 联调通过；这些检查
不代表新镜像或路由器长期运行已验收。

隔离准备目录为 `.build-ax6000/mount/lede-20261024-upstream`，上游记录、输入备份、
资源摘要和检查日志位于 `artifacts/ax6000/upstream-20261024/`。
本次只同步和验证构建输入，尚未编译新镜像、刷写或修改路由器；
`artifacts/ax6000/latest` 仍指向已交付的 `releases/20261016-upstream`。

## 2026-10-22 上游同步与构建准备

当前构建输入锁定为 LEDE `b941247a`、LuCI `52fe2099`、packages `ae3a5551`、
helloworld `4e4dee0c`；routing 和 telephony 没有新增提交。AX6000 继续使用
合并 UBI 目标和 Linux 6.12.112。

Argon 更新到 3.0.0，本地修订 r3 基于官方 r2，补上颜色值的完整字符串校验。
上游原校验会接受换行后的额外内容，本机与路由器只读验证均已复现并确认修复。
主题内置设置页、中文翻译及配置迁移逻辑，原来的
`luci-app-argon-config` 改为上游提供的空兼容包，并补上 `ucode-mod-math` 依赖。
主题自己的 sysupgrade 保留清单覆盖自定义背景与图标。若在旧固件上手动安装
Argon 3 的 IPK，按上游顺序先单独安装空兼容包，再安装主题。
OpenClash、Mihomo、AdGuard Home、MosDNS、Zashboard 的最新稳定版本未变化。

LuCI 首页改为分别加载无线和其他状态卡片，避免慢无线查询阻塞首屏与后续刷新；
首页存储查询只统计根目录与 overlay，减少外接存储首次扫描带来的等待。
LEDE 的 mac80211 软件包修订号从 3 更新到 5，变更主要修复 Broadcom 构建与查询，
MT76 驱动源码没有变化。未选用的 PON、SSR Plus 和 Xray 组件继续排除。

GeoSite 更新到 `202610202206`，由 11,338,645 字节裁剪为 2,697,333 字节，
继续保留原来的 10 类及完整条目字节。Country lite 固定到 `37e41234`，国内
IPv4/IPv6 网段刷新到本次快照，Telegram 网段摘要未变化。构建引导工具更新到
官方 Go 1.27.3；脚本按锁定版本安装并检查隔离缓存内的引导工具版本。

Argon 的 43 项上游运行逻辑与模板回归、LuCI 状态页的 3 项上游回归，以及新版
GeoSite 与路由器订阅模板的 Mihomo 1.19.32 本机校验已通过。Argon 补丁摘要
固定在版本锁中，重建时会应用到官方源码，验收镜像时也会重放补丁并逐文件核对。

隔离准备目录为 `.build-ax6000/mount/lede-20261022-upstream`，上游提交、下载摘要、
原始构建输入备份及检查记录位于 `artifacts/ax6000/upstream-20261022/`。
本次完成源码与构建配置准备，尚未编译新的固件镜像；最新可用镜像仍为
`artifacts/ax6000/releases/20261016-upstream/`，`latest` 入口保持指向该批已验收固件。

## 2026-10-16 上游更新构建

版本锁定为 LEDE `30169012`、LuCI `7607a48f`、packages `3ba0aeef`、
helloworld `1f0849ec`；内核继续使用 6.12.112，设备目标继续使用合并 UBI 的
`xiaomi_redmi-router-ax6000`。新增的原厂分区设备目标不用于这台路由器。

OpenClash 更新到 0.48.002，Argon 更新到官方 2.4.8 r2 源码；Mihomo、
AdGuard Home、MosDNS 和 Zashboard 的正式版本保持不变。补丁 011、014、022
已适配新的配置转换、核心版本缓存及延后重启流程；补丁 023 拒绝空订阅、
节点大幅缩水及多数自动组丢失节点的更新，保留现有配置。

GeoSite 更新到 `202610152206`，继续保留原来的 10 类，完整条目字节不作改写，
由 11,197,777 字节裁剪为 2,697,426 字节。Country lite 更新到固定提交
`18568197`，国内网段刷新到本次快照，Telegram 网段摘要未变化。

隔离构建目录为 `.build-ax6000/mount/lede-20261016-upstream`，产物目录为
`artifacts/ax6000/releases/20261016-upstream/`。版本、完整 SHA-256 及资源地址
由版本锁和产物中的清单记录；镜像验收结果以本次 `verification.txt` 为准。
单核心验证、DNS 就绪检查、IPv4 DNS 分流、两频 Wi-Fi 默认开启及 LuCI 面板均保留。

本次已完成构建和镜像验收。最终镜像 50,688,818 字节（48.34 MiB），预装 236 个包。
内核载荷 4,923,128 字节，SquashFS 45,757,440 字节；110 MiB UBI 分区剩余约
60.00 MiB 原始擦除块空间，实际 overlay 可用容量仍需扣除元数据和坏块预留。

```text
SHA256: 5cc7b0397a74a680f96c1413e874b803cf853fb4886d8a72f9018cb04d515296
```

镜像结构、内置默认配置、核心和面板资源，以及 234 个可下载包的索引签名、哈希与
内核 ABI 均验收通过。本机 DNS、MosDNS、AdGuard Web、订阅完整性、OpenClash
生命周期、分流及 GeoSite 回归检查通过；`artifacts/ax6000/latest` 指向本次目录。
没有刷写路由器，首次启动、LED、无线连接和升级后的长期运行尚未实机验收。

## 2026-10-06 上游更新构建记录

版本锁定为 LEDE `88f08888`、LuCI `2fa3f68a`、packages `51c86b49`、
helloworld `c39f1e35`；routing 和 telephony 上游没有新提交。
Linux 更新为 6.12.112，Mihomo 使用官方正式版 1.19.32，Zashboard 使用官方正式版
3.29.1 的 CDN 字体资源归档。OpenClash、AdGuard Home、MosDNS、Argon 仍为最新正式版。

GeoSite 使用 Loyalsoldier `202610052207` 发布数据，保留同样的 10 类，
由 11,022,015 字节裁剪为 2,709,483 字节。Country.mmdb 使用固定提交的 lite
数据，266,001 字节；国内 IPv4/IPv6 网段刷新到本次快照。所有下载的版本、地址和
SHA-256 都保存在 `configs/redmi-ax6000-build.lock.json`，源归档随产物交付。
显式关闭新版 LEDE 新增的 nftables、BPF 调度和虚拟网卡默认包，继续使用 FW3。
新 LuCI 必需的 `kmod-nf-conntrack-netlink` 保留。

新的隔离目录为 `.build-ax6000/mount/lede-20261006-upstream`，产物目录为
`artifacts/ax6000/releases/20261006-upstream/`；旧镜像和旧构建目录保留。
DNS 就绪检查、OpenClash 单核心校验、DIRECT 节点引导 DNS 修复和异常退出日志留存
均保留并纳入镜像验证。补丁 021 解决 macOS 并行编译 CMake 时 util-linux UUID
头文件与 Apple SDK 的类型冲突，仅作用于主机构建工具。
以下旧交付记录只对应其注明的历史镜像。

2026-10-06 已完成构建及验证。最终镜像 50,524,978 字节（48.18 MiB），
预装 236 个包，相比 2026-10-01 镜像更新 84 个包的版本，并新增新 LuCI 必需的
`kmod-nf-conntrack-netlink`。内核载荷 4,911,332 字节，SquashFS 45,601,792 字节，
110 MiB UBI 分区剩余约 60.12 MiB 原始擦除块空间；实际 overlay 容量需扣除
UBI/UBIFS 元数据和坏块预留，尚未通过刷机实测。

```text
SHA256: ce616191d11708b12657f4a936e45da375b4555b4f8602403f324078d3c00775
```

镜像结构、默认配置、官方核心/面板资源、裁剪数据及 234 个可下载包的索引签名、
哈希和内核 ABI 检查通过；确认 SquashFS 没有残留被排除组件的程序、库或模块。
本机 DNS、MosDNS、AdGuard Web、订阅配置、GeoSite、OpenClash 生命周期、分流及
WED 检查通过。现有 AX6000 上的 `sysupgrade -T` 返回 0，设备端镜像哈希一致。
未刷写此镜像，首次启动、LED、无线连接及升级后的长期运行尚未验收。
当次完成交付时，`artifacts/ax6000/latest` 指向这一批目录。

## 2026-10-01 交付记录

以下信息对应 2026-10-01 本次重新构建的镜像，包含补丁 001–019，
以及已在当前路由器验收的 AdGuard Home → MosDNS → 选择性 Fake-IP 链路，MosDNS 同时查询阿里两个 H3 地址和 DNSPod UDP。
使用现成的中文 `luci-app-mosdns` 1.7.14，未另建 LuCI 面板。
MosDNS 已清理空黑名单插件及拒绝规则，明确关闭广告订阅，并补上 Mihomo DNS
`SERVFAIL` 应答的即时回退；无响应回退缩为 500 ms，分流脚本兼容原生、混合和 TUN 模式。
Mihomo 默认使用 warning 日志并关闭纯 IP 强制嗅探；广告过滤继续由 AdGuard Home 负责。
未知域名复用真实解析缓存，开启一天的乐观缓存；Fake-IP 仍每次向本机 Mihomo 获取。

2026-10-01 在 macOS ARM64 上完成单任务重建，生成且仅生成 AX6000 升级镜像。
镜像大小 49,060,658 字节（46.79 MiB），预装 235 个软件包。
Linux 版本为 6.12.111，OpenClash 为 0.47.156，Mihomo 为 1.19.31，
AdGuard Home 为 0.107.79，使用 rufengsuixing 的 LuCI 插件 1.8-12；Argon 为 2.4.7。
AdGuard Home 原生 Web 管理页默认监听 `0.0.0.0:3000`，可从局域网直接访问。
默认启用 WED 的驱动开机参数，Turbo ACC 的 WED 开关保存下一次启动设置；
OpenClash 导入配置后强制使用 `find-process-mode: off`，避免路由器上的进程匹配。
默认启用 TCP 并发和统一延迟，日志级别为 `warning`，GEO 加载器为 `memconservative`；
自动选择组使用 600 秒惰性测速与 100 ms 切换容差。
2.4 GHz 和 5 GHz Wi-Fi 默认开启，初始化时启用全部无线设备。
删除 MetaCubeXD，默认面板改为 Zashboard；GeoSite 从 1508 类裁剪为 10 类，
由 10,407,328 字节降到 2,722,115 字节。固件与 OpenClash IPK 使用相同裁剪数据。

```text
SHA256: f4f3a74bf075caecfa40dce925e5653364a5bb9eaf1d8ffc974370befb15993d
```

内核载荷 4,488,452 字节，SquashFS 44,562,432 字节。按 NAND 擦除块粒度计算，
110 MiB UBI 分区在分配这两个卷后剩余约 61.62 MiB 原始空间。加入 MosDNS 后
SquashFS 相比上一份镜像增加 5 MiB；没有安装完整 v2ray GeoIP/GeoSite 数据包。
可写空间还需扣除 UBI/UBIFS 元数据与坏块预留，刷入后的容量以 `df -h /overlay` 为准。
当前路由器以 IPK 安装 MosDNS 后 overlay 可用约 31.64 MiB，不能作为新镜像的 overlay 容量。

已通过设备元数据、镜像结构、必需及排除的软件包、Mihomo 归档和固件内核心校验、
执行权限、Argon 默认主题及中文翻译、AdGuard Home 程序/面板/启动设置、
DHCPv4/v6 接管、DNS API 切换与 OpenClash 覆写脚本、禁用进程匹配和 Mihomo/测速默认设置、
MetaCubeXD 移除与 Zashboard 默认面板、固件/IPK 中裁剪 GeoSite 的哈希和类别、
双频 Wi-Fi 默认开启与生成 AP 接口启用设置、
Turbo ACC 中文面板/模块/默认设置、WED 开机参数与持久化开关、初始设置、opkg 数据，以及 233 个可下载包的索引签名、IPK 哈希和内核
ABI 检查。`kernel` 和 `libc` 由固件预装，仓库默认不将它们列入可下载索引。
当前路由器已完成相同链路的 DNS、代理 HTTPS、LuCI 页面/RPC、核心启停回退、
防火墙重载与双频 Wi-Fi 状态检查；没有刷写此新镜像，首次启动、LED 与长期运行仍未验收。

## 构建

### GitHub Actions 每日构建

仓库 [DixCouleur/lede](https://github.com/DixCouleur/lede) 的
[AX6000 Daily Firmware](https://github.com/DixCouleur/lede/actions/workflows/openwrt-ci.yml)
每天北京时间 04:30（UTC 20:30）从默认 `master` 分支构建，也支持手动运行。
相关配置或构建脚本推送到 `master` 时同样触发。每日任务使用提交在仓库中的
版本锁；不会自动将源码、插件或公共 DNS 数据切换到未验证的新版本。

任务在 Ubuntu 24.04 x86_64 上准备锁定源码，运行 DNS、订阅完整性、OpenClash
生命周期、分流、LuCI 状态等本机检查，再下载源码、编译镜像并验证镜像和签名索引。
只有全部通过才上传固件和匹配的 opkg 仓库；日志始终保留，产物保留 3 天。
在 Actions 对应运行的 Artifacts 中下载 `AX6000-...`，解压后用 `SHA256SUMS` 核对
固件；`github-build.json` 记录构建提交与运行编号。任务不连接或刷写路由器。

Actions 缓存源码下载和 ccache，不复用旧 rootfs、旧镜像或软件包 staging 目录。
国内网段和 Telegram 网段的原始 URL 会变化，因此对应锁定快照随仓库提交，
全新构建优先使用这些快照并核对摘要，不依赖某一次 Actions 的缓存。
Go bootstrap 与本机测试用的 Mihomo、AdGuard Home 按 Linux 平台单独固定摘要。
Linux 不应用仅供 macOS 主机构建的 001–004、007、021 补丁；导出产物中的
`build-patches/receipt.json` 记录实际应用与跳过的补丁及摘要。

### 本机构建

在 macOS 上，安装本仓库 README 中列出的构建依赖、GNU make >= 4.1、`gpatch`，
并准备 `python3.11`（也可由已安装的 uv 提供）。构建脚本不更改 shell 配置。
新增的 GNU patch 依赖可通过 `brew install gpatch` 安装。

```sh
rtk proxy bash scripts/build-redmi-ax6000.sh all
```

macOS 上脚本创建项目内的 64 GiB 区分大小写 APFS sparsebundle，按版本锁定文件导出源码和
feeds，不更新当前 checkout。下载使用 8 并发，编译默认使用 4 个任务，可通过
`AX6000_JOBS=1` 降低并发。首次构建耗时取决于
主机和网络。构建目录和缓存保留，可通过 `prepare`、`download`、`packages`、`build`、`index`、`verify`
分别重跑阶段；`index` 只重建软件包索引并导出，不重新编译镜像。日志位于当前版本产物目录的 `logs/`。

产物目录包含固件、SHA256SUMS、full.config、diffconfig.config、软件包 manifest、
profiles.json、构建版本信息及 verification.txt。`config.seed` 为可复用的原始精简配置。
`packages/` 保存本次编译的 IPK，可用于安装或重装与这份固件匹配的软件包。
`opkg-repository/` 保留分组软件源、签名索引及公钥，可提供给 opkg 解析依赖。
`build-patches/` 保存主机兼容修复、OpenClash DNS 配合及单一 AdGuard Home 服务补丁；
`image-files/` 保存默认 AdGuard Home 配置、OpenClash 配置覆写脚本及 WED 开机配置/开关辅助脚本。
`source-archives/` 保存校验过的 Argon 与 rufengsuixing AdGuard Home 插件源码压缩包；其网址与 SHA-256 固定在
`build.lock.json` 中，构建时只会使用这一版本。
Apple Silicon 的 Go 1.27.3 官方 bootstrap 由脚本下载、校验并放在构建磁盘内，
只在脚本进程中加入 PATH，不修改系统 Go 或 shell 配置。

2026-09-30 核对上游：LEDE 主仓库和 packages、routing、telephony、helloworld 四个 feed
的 HEAD 与本次锁定提交相同。LuCI feed 的 HEAD 比锁定提交前进两个提交，涉及 Passwall、
流量统计与状态页；本次保留已验证的 LuCI 基线，并单独引入
[Argon 2.4.7 官方发布版](https://github.com/jerrykuku/luci-theme-argon/releases/tag/v2.4.7)。
[OpenClash 0.47.156](https://github.com/vernesong/OpenClash/releases/tag/v0.47.156)、
[Mihomo 1.19.31](https://github.com/MetaCubeX/mihomo/releases/tag/v1.19.31) 和
[AdGuard Home 0.107.79](https://github.com/AdguardTeam/AdGuardHome/releases/tag/v0.107.79)
为核对时各项目的最新稳定发布版。并未逐一确认全部预装依赖包在各自上游的最新版；
它们按上述锁定仓库构建，版本以软件包清单为准。

## 可写空间与后续安装

### 面板与 GeoSite 裁剪

内置面板只保留 Zashboard，移除 MetaCubeXD 的 3.22 MiB 未压缩资源。
GeoSite 保留 `apple`、`apple-cn`、`category-games`、`category-public-tracker`、`cn`、
`geolocation-!cn`、`gfw`、`google`、`google-cn` 和 `private`，覆盖 2026-09-30 只读核对
现用订阅中的三类规则，以及 OpenClash 自定义规则/DNS/fake-IP 清单的类别引用。
`category-games@cn` 所需属性完整保留。裁剪程序只复制完整 protobuf 类别条目，
不修改域名、正则或属性；原始数据来自版本锁定文件中指定的 Loyalsoldier 完整发布数据。
广告过滤由 AdGuard Home 负责，未保留 GeoSite 的 `category-ads-all`。

`configs/ax6000/geosite-keep.json` 记录类别和完整/裁剪数据的 SHA256；
交付中的 `geosite-manifest.json` 记录每类大小与 SHA256，`geosite-keep.json`、
`ax6000_geosite.py` 和 `image-files/etc/openclash/GeoSite.dat` 可用于复现和核对。
若新订阅引用这些类别之外的 GeoSite，应先扩展白名单、重新计算裁剪 SHA256 并重建，
或者手动换回完整数据。全新配置关闭 OpenClash 的 GeoSite 自动更新，导入覆写也关闭
Mihomo 的 `geo-auto-update`，避免自动下载完整数据占用 overlay。LuCI 手动 GEO 更新
和手动安装其他面板仍可用，但会增加可写层占用；保留旧配置刷机时须检查旧的更新
开关和默认面板设置。

同版官方 macOS ARM64 Mihomo 对两种 GEO 加载器的本机测试记录在
`logs/geosite-host-test.log`，检查全部保留类别及 `category-games@cn`，并逐字节确认
条目与完整数据一致。可在源码目录复现：

```sh
rtk proxy python3 scripts/ax6000_geosite.py test \
  .build-ax6000/geosite-202610052207.dat \
  artifacts/ax6000/releases/20261006-upstream/image-files/etc/openclash/GeoSite.dat /path/to/mihomo
```

### 后装插件

AX6000 的 UBI 分区固定为 110 MiB。升级程序只为内核与 SquashFS 分配实际所需的卷，
`rootfs_data` 默认使用全部剩余空间，挂载为 `/overlay`；此镜像没有设置固定的小容量
可写分区。最终可用空间还要扣除 UBI/UBIFS 元数据及坏块预留，以实机结果为准：

```sh
df -h /overlay
fw_printenv -n rootfs_data_max
```

第二条命令用于只读检查已有引导环境是否限制了 `rootfs_data`；变量未设置时走最大
剩余空间分配。构建与本次交付不会修改引导环境。

后装插件使用 opkg，安装占用不能只按 IPK 压缩包大小估算。交付的 `packages/`
包含与本次固件匹配的包，复制到路由器 `/tmp` 后可用 `opkg install /tmp/包名.ipk`
安装。软件源中的内核模块须同时匹配本次 6.12.112 内核及其 ABI；需要新增
内核模块时应使用同一份锁定源码和配置编译，不能强制忽略内核依赖。
增加之前未启用的内核模块会改变内核配置，可能需要同时重建并升级对应固件；
纯用户空间插件通常不需要这一步。

镜像沿用仓库的默认在线软件源地址。自编译的包版本及内核 ABI 不一定与这些源
一致；优先使用交付的软件源。该软件源只含本次实际编译的包，需要的其他插件
应在锁定构建目录中增加选择并重新编译后，再加入软件源。

例如，在电脑上从 `artifacts/ax6000/releases/20261006-upstream/opkg-repository/` 启动 HTTP 服务：

```sh
python3 -m http.server 8000 --bind 0.0.0.0
```

在路由器上，先备份 `/etc/opkg/distfeeds.conf`，再将软件源改为下列地址。
把 `电脑的局域网IP` 替换为实际地址；公钥已内置在同一次构建的固件中。

```text
src/gz ax6000_core http://电脑的局域网IP:8000/targets/mediatek/filogic/packages
src/gz ax6000_base http://电脑的局域网IP:8000/packages/aarch64_cortex-a53/base
src/gz ax6000_luci http://电脑的局域网IP:8000/packages/aarch64_cortex-a53/luci
src/gz ax6000_packages http://电脑的局域网IP:8000/packages/aarch64_cortex-a53/packages
```

随后运行 `opkg update`，再用 `opkg install 插件包名` 安装软件源中已有的包。

需要为后装插件生成匹配的 IPK 时，可在电脑上运行以下命令，将示例包名替换为
锁定 feeds 中的实际包名：

```sh
rtk proxy bash scripts/build-redmi-ax6000.sh menuconfig luci-app-xxx
rtk proxy bash scripts/build-redmi-ax6000.sh download
rtk proxy bash scripts/build-redmi-ax6000.sh build
```

在 menuconfig 中将新增插件选为 `M`，这样只生成 IPK，不预装进固件。脚本安装
指定 feed 包及其依赖，但不会更新 feeds。此流程保留现有配置；不要运行 `all`
或 `prepare`，这两个阶段会重新载入初始精简配置。新增包和索引会重新导出。

## 刷机前只读兼容性检查

本次构建不执行刷机。将固件复制到路由器 `/tmp/` 后，可检查：

```sh
cd /tmp
sha256sum lede-redmi-ax6000-minimal-openclash-sysupgrade.bin
sysupgrade -T /tmp/lede-redmi-ax6000-minimal-openclash-sysupgrade.bin
```

校验值应与交付的 SHA256SUMS 一致，`sysupgrade -T` 应退出成功。
这是升级镜像，适配上述合并 UBI 布局；不是原厂网页首次安装镜像。

## AdGuard Home、MosDNS 与 OpenClash

默认 DNS 链路为 `客户端 → AdGuard Home :53 → MosDNS 127.0.0.1:5335`。
AdGuard Home 先过滤广告，并负责 DHCP 与本地域名；MosDNS 判断直连或代理：

- 国内域名并发查询阿里两个 H3 地址和 DNSPod UDP，采用最先返回的可用真实答案。
- 代理域名查询 Mihomo `127.0.0.1:7874`，返回 `198.18.0.0/16` Fake-IP。
- 未收录的域名先查询国内上游，回答属于大陆 IP 时直连，否则转入 Fake-IP。
- Mihomo 未启动或 DNS 不可用时，MosDNS 回退到直接解析，国内 DNS 继续工作。
  回退只保证解析可用，无法保证受限制网站能直连访问。

启用本机 MosDNS 分流时，AdGuard Home 每次启动先向 `127.0.0.1:5335`
发送本地 AAAA 就绪查询，同时验证 UDP 和 TCP 的有效 DNS 应答，最多等待 15 秒。
探针利用既定 AAAA 空回答规则，不依赖 WAN、公共上游或稍后启动的 Mihomo；
等待时间按系统 uptime 计算，避免开机 NTP 校时影响。未启用 MosDNS 时跳过。
超时记录 syslog 告警后继续启动 AGH，保留 DHCP 和 Web 管理；不另加公共 DNS
绕过分流。通过原有 LuCI 启停 AdGuard Home 时也会使用此检查。

Mihomo DNS 返回 `SERVFAIL` 时，清除该失败应答，立即触发公共 DNS 回退；
`REFUSED`、`NXDOMAIN` 和空 `NOERROR` 应答保留原行为。无响应回退阈值为
500 ms，未知域名回退阈值仍为 2000 ms。Mihomo 恢复后重新返回 Fake-IP，
不被回退期间缓存的真实答案覆盖。

阿里上游在 MosDNS 中使用 `h3://223.5.5.5/dns-query` 和 `h3://223.6.6.6/dns-query`，在 Mihomo 中使用
`https://223.5.5.5/dns-query#DIRECT&h3=true` 和
`https://223.6.6.6/dns-query#DIRECT&h3=true`，分别显式启用 HTTP/3。
2026-10-01 从路由器直接测试 DNSPod，DoH 超时、TCP 53 被重置，普通 UDP 53 正常。
按用户要求改为 `119.29.29.29`（UDP 53，Mihomo 附加 `#DIRECT`）。
2026-10-02 开启 Mihomo 全局 `prefer-h3`，两个阿里 DoH 地址均通过 `h3=true`
强制使用 H3。腾讯继续使用已验证可用的 UDP；公共上游并发取最快应答，
`prefer-h3` 控制 DoH 的协议选择，不把 H3 上游设为优先于 UDP 的主备关系。
当前 Fake-IP 分流模式的 `nameserver` 使用 Cloudflare `1.1.1.1` 和 Google
`8.8.8.8` 的 DoH，显式经“🚀 节点选择”访问；`nameserver-policy` 用 ROM 内的
`geosite:cn,private` 将国内及私有域名交给上述三个直连上游。
`proxy-server-nameserver` 和 `direct-nameserver` 保留国内直连上游，
不回指 MosDNS/AdGuard Home。海外 DoH 优先尝试 H3，不可用时允许 H2，
不额外配置会重复并发的 `fallback`。LuCI 的 DNS 遵循路由规则开关关闭，
出口由上游地址中的 `#DIRECT` 或代理组指定；该开关仍通过原生 LuCI 管理。
启动生成配置时明确识别 `#DIRECT`，自动补充节点 DNS 时排除代理上游，
防止海外 DoH 经节点访问却又用于解析节点自身。生产核心由轻量包装脚本启动；
非主动停止的退出会记录退出码，并在 `/tmp/openclash-last-exit.log` 保留最多
256 KiB 核心日志，避免守护脚本清理日志后丢失故障证据。该记录在重启路由器后清除。
MosDNS 的 `forward_local` 设置 `concurrent: 3`，每次未命中真实答案缓存时同时查询三个上游，
不再等待主备切换。2026-10-01 从当前路由器直接测试新增阿里备用 H3 地址，解析成功。
缓存命中不产生外部查询；已知代理域名仍只查询本机 Mihomo Fake-IP。
真实答案缓存、bootstrap DNS、AdGuard Home 前置过滤和选择性 Fake-IP 分流结构保留。
MosDNS 5.3.4-15 修正统计分类：执行错误显示 SERVFAIL，不计入“已拦截”；
真正的本地屏蔽仍计入拦截，正常的 AAAA/HTTPS 空回答仍显示 NOERROR。

已知代理域名分配 Fake-IP 时只查询本机 Mihomo，不额外查询外部 DNS。
未知域名先复用真实答案缓存，未命中时才查询公共 DNS 来判断；代理连接最终仍可能需要节点解析实际目标。
真实解析在独立的嵌套序列中完成并缓存，再按回答 IP 判断直连或 Fake-IP。
因此同一未知国外域名在真实答案 TTL 内重复访问，不再每次查询公共 DNS；
每次仍向本机 Mihomo 获取 Fake-IP。真实答案 TTL 过期后，可先用旧答案判断，
同时在后台重新解析；后续查询使用更新后的真实答案。
查询日志的最终 Fake-IP 应答仍显示未缓存；用于分类的真实缓存命中体现在
`mosdns_cache_hit_total{tag="lazy_cache"}` 指标，而非最终应答的缓存标记。
AdGuard Home 缓存关闭；MosDNS 仅缓存真实答案，最多 2048 项，
`lazy_cache_ttl: 86400` 使成功的地址回答最多保留一天。
原 TTL 内按正常缓存返回；过期命中立即返回短 TTL 的旧答案，并在后台刷新。
Fake-IP 不经过这两层缓存，映射由 Mihomo 持久化管理。
停止与恢复 OpenClash 时上游均保持 MosDNS，清理 AdGuard Home 缓存而不重启 DHCP。

OpenClash 默认使用原生 `fake-ip`（TCP REDIRECT / UDP TPROXY）。防火墙仅把
Fake-IP 和明确的代理 IP 例外交给 Mihomo；其他真实 IP 直接由系统转发。
同一脚本兼容 `fake-ip-mix` 与 `fake-ip-tun`，按原生 Fake-IP 规则复用协议、端口和标记，
保留核心用户、本地网络及回包豁免；重复执行不增加规则。保留 `fwmark 0x162 lookup 354`
策略路由：原生 TPROXY 模式为 table 354 的 `local default dev lo`，TUN 模式为
`default dev utun`。明确的 IP 例外默认包含 Telegram 官方 IPv4
网段，并合并 OpenClash 原生“大陆绕过 IP 例外”列表中的 IPv4 地址/CIDR。
按域名填写 IP 例外需要 dnsmasq，本镜像不提供；域名应在 MosDNS 灰名单设置。

“服务 → MosDNS”直接使用现成的 `luci-app-mosdns`，没有另建面板。
基本设置选择“自定义配置”，通过原生 YAML 编辑器调整此链路；默认配置模式的
表单参数不控制自定义 YAML。原生规则页的白名单优先直连、灰名单优先 Fake-IP，
同时支持 Hosts、DDNS 和重定向。广告过滤由 AdGuard Home 管理；本自定义配置
不加载 MosDNS 黑名单、广告规则集或广告订阅，UCI 明确设置 `adblock=0`。
原生规则页的“黑名单”文件不参与此配置。AAAA/HTTPS 空回答和私网 PTR 拒绝仍保留，
这些规则用于 IPv4 解析策略和避免本地反向查询外泄，不是广告过滤。
日志、查询统计、缓存清理和服务启停使用插件原生页面。

按用户指定策略，MosDNS 精确拒绝 `local.adguard.org`，所有查询类型通过 UDP/TCP
返回 `REFUSED`（rcode 5），优先于 Hosts、缓存、IPv4 查询类型策略及域名分流，
不查询上游。AdGuard Home 仍提前处理 AAAA，返回空答案而不转发给 MosDNS。
该规则可通过原生 LuCI 自定义 YAML 编辑器调整。
`injections.adguard.org` 恢复现有 `adguard.org` 代理分类，按原规则取得 Fake-IP。
这两个域名均无白名单或 Mihomo Fake-IP 排除例外；拒绝规则不匹配子域名。
路由器专用 `AX6000_Router.ini` 在订阅规则首部生成精确
`DOMAIN,local.adguard.org,REJECT`，不再额外生成 `adguard.org` 整域代理规则；
其正常分流沿用 `ProxyLite.list`。
该 INI 不导入旧 AdGuard 直连规则集，也不为 `local.adguard.com` 添加专门规则；
`injections.adguard.org` 按父域规则选择代理，没有单独例外。

文本域名/IP 集从锁定的裁剪 GeoSite 和大陆 IP 表导出；不安装完整的 v2ray
GeoIP/GeoSite 包，自动 GEO 更新关闭。更新内置分流数据时使用构建脚本重新导出
并构建，或在自定义配置中显式换用自己的数据文件。MosDNS 采用 `GOGC=50` 和
32 MiB Go 软内存目标；AdGuard Home 与 Mihomo 各为 128 MiB，该值不是 RSS 上限。

LAN 的 TCP/UDP 53 查询通过 LuCI 防火墙中可见的“LAN DNS to AdGuardHome”规则
转到 `192.168.199.1:53`，避免设备手写外部普通 DNS 跳过过滤。
MosDNS 不另启 DNS 劫持，OpenClash 和 TUN 的 DNS 劫持均关闭。
Mihomo 为国内、节点和直连解析保留阿里 H3 / DNSPod UDP；其他真实查询使用
经代理访问的 Cloudflare / Google DoH，避免回指 AdGuard Home 形成环路。
IPv4-only 策略：AAAA、SVCB(type 64) 和 HTTPS(type 65) 返回空答案；
关闭 IPv6 地址、前缀委派、转发、RA、DHCPv6 与 OpenClash IPv6 代理。
`99-ax6000-ipv4-only.conf`、设备 UCI 设置及接口 hotplug 保持该策略；
`zzz-ax6000-ipv4-only` 在首次启动时应用设置并禁用 odhcpd。
AdGuard Home 保留 DHCPv4，DHCPv6 范围为空；准备脚本不会重新填入 ULA。

全新配置自动启动 AdGuard Home 与 MosDNS；OpenClash 保持关闭，导入自己的
订阅配置后再启用。请保留配套端口、Fake-IP 模式及覆写/防火墙脚本；
升级 OpenClash 包时应使用本构建锁定与适配补丁。

默认 DHCPv4 地址池为 `192.168.199.100–192.168.199.249`，网关和 DNS 都是
`192.168.199.1`，租期 12 小时。局域网设备的租约、静态绑定、`设备名.lan` 和
反向解析由 AdGuard Home 管理。DHCP 服务仅绑定 `br-lan`。
DHCPv6 地址池启动前根据 `br-lan` 当前 ULA /64 自动生成，从 `::100` 开始。
odhcpd 仅发送 IPv6 RA/SLAAC 通告，DHCPv4/v6 关闭；AdGuard Home 不发送 RA。

路由器专用订阅由
[`AX6000_Router.ini`](https://raw.githubusercontent.com/DixCouleur/subconverter-profiles/main/AX6000_Router.ini)
引用 [`AX6000_Base.yaml`](https://raw.githubusercontent.com/DixCouleur/subconverter-profiles/main/AX6000_Base.yaml)。
INI 管理规则和分组；基础 YAML 管理 DNS/H3、日志、进程匹配、GEO 更新、profile 和嗅探默认值。
固件源码的 `/usr/share/openclash/profiles/` 保存同一份公开配置，供离线查看与导出。
基础 YAML 使用 `find-process-mode: off`，需要按路由器进程分流时可直接修改该文件。
转换 URL 的 `config` 参数应指向新 INI；原通用 `ACL4SSR_Online_NoAuto.ini` 保持原行为。

本地覆写只将 DNS 监听地址收回 `127.0.0.1:7874`、清空 TUN 的 DNS 劫持，
并兼容 Ruby YAML 对 `off` 和 IPv6 字符串的解析。OpenClash 自带 LuCI 仍负责端口、
运行模式、API 认证和其他本机选项；修改这些选项时无需改 GitHub 配置。
本地脚本不再重写 DNS 上游、规则、测速间隔或性能参数。

全新配置通过 OpenClash 自带的 LuCI 开关启用 `tcp-concurrent: true` 和
`unified-delay: true`，设置 `log-level: warning`、`geodata-loader: memconservative`。
这些默认值在导入配置时由 OpenClash 应用，之后仍可在 LuCI 中调整；
排查连接和分流问题时可将日志级别改回 `info`。TCP 并发尝试多个解析地址以减少建连等待，
统一延迟调整节点测试的延迟计算，两者不代表节点吞吐提高。
嗅探保留 HTTP/TLS/QUIC 和原有域名例外，默认关闭 `parse-pure-ip`，避免对缺少域名的
连接一律强制嗅探。此项使用原生 LuCI 的“强制嗅探纯 IP 连接”开关，仍可手动恢复。

专用 INI 为 18 个区域 `url-test` 组设置 600 秒间隔、100 ms 容差，Mihomo 默认
`lazy: true`；保留节点筛选表达式、测速 URL 和超时。手动选择、自动回退、
负载均衡组保留原设置；不新增代理集合的后台健康检查。
600 秒测速间隔减少周期性测试，但也会推迟测试发现故障的时间；如需更短间隔，
调整 GitHub 专用 INI 的 `600,5,100` 参数，再更新订阅。
Hysteria2 的 `up`/`down` 与 QUIC 窗口保留订阅值，不按 WAN 网口速率自动填充。

当前源码通过补丁 013 将订阅的 `mihomo -t` 校验与生产核心串行执行：先停核心，
有界校验，成功或失败后均恢复服务，因此校验期间会短暂中断代理。
启停操作共用锁，校验核心和生产核心均使用 `GOGC=50`、128 MiB Go 软内存目标；
该目标并不是进程 RSS 上限。补丁 014 将 LuCI 和调试脚本的版本读取改为运行中 API
及缓存，避免压缩核心在多次 `-v` 查询中并发解压。停机且无可用缓存时，版本查询
最多运行一次，并与核心启动/校验互斥。核心更新器对下载后的新核心也使用串行校验。

“服务 → AdGuard Home”使用
[rufengsuixing/luci-app-adguardhome](https://github.com/rufengsuixing/luci-app-adguardhome)，
锁定提交 `37fdf502b99328b37c9ef4c4387f069f67253f85`，包含中文设置、Web 入口、
日志查看、核心更新及 YAML 编辑页。完整的过滤器、查询日志、统计和 DNS 设置使用
[AdGuard Home 原生网页](http://192.168.199.1:3000/)，默认监听 `0.0.0.0:3000`，语言为简体中文。
LuCI 中可调整网页监听地址和端口；启动适配会同步到新版 YAML 的 `http.address`，
保留旧配置刷机时也会应用新的监听默认值。镜像不预置管理账号；在插件中首次设置
网页密码时，账号名为 `root`，已有账号则保留原用户名。

插件使用固件自带的 `/usr/bin/AdGuardHome`，配置仍为 `/etc/adguardhome/adguardhome.yaml`。
只有 `/etc/init.d/AdGuardHome` 管理进程；小写 `/etc/init.d/adguardhome` 是兼容入口。
该镜像由 AdGuard Home 直接提供 53 端口，插件内仅保留“无重定向”模式；
自动核心更新、额外开机网络重启与自动 GFW/主机任务默认关闭。
交付目录中的适配补丁为 `luci-adguardhome.patch`；上游模板同步为当前 DNS/DHCP 配置。

默认启用官方 AdGuard DNS filter，首次联网下载并每 24 小时刷新。配置和 DHCP 租约
持久化在 `/etc/adguardhome/`，租约数据库位于 `runtime/data/leases.json`；该目录
加入升级配置备份清单。过滤文件通过目录链接存放在内存，统计也使用独立内存目录，
查询日志仅保留内存中的最近 1000 条。重启保留租约与设置，清空统计/日志并重新下载
过滤文件，减少闪存写入并保留后装插件的空间。

DHCP 地址池、静态绑定和租约应在 AdGuard Home 原生网页管理。LuCI 常规的
“DHCP/DNS”页和租约列表仍按 OpenWrt UCI/dnsmasq 格式工作，不能用于管理这份固件
的 AdGuard Home DHCP。LuCI 的 AdGuard Home 面板提供服务配置；完整管理页使用
前述 `192.168.199.1:3000` 地址。

如为 AdGuard Home 原生网页设置了账号，OpenClash API 切换也需要认证。将凭据保存
到权限 `600` 的 `/etc/adguardhome/openclash.netrc`，内容采用 curl netrc 格式：
`machine 127.0.0.1 login 用户名 password 密码`。未设置账号时无需此文件。

`logs/mosdns-servfail-fallback-host-test.log` 使用真实 AdGuard Home、真实 MosDNS 和可计数的
本地上游验证过滤、国内缓存、代理仅查询本机、未知答案分类、Fake-IP 不缓存、
核心不可用时回退、Mihomo `SERVFAIL` 立即回退、恢复后重新返回 Fake-IP，以及统计和清理缓存 API。
同时验证 `REFUSED`、`NXDOMAIN` 和空 `NOERROR` 不触发公共 DNS 回退。
也通过三上游竞速、两个上游故障、恢复和全部上游故障注入，检查第三个上游最快时
立即返回、部分故障时仍能得到答案，以及 SERVFAIL 不计入拦截、私网 PTR 拒绝仍计入拦截。
`logs/mosdns-unknown-real-cache-host-test.log` 验证两次未知国外域名查询时，三个公共上游各只收到一次请求，
而本机 Fake-IP 上游仍收到两次；并用原 TTL 为 1 秒的真实答案验证过期时先返回旧分类、
后台刷新后在国内/国外分类间双向切换。
`logs/mosdns-unknown-real-cache-live-test.json` 记录当前路由器上 `httpbin.org` 的 UDP/TCP 查询、缓存和上游计数：
首次向三个公共上游各查询一次，第二次公共查询为零；该单域名样本的 MosDNS 耗时约 40 ms → 1.6 ms。
AdGuardHome/Mihomo 未重启，相关配置与分流规则逐项比较未变化。
`logs/mosdns-unknown-real-cache-sysupgrade-test.log` 记录新镜像的 `sysupgrade -T` 兼容性校验，未刷写。

`logs/service-performance-routing-test.log` 验证三种模式的 Fake-IP/IP 例外、真实 IP 绕过、
回包/本地/核心用户豁免和重复执行。`logs/service-performance-live-routing-test.log` 与
`logs/service-performance-lan-test.log` 记录当前原生模式的规则计数、LAN DNS、广告过滤、
Google 透明代理 HTTPS、百度直连 HTTPS，以及管理端点响应。`logs/service-performance-mosdns-test.log` 记录真实服务隔离测试结果，无响应上游约 501 ms 回退。
`logs/service-performance-sysupgrade-test.log` 记录新镜像在当前路由器上通过 `sysupgrade -T`；没有刷写。

`logs/adguardhome-dns-readiness-test.json` 记录临时回环高端口上的就绪探针测试：
延迟启动、TCP 分段应答、UDP/TCP 单协议可用、静默端口、回显、错误事务 ID、
错误问题与 SERVFAIL 均已验证。Shell 集成测试确认超时记录告警并继续启动；
MosDNS 关闭或未启用分流时跳过等待。测试未停止生产 DNS/DHCP 服务。
`logs/adguardhome-dns-readiness-lan-test.json` 记录部署后的 LAN DNS 和 Google 代理验证；
`logs/adguardhome-dns-readiness-sysupgrade-test.log` 记录本次新镜像通过 `sysupgrade -T`，未刷写。

当前自定义配置已移除 MosDNS 广告过滤，测试继续验证 AdGuard Home 的过滤和
MosDNS 的私网 PTR 策略。`logs/mosdns-servfail-fallback-lan-test.log` 记录当前路由器的
LAN UDP/TCP 解析、Fake-IP、AdGuard Home 过滤和 AAAA/HTTPS 空回答验证。
`logs/mosdns-failover-stats-unit.log` 保留统计插件的原有单元测试结果。
`logs/dns-host-test.log` 保留旧链路兼容路径与 DHCPv6 地址池生成的回归检查。
`logs/dhcp-host-test.log` 是同版官方 DHCPv4/v6 协议、地址池与租约读写的本机测试。

`logs/mosdns-runtime-*.log` 与 `logs/mosdns-lan-probes.log` 记录已运行路由器的
配置切换和验收；它们不能替代新镜像刷入后的首次启动、硬件 LED 与长期运行检查。
可在 macOS ARM64 复现：先下载并核验 `build.lock.json` 中两项 `host_test`
指定的归档，解压后传入对应程序路径。

```sh
rtk proxy python3 scripts/test-ax6000-mosdns.py /path/to/patched-mosdns /path/to/AdGuardHome
rtk proxy python3 scripts/test-ax6000-dns.py /path/to/AdGuardHome /path/to/mihomo
rtk proxy python3 scripts/test-ax6000-router-profile.py --mihomo /path/to/mihomo
rtk proxy python3 scripts/test-ax6000-adguardhome-ui.py /path/to/AdGuardHome /path/to/ax6000-ui-prepare.rb
rtk proxy python3 scripts/test-ax6000-dns-ready.py --router root@192.168.199.1
```

本次补充 `logs/adguardhome-ui-host-test.log`：旧配置监听迁移、密码数组与端口校验、
同版本原生程序经本机 LAN 地址访问 Web/API/资源，以及 API 跟随插件端口的切换/恢复均通过。
测试关闭 DHCP；这不能替代刷机后的路由器网络与 LuCI 实机验收。

## Turbo ACC 网络加速

“网络 → TurboACC”内置简体中文面板。采用 Linux/FW3 Flow Offloading，
包含 `kmod-ipt-offload`、`kmod-nf-flow`、`kmod-tcp-bbr`，不加入 SFE/fast-classifier。
面板提供软件流卸载、硬件流卸载和 MTK WED WO 控制项；硬件效果需要实机检查。

全新配置默认启用 BBR、软件流卸载、MTK 硬件流卸载和 WED；Full Cone 保持关闭。
`/etc/modules.conf` 内置 `options mt7915e wed_enable=Y`，在 Wi-Fi 驱动加载时启用 WED。
Turbo ACC 开关通过辅助脚本保存 `wed_enable=Y/N`，更改后需要重启路由器；
不会以运行时改写参数冒充 WED 已重新初始化。辅助脚本保留其他模块参数与注释，
相同设置不重复写入配置文件。
`logs/wed-host-test.log` 记录启用/停用/重新启用、重复调用不写入、重复参数清理、
保留其他模块参数及注释、拒绝非法输入的本机测试。
BBR 控制路由器本机发出的 TCP 连接，不直接改变所有转发客户端的拥塞控制。
流卸载启用后，已缓存的
转发流会绕过后续部分 Netfilter 路径，具体机制见 [Linux 内核说明](https://docs.kernel.org/networking/nf_flowtable.html)。

全新启动后应重新建立连接，检查 PPE 表项、WAN 吞吐和 CPU 使用，同时验证
OpenClash 规则命中、TCP/UDP 代理及 AdGuard Home 过滤。如果结果异常，可在面板
先关闭硬件流卸载，再关闭软件流卸载并复测；如需停用 WED，在 Turbo ACC 中关闭后重启。
此次已在现用系统确认 WED 开启及无线客户端的 PPE 绑定流，但新镜像尚未实机启动，
不能把现用系统的检查结果当作新镜像的性能测试结果。
Packet Steering 默认使用 netifd 的普通模式 `1`，没有强制使用全部 CPU；
可在实机分别测试模式 `0`、`1`、`2` 的吞吐与延迟，再决定是否更改。
不将这份固件的编译检查当作硬件加速性能结果。

SSH 状态检查：

```sh
uci show turboacc
sysctl net.ipv4.tcp_congestion_control
cat /proc/sys/net/ipv4/tcp_available_congestion_control
uci get firewall.@defaults[0].flow_offloading
uci get firewall.@defaults[0].flow_offloading_hw
uci get network.globals.packet_steering
uci get openclash.config.china_ip_route
cat /sys/module/mt7915e/parameters/wed_enable
cat /sys/kernel/debug/ppe0/entries
lsmod | grep -E "tcp_bbr|xt_FLOWOFFLOAD|nf_flow_table"
```

## 全新启动后的验收

默认 LAN 地址 `192.168.199.1`，WAN 使用 DHCP，PPPoE 可在 LuCI 中配置。
2.4 GHz、5 GHz 默认开启，SSID 和加密设置沿用 LEDE 的无线配置生成器；全新配置
默认 SSID 为 `LEDE`，不预置 Wi-Fi 密码。首次连接后，在“网络 → 无线”设置自己的
SSID 和 Wi-Fi 密码；root 也无预置密码。初始化脚本启用已有的无线设备，不覆盖
已有的 SSID、加密方式、密码、信道或带宽设置。时区为 Asia/Shanghai，界面为简体中文。
默认使用 Argon 主题，主题设置页也提供简体中文。
这描述的是全新配置启动；保留旧设置时，旧设置可能覆盖镜像默认值。

1. 检查 Argon 默认主题及中文 LuCI/主题设置页、SSH、三个 LAN 口及 WAN 口。客户端释放并续租 DHCP 后，应获得地址池内地址、网关和 DNS；在 AdGuard Home 原生网页确认租约，再重启路由器检查租约仍在。
2. 分别连接 2.4 GHz 与 5 GHz，确认 DHCP、域名解析及访问网络正常。
3. 验证 WAN DHCP 或 PPPoE；确认支持 DHCPv6 的客户端获得 ULA 地址。有 IPv6 上游时，再检查 RA/SLAAC 公网地址和 IPv6 联网。
4. 打开“服务 → AdGuard Home”，确认服务已运行；直接打开 `http://192.168.199.1:3000/`，
   确认过滤器下载成功，查询日志中能看到客户端，分别验证 UDP/TCP 和 IPv6 DNS。
5. 打开“服务 → MosDNS”，确认启用自定义配置，统计/日志和规则页可操作；
   AdGuard Home 上游应为 `127.0.0.1:5335`。打开 OpenClash，确认已识别当前版本锁中的 Meta 核心。
6. 导入自己的订阅或配置，启用 OpenClash，检查启动日志、DNS、规则匹配、
   TCP/UDP 连接；国内域名应返回真实 IP，代理域名应返回 `198.18.0.0/16` Fake-IP。
   AdGuard Home 仍能看到并过滤查询；停用 OpenClash 后上游保持 MosDNS，
   国内解析和租约正常，代理域名回退为真实解析。恢复后应重新返回 Fake-IP。
7. 打开 Turbo ACC 面板，确认 BBR、软/硬件流卸载及 WED 已启用；按前述步骤
   检查 PPE 和 CPU，并分别验证大陆 IP 直连及海外代理。用 `network.globals.packet_steering`
   查看普通模式是否生效。

可在 SSH 中记录基础状态；代理状态应在导入配置并启用后检查：

```sh
ubus call system board
ubus call network.interface.wan status
wifi status
nslookup openwrt.org 192.168.199.1
/usr/bin/AdGuardHome --version
/etc/init.d/adguardhome status
/etc/init.d/mosdns status
ubus call luci.mosdns get_stats
uci get dhcp.lan.dhcpv6
uci get dhcp.lan.ra
cat /etc/adguardhome/runtime/data/leases.json
uci get openclash.config.enable_redirect_dns
logread -e AdGuard
/etc/openclash/core/clash_meta -v
/etc/init.d/openclash status
logread -e openclash
```

OpenClash 默认停用，未预置任何订阅、账号、节点或个人规则。IPv6 路由功能保留，
OpenClash 的 IPv6 代理沿用插件默认关闭状态，可根据订阅在插件中开启。

构建与镜像检查记录在 verification.txt；实机启动、联网和代理检查需要路由器实测，
不会以编译成功替代这些结果。

参考：[AdGuard Home 0.107.79](https://github.com/AdguardTeam/AdGuardHome/releases/tag/v0.107.79)、[官方配置说明](https://github.com/AdguardTeam/AdGuardHome/wiki/Configuration)。
