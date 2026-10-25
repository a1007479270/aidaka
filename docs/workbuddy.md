# WorkBuddy 自动签到

WorkBuddy（腾讯 CodeBuddy）每日积分签到 + 成长计划奖励探测 + 桌面端登录态备份/切换。

- **奖励**：每日 **100 积分**（一周 700 积分）
- 签到脚本：`platforms/workbuddy.py`（单文件自包含，零依赖）
- 成长计划：`platforms/workbuddy_growth.py`（附属脚本，默认 DRYRUN 安全模式）
- 登录态管理：`switchers/workbuddy/switch_auth.py`（Windows，纯标准库）

## 一、环境变量

青龙 → 系统设置 → 环境变量 → 新建：

| 名称 | 值 |
| --- | --- |
| `WORKBUDDY` | `ACCESS_TOKEN#UID#备注`（多账号换行） |

示例：

```
tok_abc123#uid_001#主号
tok_def456#uid_002#小号
```

## 二、取 token（每个账号做一次）

**方式一（推荐）：用 switcher 一键获取**

在已登录 WorkBuddy 的电脑上：

```bash
python switchers/workbuddy/switch_auth.py show
```

直接输出 `ACCESS_TOKEN#UID#账号名` 一行，复制即可填入青龙环境变量。
（交互式：双击 `switchers/workbuddy/switch_auth.bat` 选 `[2]`，效果相同。）

新版客户端的加密信封会**当场解开**，不需要旧版客户端、不需要手抄密文。
加 `--save` 会把结果缓存进 `switchers/workbuddy/accounts.txt`，下次取不到时自动兜底；
`python checkin.py` 在环境变量为空时也会自动走这条路，不用手动配环境变量。

**方式二：手动读取登录态文件**（旧版客户端明文时可用）

```
%LOCALAPPDATA%\CodeBuddyExtension\Data\Public\auth\workbuddy-desktop.info
```

取 `auth.accessToken` 和 `account.uid`，按 `ACCESS_TOKEN#UID#账号名` 拼接。
新版客户端这里是密文，手抄没用——用方式一。

> token 由客户端滚动续期（有效期通常 30~60 天，刷新后旧 token 会被吊销）。
> 所以取号要「现取现用」，别长期存一份快照。

### 新版客户端把字段加密了

登录文件里的 `accessToken` / `refreshToken` / `nickname` / `phoneNumber` 换成了信封：

```json
"accessToken": { "$wbEncrypted": 1, "envelope": "eyJzdWl0ZSI6MSwia2V5SWQiOiI5MT..." }
```

`envelope` 解码后是 `{suite:1, keyId, nonce, authTag, ciphertext}`，算法 **AES-256-GCM**：

| 环节 | 规则 |
|---|---|
| AES 密钥 | `SHA-256(atRestSecretKey 字符串)` —— 对 44 字符 base64 **字符串本身**做 hash，不是先解码 |
| keyId | `SHA-256(key).hex[:16]`，同时出现在信封和 AAD 里，用错钥匙必然认证失败 |
| AAD | 54 字节固定结构：`"WB-AAD\0"` + `01` + `u32be(5)+"WBEV1"` + `u32be(6)+"sym-v1"` + `u32be(1)` + `u32be(16)` + `keyId`（ASCII 字符串，不是 hex） + `02 00 00`。本项目 `field_aad()` 逐字节实现，`selftest` 会校验长度 = 54 |

**密钥不落盘，但客户端自己随时能取**：`WorkBuddy.exe` 是 Electron 应用，带
`ELECTRON_RUN_AS_NODE=1` 启动时它退化成普通 Node，仍然注册着私有原生绑定，
于是可以问它要：

```bash
ELECTRON_RUN_AS_NODE=1 "C:/Program Files/WorkBuddy/WorkBuddy.exe" \
  -e "console.log(JSON.parse(process._linkedBinding('electron_browser_workbuddy_storage').loggerGet()).atRestSecretKey)"
```

`switch_auth.py` 就是这么做的：起一个隐藏子进程取密钥（约 0.5 秒，免管理员、不用客户端开窗口），
在本机内存里解密，明文只用于拼一行环境变量。密钥来源优先级：

```
--key <44 字符密钥>  →  WORKBUDDY_ATREST_KEY  →  客户端原生绑定  →  （无）
```

取不到时 `show` 按顺序回退：

