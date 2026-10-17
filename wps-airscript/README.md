# aidaka · WPS 云端版（AirScript，零服务器签到）

把 ima / WorkBuddy / Qoder / TraeWork 四个平台的每日签到，交给**金山文档（WPS）智能表格**的
AirScript 云端定时任务执行——不用服务器、不用青龙、不用电脑常开，关机也照跑。

> 这是本仓库的第四种跑法，和 `platforms/` 里的 Python 版**功能完全等价**，账号配置互通。

---

## 一键开始

### 👉 打开部署页（推荐）

**[deploy.html](deploy.html)** —— 双击用浏览器打开，里面有：

- 模板表格地址（带「复制链接」按钮）
- **「复制脚本」按钮**（一次复制全文，粘进 AirScript 编辑器即可，不用改一行）
- 账号 JSON 格式对照表
- 定时任务配置要点

想直接看脚本源码：**[checkin.js](checkin.js)**（约 500 行，纯 JS，零依赖）。

### 模板表格

```
https://www.kdocs.cn/l/ckNJ04YURB8F
```

打开后右上角「…」→ 另存为 / 创建副本，存到自己账号下再填账号。
表格里已带好工作表结构（`签到配置`）和表头，照 B 列填就行。

---

## 五分钟部署

| 步骤 | 操作 |
| --- | --- |
| 1 | 复制上面的模板表格到自己账号下 |
| 2 | 表格顶部菜单 `效率` → `高级开发` → `AirScript 脚本编辑器` |
| 3 | 编辑器工具栏点立方体图标（服务）→ 确认已有 **`网络API`**；没有就点「添加服务」加上 |
| 4 | 清空示例代码 → 打开 [deploy.html](deploy.html) 点「复制脚本」→ `Ctrl+V` 粘贴 |
| 5 | `Ctrl+S` 保存，点 ▶ 运行；首次会弹「服务授权」（云文档 + 外部网络）→ 选 **允许** |
| 6 | 按下面的格式把账号填进 A / B 列 |
| 7 | `效率` → `高级开发` → `定时任务` → 创建任务，选「每天」，时间填 **10:30** 之后 |

第 5 步跑完，G 列应该出现类似 `[workbuddy] 主账号 skip_already_signed: 今天已签到` 的结果。
如果日志里报 `HTTP 对象不可用`，就是第 3 步的「网络API」服务没加。

---

## 表格结构

工作表名 **`签到配置`**（想改名的话改 `checkin.js` 里 `getSheet()` 那一行）：

| 列 | 表头 | 谁写入 | 说明 |
| --- | --- | --- | --- |
| A | 平台 | 你 | `ima` / `workbuddy` / `qoder` / `traework`，小写 |
| B | 账号JSON | 你 | 一行一个账号，格式见下表 |
| C | 是否签到 | 脚本 | 每次运行写入北京时间戳，用来确认有没有漏跑 |
| D | Server酱 | 你（可选） | SendKey，填了就推送 |
| E | PushPlus | 你（可选） | token，填了就推送 |
| F | 企业微信Webhook | 你（可选） | 机器人 Webhook 完整地址 |
| G | 签到结果 | 脚本 | 最近一次的动作 + 消息 |

脚本扫描第 2～30 行，A 列为空的行自动跳过。
推送是**汇总式**的：同一种推送配置只发一条，内容是所有账号的结果，跑完才发，失败也照发。

---

## 账号 JSON 格式（B 列）

```jsonc
// ima：refresh_token 长期有效，access_token 由脚本每次现换
{"ima_uid":"","uid_type":"1","ima_guid":"","refresh_token":"","name":""}

// WorkBuddy：token 约 60 天过期
{"token":"","uid":"","name":""}

// Qoder：device 段必须有，缺了活动接口不返回活动
{"name":"","refreshToken":"","accessToken":"","uid":"",
 "device":{"clientType":"10","machineOS":"Windows","machineHostname":"",
           "machineId":"","machineToken":"","machineCode":"","machineType":"","version":""}}

// TraeWork：device_id 建议带上，缺了服务端可能返回 9004
{"token":"","uid":"","device_id":"","name":""}
```

这些 JSON **不要手抄**。本仓库的 switcher 输出的是「青龙环境变量」格式（`#` 分隔的一行），
而表格要的是 JSON——用 [`switchers/to_wps.py`](../switchers/to_wps.py) 一条命令转好，直接粘：

**Windows 不想敲命令**：双击 [`switchers/to_wps.bat`](../switchers/to_wps.bat)，出**中文菜单**，
按序号选平台即可，转好的 JSON 自动进剪贴板，回到表格 B 列 `Ctrl+V` 就行。
选 `[5]` 还能一次转完四个平台、直接整表粘贴。

```bash
# 单个平台：自动跑本机 switcher，输出可粘贴的 JSON
python switchers/to_wps.py qoder

# 顺带复制到剪贴板
python switchers/to_wps.py qoder --clip

# 四个平台一次转完，输出「平台<TAB>JSON」，在表格 A 列粘贴一次就填满所有行
python switchers/to_wps.py all --tsv --clip

# 从别处粘一行进去（不跑 switcher）
python switchers/to_wps.py traework "ACCESS_TOKEN#UID#备注#设备ID"
python switchers/to_wps.py ima --stdin        # 然后 Ctrl+V 粘贴，回车结束
```

对应关系（脚本内部就是按这个映射搬字段）：

