# WorkBuddy 自动签到

WorkBuddy（腾讯 CodeBuddy）每日积分签到 + 成长计划奖励探测 + 桌面端登录态备份/切换。

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

在已登录 WorkBuddy 的 Windows 电脑上：

```bash
python switchers/workbuddy/switch_auth.py show
```

直接输出 `ACCESS_TOKEN#UID#账号名` 一行，复制即可填入青龙环境变量。
（交互式：双击 `switchers/workbuddy/switch_auth.bat` 选 `[2]`，效果相同。）

加 `--save` 会把结果缓存进 `switchers/workbuddy/accounts.txt`，下次取不到时自动兜底；
`python checkin.py` 在环境变量为空时也会自动走这条路，不用手动配环境变量。

**方式二：手动读取登录态文件**

用记事本打开：

```
%LOCALAPPDATA%\CodeBuddyExtension\Data\Public\auth\workbuddy-desktop.info
```

取里面的 `auth.accessToken` 和 `account.uid`，按 `ACCESS_TOKEN#UID#账号名` 格式拼接。

> token 约 60 天过期，过期后重取更新环境变量即可。

### ⚠️ 新版客户端把字段加密了

新版把登录文件里的 `accessToken` / `refreshToken` / `nickname` 换成了信封：

```json
"accessToken": { "$wbEncrypted": 1, "envelope": "eyJzdWl0ZSI6MSwia2V5SWQiOiI5MT..." }
```

`envelope` 解码后是 `{suite:1, keyId, nonce, authTag, ciphertext}`，算法是 **AES-256-GCM**。
密钥在客户端构建时注入（`atRestSecretKey` → SHA256 得到 AES key，`keyId` 就是这把 key 的
SHA256 前 16 位）。本地没有这把钥匙，**解不开**。

所以 `switch_auth.py show` 改成按顺序找可用 token：

| 顺序 | 来源 | 说明 |
|---|---|---|
| 1 | 当前登录文件 | 旧版客户端仍是明文，直接用 |
| 2 | **同目录下的历史明文快照** | 加密前留下的 `workbuddy-desktop.<时间戳>.info`，没过期就能用 |
| 3 | `accounts.txt` | 上次 `--save` 留下的缓存 |

三条都不通时，脚本会打印诊断（哪个环节缺什么）和下一步可做的事，而不是只甩一句「失败」。
输出里会标明 token 来自哪个文件、哪天到期，**剩 7 天内会提醒**。

#### 已经试过、走不通的两条路（别再重复踩）

- **从进程内存捞 token**：扫了 13 个 WorkBuddy 进程共约 4 GB 内存，能捞到的只有
  `app_type=codebuddy` 的 token（CodeBuddy IDE 的）。拿它去调 `/v2/billing/meter/*`
  一律 **401**——billing 接口只认没有 `app_type`（或 `app_type=workbuddy`）的 token。
  加 `X-App-Type` 之类的头也无效，网关按 JWT 里的字段判。
- **用 refreshToken 自己续期**：refresh token 是 Offline 类型（Keycloak，realm=`copilot`，
  `azp=console`），有效期比 accessToken 长得多，但 `console` 是 confidential client，
  刷新必须带 `client_secret`。这个值不在客户端 JS 内存里（原生层参与），代码里也没有硬编码。

#### 到期后怎么办

`show` 能给出的最晚值就是「最后一次明文落盘的那个 token」。到期后三选一：

1. **换台机器 / 旧版客户端**跑一次 `show`，把账号行抄进 `switchers/workbuddy/accounts.txt`；
2. **装回旧版客户端登录一次**，它会写一份明文快照，再升级回来——快照留在 auth 目录，`show` 能读到；
3. 若手上有开发版客户端，DevTools 里抓一次 `Authorization: Bearer` 头，手工填 `accounts.txt`。

> 一个 token 管 60 天，一年换 6 次。填好 `accounts.txt` 后，本地跑签到和青龙都不用手动配环境变量。

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

- 接口域名必须用 `www.codebuddy.cn`（带 `/v2/`），`copilot.tencent.com` 会 404。
- `checkin-status` 状态接口的 `today_checked_in` 字段不可靠（活动未开始时 `active=false`），
  因此采用【直接调签到接口 + 用响应判定】策略，避免漏签。
- "今天已签到/请明天再来"走 HTTP 400，属业务正常，脚本归为 `skip_already_signed` 而非 error。

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
```

还原后请重启/刷新 WorkBuddy 桌面端确认账号已切换（若提示重新登录属正常）。

## 八、本机定时签到（不依赖青龙）

**方式一：Windows 计划任务**

```bash
schtasks /Create /TN WorkBuddyAutoCheckin /SC DAILY /ST 09:00 /F ^
  /TR "cmd /c cd /d %USERPROFILE%\aidaka && python platforms\workbuddy.py"
```

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