| 顺序 | 来源 | 说明 |
|---|---|---|
| 1 | 当前登录文件 | 明文直接用；信封则现场解密 |
| 2 | 同目录下的历史明文快照 | 加密前留下的 `workbuddy-desktop.<时间戳>.info` |
| 3 | `accounts.txt` | 上次 `--save` 留下的缓存 |

全都拿不到时，脚本打印诊断（缺客户端 / 缺密钥 / keyId 对不上）和下一步可做的事。
输出里标明 token 来自哪个文件、哪天到期，**剩 7 天内会提醒**。

#### 出问题先跑自检

```bash
python switchers/workbuddy/switch_auth.py diag       # 客户端路径 / 密钥来源 / 本机keyId / 文件keyId / 能否取号
python switchers/workbuddy/switch_auth.py selftest   # AES-256-GCM 已知答案测试（CI 会跑）
```

`diag` 里两个 keyId 不一致 = 客户端升级换过钥匙，此时旧备份里的 token 解不开，
需要重新登录一次生成新信封。

#### 青龙上为什么解不开

青龙容器里既没有 `WorkBuddy.exe`，也没有 `atRestSecretKey`，信封在那儿就是死数据。
所以青龙只能吃**明文账号行**：在装了客户端的机器上 `show` 一次，把结果填进环境变量。
这也是为什么本项目把「取号」和「签到」分成两个脚本。

#### 关于两条流传很广的说法（已核实，不必再试）

- **「扫进程内存能捞到密钥/令牌」**：扫内存这条路早年有人试过，捞到的往往是
  `app_type=codebuddy` 的 CodeBuddy IDE 令牌，跟 WorkBuddy 会话不是一回事；
  取密钥的正确入口是上面的原生绑定，不用 `ReadProcessMemory`，也不用管理员权限，
  macOS 上还照样能用（内存扫描在 macOS 基本走不通）。
- **「用 refreshToken 自己续期」**：refresh token 是 Offline 类型（Keycloak，
  realm=`copilot`，`azp=console`），但 `console` 是 confidential client，刷新必须带
  `client_secret`，该值由原生层参与计算，客户端 JS 里拿不到。所以别让脚本去刷——
  让客户端自己续期，脚本每次都现取，才是稳的。

#### 到期后怎么办

现在不用等过期才处理：客户端刷新后，`show` 每次都能拿到当前最新的 token。
只想少折腾就：

1. 本机直接跑 `python checkin.py`（环境变量留空也行，会自动现取）；
2. 青龙侧定时把 `show` 的结果同步过去（手动或另写同步脚本）；
3. 完全离线：`WORKBUDDY_ATREST_KEY` 存好密钥，任何机器上都能解本机备份的加密文件。


## 三、定时任务

- 命令：`task platforms/workbuddy.py`（路径按实际上传位置改）
- 定时规则：一天 1~2 次，推荐 `0 9,21 * * *`

## 四、输出字段

每个账号一行 JSON：

- `action=clicked` → 领取成功（`points` 积分，`streak_days` 连续天数）
- `action=skip_already_signed` → 今天已签到，跳过（`status=ok`）
- `action=no_account` → 仍是脱敏占位值，未配置环境变量
- `status=error` → 异常（多为 token 失效）

单账号失败不影响其他账号；全部正常退出码 0，存在异常退出码 1（青龙据此判成败、发通知）。
调试：`WB_DEBUG=1` 或 `python platforms/workbuddy.py --debug` 打印状态接口原始响应。

## 五、关键实现说明

- 接口域名：脚本用 `www.codebuddy.cn`（带 `/v2/`）。实测同一个 token 打
  `www.codebuddy.cn` / `www.workbuddy.cn` / `copilot.tencent.com` 的
  `/v2/billing/meter/checkin-status` 都返回 200；个别账号只在其中一个域返回 401
  （网关按 JWT 的 `iss` 分流），遇到 401 时换另一个域试一次即可。
- JWT 里带 `app_type`（常见 `codebuddy`）**不影响** billing 接口——实测这类 token 正常调用。
- `checkin-status` 状态接口的 `today_checked_in` 字段不可靠（活动未开始时 `active=false`），
  因此采用【直接调签到接口 + 用响应判定】策略，避免漏签。
