# aidaka · AI 打卡机

> **ima / WorkBuddy / Qoder / TraeWork 四平台每日签到，本地、青龙、WPS 云端三种部署方式。**

把四个 AI 编程工具的每日积分签到收进一个仓库：青龙面板多账号签到、桌面端登录态备份/切换、
本机定时、**金山文档云端定时（零服务器，关机也照跑）**。签到脚本纯 Python 标准库，**零第三方依赖**。

| 跑在哪 | 需要常开设备 | 适合谁 |
| --- | --- | --- |
| **本地**（`python checkin.py`） | 是 | 想随时手动跑、看日志 |
| **青龙面板** | 是（服务器/软路由/NAS） | 已有青龙，想 7×24 |
| **WPS 云端**（金山文档 AirScript） | **否** | 没服务器、电脑会关机 |

> ⚠️ **安全提示**：脚本内所有 token 均已脱敏（`YOUR_ACCESS_TOKEN_HERE` 等）。凭据通过环境变量或登录态文件注入，
> **切勿把真实 token 提交到仓库**（`.gitignore` 已挡住各类备份目录与凭据文件）。

## 支持平台

| 平台 | 奖励 | 环境变量 | 账号行格式 | 详细文档 |
| --- | --- | --- | --- | --- |
| ima（腾讯 AI 工作台） | 每日登录福利 + 满签奖励 | `IMA` | `ima_uid#uid_type#ima_guid#refresh_token#备注` | [docs/ima.md](docs/ima.md) |
| WorkBuddy（腾讯 CodeBuddy） | 每日积分 | `WORKBUDDY` | `ACCESS_TOKEN#UID#备注` | [docs/workbuddy.md](docs/workbuddy.md) |
| Qoder（CN 个人版） | 每日 Credits | `QODER` | `ACCESS_TOKEN#REFRESH_TOKEN#UID#备注#设备JSON` | [docs/qoder.md](docs/qoder.md) |
| TraeWork（国内个人版） | 每日积分 | `TRAEWORK` | `ACCESS_TOKEN#UID#备注#设备ID` | [docs/traework.md](docs/traework.md) |

多账号统一用**换行**分隔，一行一个账号，例如：

```
token_主号#uid_1#主号
token_小号#uid_2#小号
```

## 快速开始

### 方式一：统一入口（推荐，本机使用）

```bash
# 跑全部平台
python checkin.py

# 只跑指定平台
python checkin.py ima qoder

# 列出所有平台及环境变量格式
python checkin.py --list

# 只探测不实际领取（安全试运行）
python checkin.py --dry-run

# 打印接口原始响应（排障用）
python checkin.py --debug
```

**本地跑不用先配环境变量。** 某个平台的环境变量为空时，`checkin.py` 会自动按下面顺序找凭证：

1. 环境变量（`IMA` / `WORKBUDDY` / `QODER` / `TRAEWORK`）
2. `switchers/<平台>/accounts.txt`（一行一个账号，格式同环境变量）
3. 现跑 `switchers/<平台>/switch_auth.py show`，从**本机登录态**取一份

取到的凭证只在本次进程内使用，**不会写进系统环境变量**。运行时每行会打印 `[凭据] …` 说明来源。

| 开关 | 作用 |
| --- | --- |
| `--save-local-cred` | 把取到的账号行存成 `switchers/<平台>/accounts.txt`，下次直接用（含明文 token，已在 `.gitignore` 里） |
| `--no-local-cred` | 关掉本地回退，只用环境变量（青龙、CI 等场景） |