| 平台 | switcher 输出的 `#` 段 | → B 列 JSON 字段 |
| --- | --- | --- |
| ima | `ima_uid#uid_type#ima_guid#refresh_token#备注` | `ima_uid / uid_type / ima_guid / refresh_token / name` |
| workbuddy | `ACCESS_TOKEN#UID#备注` | `token / uid / name` |
| qoder | `ACCESS_TOKEN#REFRESH_TOKEN#UID#备注#设备JSON` | `accessToken / refreshToken / uid / name / device` |
| traework | `ACCESS_TOKEN#UID#备注#设备ID` | `token / uid / name / device_id` |

脚本会自己挑行（忽略 `===` 标题和提示行）、自己祛占位符备注；
`--tsv` 输出的每一行都是「平台 + TAB + JSON」，粘到表格 A 列时 kdocs 会自动分列分行。

> **WorkBuddy 注意**：新版客户端把登录态加密了，`switch_auth.py show` 会输出一个
> `{'$wbEncrypted': ...}` 的密文信封而不是 token。这时 `to_wps.py` 会明确报错并给出两条出路：
> 用旧版明文备份 restore 后再 show，或者从客户端请求头抄 `Authorization: Bearer <token>`，
> 然后 `python switchers/to_wps.py workbuddy "<token>#<uid>#备注"`。

---

## 定时建议：为什么是 10:30

时间下拉只有 30 分钟粒度（09:00 / 09:30 / 10:00 / 10:30 …）。

- **Qoder 的领取窗口每天 10:00(UTC+8) 才开**，10:00 之前跑会撞上前一天那个已领完的窗口
- 所以选 **10:30** 起，保证四个平台都落在有效窗口内
- 需要补跑直接手动点运行就行，所有平台接口都是**幂等**的，重复跑不会重复领

---

## 运维要点

| 平台 | token 寿命 | 过期后怎么办 |
| --- | --- | --- |
| ima | refresh_token 长期 | 一般不用管；失效了重新 `extract` 换 B 列 |
| WorkBuddy | 约 60 天 | 换掉 B 列 JSON 里的 `token` |
| Qoder | access 约 30 天 | 脚本自动刷新，并把新 token **回写 B 列**，不用管 |
| TraeWork | 约两周 | 重新 `show` 取一行换掉 |

其它：

- **结果在哪看**：G 列最后一次结果 + C 列运行时间；详细日志在 AirScript 编辑器下方的「日志」面板
- **只跑一部分**：把不想跑的行 A 列清空即可，脚本按 A 列是否为空判断
- **超时**：单个请求默认 30s；账号多时整轮会变长，30 行以内没问题

---

## 安全须知

1. **B 列是明文 token。** 模板默认是「免登录可编辑」链接，填完账号后请把文档权限改成
   **仅指定人可编辑**，并且不要把填了账号的表格链接发给别人。
2. 不要把自己的表格链接提交到本仓库或任何公开渠道。
3. `checkin.js` 本身**不含任何凭据**，可以安全分发。
4. 平台条款请自行遵守：同一自然人 / 手机号 / 设备视为同一用户，每日仅领一次，
   本工具仅用于个人账号的日常自动化。

---

## 排障

| 现象 | 原因 / 处理 |
| --- | --- |
| `HTTP 对象不可用，请添加「网络API」服务` | 编辑器工具栏 → 服务 → 添加「网络API」 |
| 运行就弹「服务授权」 | 正常，选允许；拒绝后重跑还会再弹 |
| G 列什么都没有 | A 列平台名不是小写、或 B 列不是合法 JSON（脚本会在 G 列写「账号JSON解析失败」） |
| Qoder 报 `活动列表为空` | 没到 10:00 窗口，或 B 列的 `device.machineToken` 缺失 / 与客户端版本不符 |
| TraeWork 报 `9004` | 缺设备 ID，重新 `show` 取带 device_id 的行 |
| 报 `刷新登录失败`（ima） | refresh_token 失效，重新 extract |
| 定时任务到点没跑 | 确认任务「执行脚本」选的是你保存的这个脚本；看文档权限是否变更过 |
| `to_wps.py` 说「没找到 X 的账号行」 | 该平台本机没登录过，或输出不是 `#` 分隔格式；改用 `--stdin` 手工粘一行进去 |
| `to_wps.py` 输出 `$wbEncrypted` 报错 | WorkBuddy 新版客户端加密了登录态，见上面「WorkBuddy 注意」那两条出路 |
| `to_wps.py` 提示缺 `cryptography` | 换个装了这个库的 Python 跑（脚本会自动尝试 py -3.10 / 常见安装路径）；或先 `pip install cryptography` |

---

## 维护

`checkin.js` 是唯一源文件，[deploy.html](deploy.html) 由它生成，改完脚本重跑：

```bash
python wps-airscript/build.py
```

会刷新部署页里内嵌的脚本和「复制脚本（N 行）」的文案，避免文档里的版本和真正部署的对不上。

---

## 和 Python 版的关系

| | Python 版（`platforms/`） | AirScript 版（本目录） |
| --- | --- | --- |
| 跑在哪 | 本机 / 青龙 / 服务器 | 金山文档云端 |
| 需要常开设备 | 青龙需要 | **不需要** |
| 账号配置 | 环境变量 `IMA` / `WORKBUDDY` / … | 表格 A/B 列 |
| 多账号 | 换行分隔 | 一行一个账号 |
| 推送 | 青龙自带通知 | D/E/F 列（Server酱 / PushPlus / 企业微信） |
| 接口行为 | 完全一致（本脚本按 Python 版逐个移植） | |

两边可以同时存在：本机用 Python 版跑，云端用 AirScript 版兜底，互不影响（幂等，不会重复领）。
