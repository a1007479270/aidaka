# Qoder 自动签到

Qoder CN 个人版每日 Credits 自动领取 + 桌面端登录态备份/切换 + 本机一键签到。

- **奖励**：每日 **100 Credits**（一周 700 Credits）
- 签到脚本：`platforms/qoder.py`（单文件自包含，零依赖）
- 登录态管理：`switchers/qoder/switch_auth.py`（Windows，DPAPI+CNG AES-GCM 解密，零第三方依赖）

## 一、环境变量

青龙 → 系统设置 → 环境变量 → 新建：

| 名称 | 值 |
| --- | --- |
| `QODER` | `ACCESS_TOKEN#REFRESH_TOKEN#UID#备注#设备JSON`（多账号换行） |

示例（两个账号）：

```
dt-aaaa#drt-aaaa#019f...#主号#{"machineToken":"P1gA...","machineType":"92...","machineCode":"04fd...","machineId":"a50a...","machineHostname":"AMD","machineOS":"Windows","version":"0.4.8","clientType":"10"}
dt-bbbb#drt-bbbb#小号
```

第 3~5 段可省略（省略时备注=uid），但**设备 JSON 必须带上**，否则服务端不下发活动。

也支持 `QODER_ACCOUNTS_FILE` 指向 JSON 文件（`{"accounts":[{...}]}`），优先级低于 `QODER`。

## 二、取 token（每个账号做一次）

**方式一（推荐）：用 switcher 一键获取**

在已登录 Qoder 桌面端的 Windows 上：

```bash
python switchers/qoder/switch_auth.py show
```

脚本会解密本机登录态，直接输出 `ACCESS_TOKEN#REFRESH_TOKEN#UID#备注#设备JSON` 一整行，
**复制即可**填入青龙环境变量，不用手动开文件、不用抓包。

（交互式：双击 `switchers/qoder/switch_auth.bat` 选 `[2]`，效果相同。）

**方式二：手动读文件（不推荐，Qoder 的登录态是加密的）**

```
%APPDATA%\com.qodercn.app.stable\auth.v1.dat      # DPAPI + AES-GCM 密文
%APPDATA%\com.qodercn.app.stable\auth.machine-id  # 设备 ID
~\.qoder-cn\umid-cache.json                        # machineToken / machineType / machineCode
```

`auth.v1.dat` 只能在**同一台机器、同一个 Windows 登录用户**下解密，所以请走方式一。

## 三、定时任务

- 命令：`task platforms/qoder.py`（路径按实际上传位置改）
- 定时规则：`5 10,21 * * *`（一天 1~2 次）

**领取窗口：每天 10:00(UTC+8) 开新一轮，到次日 10:00 前，错过不补，所以别在 10 点前跑。**

## 四、输出字段

每个账号一行 JSON：

- `action=clicked` → 领取成功（`credits` 是本次领到的 Credits）
- `action=skip_already_claimed` → 本轮已领，跳过（`status=ok`）
- `action=no_campaign` → 活动列表为空（未到窗口 / 活动下线 / 设备头不符）
- `action=token_expired`、`no_device`、`campaign_failed` → 异常（`status=error`）

调试：`QD_DEBUG=1` 打印活动接口原始响应；`QD_DRYRUN=1` 只列活动不领取
（或 `python platforms/qoder.py --dry-run`）。

## 五、关键实现说明

- **必须带 `Cosy-*` 设备头**。只带 `Authorization: Bearer` 时接口返回 200，但
  `showCampaign:false`、`campaigns:[]`，看起来像"没有活动"——这是最容易踩的坑。
- 活动接口 `GET /sash/api/v1/me/campaigns`，领取 `POST /sash/api/v1/me/campaigns/{campaignId}/claim`。
- **领取幂等**：已领过再调返回 `status:CLAIMED, replayed:true`，不会重复发奖，
  因此可以放心一天跑多次补漏，脚本把它归为 `skip_already_claimed` 而不是 error。
- 刷新接口 `POST /api/v1/deviceToken/refresh`（body `{"refresh_token": "..."}`）。
  token 约 30 天过期，脚本在临近过期或收到 401 时自动刷新；`refreshToken` 若被轮换，用
  `QD_STATE_FILE=/path/qoder_lines.txt` 让脚本把最新一行写出来，复制回青龙即可。
- 国际版：设 `QODER_BASE=https://openapi.qoder.sh`（CN 版默认 `openapi.qoder.com.cn`）。

## 六、桌面端多账号切换 + 本机签到（switchers/qoder）

Qoder 桌面端单账号登录，登录态在：

```
%APPDATA%\com.qodercn.app.stable\auth.v1.dat + auth.machine-id + Local State
```

一起备份/还原这三个文件，即可实现多账号并存与切换，主号不丢失。
（凭据是 DPAPI 加密的，**备份只能在同一台机器、同一个 Windows 用户下还原**。）

双击 `switch_auth.bat` 进入菜单：

```
[1] 备份当前登录态（仅备份，不还原）
[2] 输出当前 QODER 信息 (ACCESS_TOKEN#REFRESH_TOKEN#UID#备注#设备JSON)
[3] 用当前登录态立即签到一次
[4] 还原 xxx  (昵称)   <- 有备份时才出现
[0] 取消
```

- 还原前会自动备份"当前登录态"，防止丢号。
- 冷启动友好：备份目录为空也能运行。
- `[3]`/`signin` 会现取登录态再调 `platforms/qoder.py`，所以 token 轮换、换账号都不用维护配置文件。

命令行模式：

```bash
python switchers/qoder/switch_auth.py            # 交互式菜单
python switchers/qoder/switch_auth.py list       # 仅列出所有备份
python switchers/qoder/switch_auth.py backup     # 仅备份当前登录态(带时间戳)
python switchers/qoder/switch_auth.py show       # 仅输出当前 QODER 信息
python switchers/qoder/switch_auth.py signin     # 用当前登录态立即签到
```

### 本机定时（不依赖青龙）

```bash
schtasks /create /f /tn "Qoder每日签到" /sc daily /st 10:05 ^
  /tr "python <仓库路径>\switchers\qoder\switch_auth.py signin"
```

## 七、常见问题

- **活动列表为空 / `no_campaign`**：设备 JSON 缺失或版本不符。回 Windows 重跑
  `python switchers/qoder/switch_auth.py show` 取新行；`QODER_VERSION` 可手动指定客户端版本号。
- **`token_expired`**：`refreshToken` 也失效了（约 1 年）。回 Windows 打开 Qoder 登录后重新 `show`。
- **代理报错 `EOF occurred in violation of protocol`**：本地代理抖动，脚本已内置 3 次退避重试。

## 八、合规提醒

请遵守 Qoder 活动条款：同一自然人/手机号/设备/登录环境视为同一用户，每日仅可领 1 次，
严禁多账号套利、刷量等作弊行为。本工具用于个人账号的日常自动化，请勿用于违规用途。
活动规则见 <https://docs.qoder.cn/events/100credits>。