> **WorkBuddy 的特殊情况**：新版客户端把 token 加密成 `{"$wbEncrypted":1,...}` 信封（AES-256-GCM）。
> 密钥不落盘，但客户端自带原生绑定能当场交出来——switcher 用 `ELECTRON_RUN_AS_NODE=1`
> 起一个隐藏子进程取密钥，在本机解密，所以**四个平台都是从本机登录态实时取号**，
> 不需要旧版客户端、也不用等 token 过期才换。
> 青龙侧没有客户端、解不开信封，仍需把账号行填进环境变量（见
> [docs/workbuddy.md](docs/workbuddy.md#新版客户端把字段加密了)）。

### 方式二：青龙面板（服务器 7×24 运行）

每个平台脚本都是**单文件自包含**的，把 `platforms/` 下对应文件单独上传到青龙即可，不需要上传整个仓库：

```bash
platforms/ima.py          # 青龙里重不重命名都行，路径对即可
platforms/workbuddy.py
platforms/qoder.py
platforms/traework.py
```

环境变量在青龙「系统设置 → 环境变量」里新建（名称见上表），定时规则建议一天 1~2 次，例如 `0 9,21 * * *`。
Qoder 注意：领取窗口每天 10:00(UTC+8) 开放，**别在 10 点前跑**，建议 `5 10,21 * * *`。
完整部署指南见 [docs/qinglong.md](docs/qinglong.md)。

### 方式三：单平台直接运行

```bash
python platforms/ima.py --dry-run
python platforms/workbuddy.py --debug
python platforms/qoder.py
python platforms/traework.py
```

### 方式四：金山文档 AirScript（零服务器，关机也能跑）

不想搭服务器、也不想让电脑常开的话，把这个仓库的签到逻辑跑在**金山文档（WPS）智能表格**的
AirScript 云端定时任务里——账号填在表格里，云端每天定时执行，结果写回表格。

**👉 部署页（一键复制脚本）**：[wps-airscript/deploy.html](wps-airscript/deploy.html)
　**说明文档**：[wps-airscript/README.md](wps-airscript/README.md)
　**模板表格**：[www.kdocs.cn/l/ckNJ04YURB8F](https://www.kdocs.cn/l/ckNJ04YURB8F)

三步走：

1. 打开上面的模板表格，另存一份到自己账号下
2. 打开部署页点「复制脚本」→ 表格 `效率` → `高级开发` → `AirScript 脚本编辑器` → 粘贴保存
   （编辑器工具栏「服务」里要确认已添加 **网络API**）
3. A 列填平台名、B 列填账号 JSON，再挂个「每天 10:30」的定时任务

账号 JSON 格式、推送配置（Server酱 / PushPlus / 企业微信）、排障都在
[wps-airscript/README.md](wps-airscript/README.md) 里。

> Qoder 的领取窗口每天 10:00 才开，定时别早于 10 点。

## 目录结构

```
aidaka/
├── checkin.py                  # 统一入口（一条命令跑全部平台）
├── platforms/                  # 各平台签到脚本（单文件自包含，青龙直接上传）
│   ├── ima.py
│   ├── workbuddy.py
│   ├── workbuddy_growth.py     # WorkBuddy 成长计划奖励探测（附属，默认 DRYRUN）
│   ├── qoder.py
│   └── traework.py
├── switchers/                  # 桌面端登录态管理（Windows，双击 .bat 进菜单）
│   ├── to_wps.py               #   账号行(# 分隔) → 金山文档表格 B 列 JSON 转换器
│   ├── to_wps.bat              #   同上，Windows 双击出菜单（转换结果自动进剪贴板）
│   ├── ima/                    #   凭证提取(DPAPI+AES-GCM) / 备份 / 还原
│   ├── workbuddy/              #   登录态备份 / 还原 / 取号
│   ├── qoder/                  #   登录态(DPAPI+AES-GCM)备份 / 还原 / 取号 / 立即签到
│   └── traework/               #   登录态(AES-128-CBC)备份 / 还原 / 取号
├── wps-airscript/              # 金山文档 AirScript 版（零服务器，云端定时）
│   ├── checkin.js              #   四平台签到脚本（粘进 AirScript 编辑器即可）
│   ├── deploy.html             #   部署页：一键复制脚本 + 模板地址 + 步骤
│   ├── build.py                #   由 checkin.js 生成 deploy.html
│   └── README.md               #   部署说明 / 账号格式 / 排障
├── docs/                       # 各平台详细文档 + 青龙部署 + FAQ
├── requirements.txt            # 仅切换脚本按需 cryptography，签到零依赖
├── LICENSE                     # MIT
└── .gitignore                  # 已挡住各类凭据/备份目录
```

## 取 token（每个账号做一次）

在**已登录对应桌面端的 Windows 电脑**上，进入 `switchers/<平台>/` 双击 `switch_auth.bat` 选 `[2]`，
脚本会直接输出青龙环境变量所需的账号行，**复制即用**，不用手动翻文件、不用抓包：

```bash
python switchers/ima/switch_auth.py show        # ima（extract 需先完全退出 ima）
python switchers/workbuddy/switch_auth.py show
python switchers/qoder/switch_auth.py show
python switchers/traework/switch_auth.py show
```

多账号：在桌面端切换登录下一个账号 → 再跑一次 `show` → 逐行贴进同一个环境变量。
WorkBuddy 的 `show` 会自动解开新版加密信封，前提是本机装着客户端（自定义目录用
`WORKBUDDY_CLIENT_EXE` 指定）；这一步只能在 Windows 本机做，青龙上解不开。
`switchers/` 同时提供登录态**备份/还原**（还原前自动备份当前登录态，防止丢号），
备份目录跟随脚本自身，拷到任意目录/电脑都能用。

要填金山文档表格（AirScript 版）的话，别手抄 JSON —— 一条命令把上面那行转成 B 列要的格式：

```bash
python switchers/to_wps.py qoder                # 单个平台，输出可粘贴的 JSON
python switchers/to_wps.py all --tsv --clip     # 四个平台一起转好并复制，表格 A 列粘一次填满整表
python switchers/to_wps.py ima --stdin          # 从别处粘一行进去
```

Windows 上也可以直接**双击 `switchers/to_wps.bat`**，出中文菜单，选个序号就行，转好的 JSON 自动进剪贴板。

## 输出字段

每个账号输出一行 JSON（方便青龙日志查看与通知解析）：

| 字段 | 说明 |
| --- | --- |
| `action=clicked` | 领取成功（`credits`/`points` 是本次获得的积分） |
| `action=skip_already_signed` | 今天已签到，跳过（`status=ok`，不算异常） |
| `action=no_account` / `token_expired` | 未配置账号 / token 失效（`status=error`） |
| `action=disabled` | 该账号未开启签到功能 |
| `action=no_campaign` | 活动列表为空（Qoder：未到 10:00 窗口或设备头不符） |

单账号失败不影响其他账号；全部正常退出码 0，存在异常退出码 1（青龙据此判成败、发通知）。
脚本均**幂等**：一天跑多次不会重复领取，可放心多跑补漏。

## 定时部署

| 方式 | 适用场景 | 说明 |
| --- | --- | --- |
| 金山文档 AirScript | **没有服务器、电脑不常开** | 金山文档里跑云端定时，见 [wps-airscript/README.md](wps-airscript/README.md) |
| 青龙面板 | 有服务器/常开设备 | 上传单文件 + 环境变量 + cron，见 [docs/qinglong.md](docs/qinglong.md) |
| Windows 计划任务 | 本机常开 | `schtasks` 每天跑一次，命令见各平台文档 |
| WorkBuddy 内置自动化 | 本机常开 | 用 WorkBuddy 的「自动化」功能定时跑脚本，见 [docs/workbuddy.md](docs/workbuddy.md) |

关机/休眠到点不执行；要关机也能跑就用金山文档 AirScript 或青龙。

## 常见问题

token 失效怎么办、活动列表为空、Qoder 设备头、TraeWork 设备 ID、ima 提取失败等，
见 [docs/faq.md](docs/faq.md)。

## 合规提醒

请遵守各平台活动条款：同一自然人/手机号/设备/登录环境视为同一用户，每日仅可领 1 次，
**严禁多账号套利、刷量等作弊行为**。本工具用于个人账号的日常自动化，请勿用于违规用途。

## License

[MIT](LICENSE)

---

### English in brief

`aidaka` (AI Daka — "daily punch-in") is a zero-dependency (Python stdlib only) daily
check-in toolkit for four AI dev-tool platforms: ima, WorkBuddy, Qoder and TraeWork.
Three ways to run it: locally (`python checkin.py`), on a QingLong panel, or entirely
in the cloud via Kingsoft Docs / WPS AirScript — no server needed, works even when your
PC is off. Multi-account, idempotent, with Windows desktop login-state backup/restore
switchers. All credentials are injected via environment variables or the spreadsheet;
never commit real tokens.