- "今天已签到/请明天再来"走 HTTP 400，属业务正常，脚本归为 `skip_already_signed` 而非 error。
- 签到是**幂等**的：一天跑几次都只领一次。

## 六、成长计划额外奖励（platforms/workbuddy_growth.py）

桌面端"成长计划"页面（www.workbuddy.cn/profile/plans-usage）里有可领取奖励
（连续签到奖励、任务积分、成长礼包等）。本脚本复用同一账号登录态探测/领取：

- 登录态二选一：`WORKBUDDY`（桌面端 token，Bearer 鉴权）或 `WORKBUDDY_COOKIE`（网页端 Cookie）。
- 默认 **DRYRUN 探测模式**（只探测不领取）；设 `WB_DRYRUN=0` 且已在脚本中按浏览器真实
  "领取"请求补全 `REWARDS` 列表后才会实际领取。

```bash
python platforms/workbuddy_growth.py            # 探测模式
WB_DRYRUN=0 python platforms/workbuddy_growth.py
```

## 七、桌面端多账号切换（switchers/workbuddy）

原理：WorkBuddy 桌面端单账号登录，登录态就是本地一个 JSON 文件，备份/恢复它即实现换号。

双击 `switch_auth.bat` 进入菜单：

```
[1] 备份当前登录态（仅备份，不还原）
[2] 输出当前 WORKBUDDY 信息 (ACCESS_TOKEN#UID#账号名)
[3] 还原 xxx  (昵称 / uid)   <- 有备份时才出现
[0] 取消
```

- 还原前会自动备份"当前登录态"，防止丢号。
- 冷启动友好：备份目录为空也能运行，先 `[1]` 生成第一个备份。
- 脚本目录跟随自身：`switch_auth.py` 与 `workbuddy_auth_backup/` 放一起，拷到任意目录/电脑都能用。

命令行模式：

```bash
python switchers/workbuddy/switch_auth.py            # 交互式菜单
python switchers/workbuddy/switch_auth.py list       # 仅列出所有备份
python switchers/workbuddy/switch_auth.py backup     # 仅备份当前登录态(带时间戳)
python switchers/workbuddy/switch_auth.py show       # 仅输出当前 WORKBUDDY 信息
python switchers/workbuddy/switch_auth.py diag        # 自检：客户端/密钥/keyId/能否取号
python switchers/workbuddy/switch_auth.py selftest    # GCM 已知答案测试
python switchers/workbuddy/switch_auth.py show --key <44字符密钥>   # 手动指定密钥
```

`backup` 备份的是**原样字节**（仍是加密信封）。密钥是客户端构建期固定的，
同一版本客户端之间可以互相还原；客户端大版本升级换了 keyId 时，旧备份需要
`--key` 或 `accounts.txt` 里的明文兜底。

还原后请重启/刷新 WorkBuddy 桌面端确认账号已切换（若提示重新登录属正常）。

## 八、本机定时签到（不依赖青龙）

**方式一：Windows 计划任务**

```bash
schtasks /Create /TN WorkBuddyAutoCheckin /SC DAILY /ST 09:00 /F ^
  /TR "cmd /c cd /d %USERPROFILE%\aidaka && python platforms\workbuddy.py"
```

本机跑可以完全不配 `WORKBUDDY`：`platforms/workbuddy.py` 发现环境变量为空时，
会调用仓库内的 switcher 现取并解密（要求本机装着客户端且登录过）。

**方式二：WorkBuddy 内置自动化**

WorkBuddy 的「自动化」= 定时执行的 Prompt 任务。左侧栏「自动化」→「新建自动化」：

| 字段 | 值 |
| --- | --- |
| 名称 | WorkBuddy 每日积分签到 |
| Prompt | 运行 `platforms/workbuddy.py`，脚本幂等今日已签会跳过，读取输出汇报签到结果（领取积分 / 已签到 / token 失效） |
| 触发时间（RRULE） | `FREQ=DAILY;BYHOUR=9;BYMINUTE=0` |
| 工作目录 | 仓库所在目录 |
| 状态 | ACTIVE |

依赖本机开机 + WorkBuddy 桌面端运行，关机/休眠到点不执行。

## 九、合规提醒

请遵守 WorkBuddy 活动条款：同一手机号/微信号/设备 ID/IP 关联的多个账号视为同一用户，
严禁多账号套利、刷量等作弊行为。本工具用于个人账号的日常自动化，请勿用于违规用途。
