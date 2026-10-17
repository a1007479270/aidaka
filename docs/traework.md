# TraeWork 自动签到

TraeWork 国内个人版每日积分签到 + 桌面端登录态备份/切换。

- 签到脚本：`platforms/traework.py`（单文件自包含，零依赖）
- 登录态管理：`switchers/traework/switch_auth.py`（Windows，AES-128-CBC 解密，需 `cryptography`）

## 一、环境变量

青龙 → 系统设置 → 环境变量 → 新建：

| 名称 | 值 |
| --- | --- |
| `TRAEWORK` | `ACCESS_TOKEN#UID#备注#设备ID`（多账号换行） |

**只有 `ACCESS_TOKEN` 必填**，后三段可省略。示例：

```
eyJhbG...#1124000000000001#主号#3000000000000001
eyJhbG...#1124000000000002#小号
```

## 二、取 token（每个账号做一次）

在已登录 TraeWork 的 Windows 电脑上，**双击 `switchers/traework/switch_auth.bat` 选 `[2]`**，
脚本直接输出当前账号的 `ACCESS_TOKEN#UID#账号名#设备ID` 一行，**复制即可**填入青龙环境变量，
不用手动开文件、不用抓包。

命令行等价写法：

```bash
python switchers/traework/switch_auth.py show          # 交互输出（带填写指引）
python switchers/traework/switch_auth.py show > ql.txt # 重定向时只输出干净的一行
```

> 多账号：桌面端切换登录下一个账号（见第四节），再 `[2]` 输出，逐行贴进同一个环境变量。
> token 会过期（accessToken 约两周，refreshToken 约半年），过期后重取更新环境变量即可。

## 三、定时任务

- 命令：`task platforms/traework.py`（路径按实际上传位置改）
- 定时规则：一天 1~2 次，推荐 `0 9,21 * * *`

脚本**幂等**：先查状态，今日已签自动跳过，不会重复领。单账号失败不影响其他账号，
全部成功退出码 0，存在异常退出码 1（青龙据此判成败、发通知）。

## 四、输出字段

每个账号一行 JSON：

- `action=clicked` → 领取成功（`credits` 是当前积分）
- `action=skip_already_signed` → 今天已签到，跳过（`status=ok`）
- `action=disabled` → 该账号未开启签到功能
- `action=dry_run` → dry-run 模式，只查状态未领取
- `status=error` → 异常（多为 token 失效）

调试：`python platforms/traework.py --debug` 或设 `TRAEWORK_DEBUG=1`，打印接口原始响应。

实测输出：

```
=== TraeWork 签到开始，共 1 个账号 ===
{"remark": "用户示例", "uid": "1124000000000001", "status": "ok", "action": "clicked", "credits": 100, "msg": "success"}
=== 完成: 成功/已签 1 个（本次领取 1，今日已签 0），异常 0 个 ===
```

## 五、关键实现说明

- 接口域名必须用 `api.trae.cn`，路径带 `/trae/api/v2/ug/checkin_credits/`。
- 请求体固定为 `{"req_source": 2}`（2 = TraeWork(lite)，TraeCode IDE 为 1）；
  鉴权头是 `Authorization: Cloud-IDE-JWT <token>`（不是 Bearer）。
- 请求必须带 `x-device-id`：`[2]` 导出的第四段就是真实设备 ID；
  不填脚本会按 token 派生固定值兜底，但服务端可能返回 `9004`。
- 服务端繁忙返回 `9074` 时自动重试 3 次（间隔 5 秒）。
- 青龙端**零依赖**：只传 `platforms/traework.py` 一个文件即可，
  不需要 `switch_auth.py`、备份文件或 `cryptography`。

## 六、桌面端多账号切换（switchers/traework）

TraeWork 桌面端是**单账号登录**，登录态加密（AES-128-CBC）存在本地：

```
%APPDATA%\TRAE SOLO CN\User\globalStorage\storage.json
```

（旧版客户端目录名为 `Trae CN` / `Trae`，脚本会依次探测并试解密。）

与账号绑定的是三个键：`iCubeAuthInfo://icube.cloudide`（登录态）、
`iCubeAuthInfo://usertag`（区域映射）、`iCubeServerData://icube.cloudide`（服务端缓存）。
备份/还原这几个键，即可实现多账号并存与切换，主号不丢失。

双击 `switch_auth.bat` 进入菜单：

```
=== 当前桌面端登录态 ===
  uid=1124000000000001  昵称=用户示例  区域=CN
  设备ID=3000000000000001
  token过期=2026-10-28T17:28:46.105Z

请选择操作:
  [1] 备份当前登录态（仅备份，不还原）
  [2] 输出当前 TRAEWORK 信息 (ACCESS_TOKEN#UID#账号名#设备ID)
  [3] 还原 xxx  (uid / 昵称)   <- 有备份时才出现
  [0] 取消
```

多账号流程：登录 A → `[1]` 备份；切到客户端登录 B → `[1]` 备份；
以后想换回谁，双击 → 选对应账号的 `[还原]` 项即可。

- **冷启动友好**：备份目录为空也能进菜单，先 `[1]` 生成第一个备份，之后才出现还原项。
- 还原前会**自动备份当前登录态**（文件名带 `before-restore`），防止丢号。
- 检测到客户端正在运行时拒绝还原——必须先**完全退出 TraeWork（含托盘）**，
  否则客户端退出时会用内存里的旧登录态把文件覆盖回去。
- 脚本目录跟随自身：三个文件 + `traework_auth_backup/` 放一起，拷到任意目录/电脑都能用。

命令行模式：

```bash
python switchers/traework/switch_auth.py            # 交互式菜单
python switchers/traework/switch_auth.py list       # 仅列出所有备份
python switchers/traework/switch_auth.py backup     # 仅备份当前登录态
python switchers/traework/switch_auth.py show       # 仅输出当前 TRAEWORK 信息
```

### 依赖

解密 storage.json 需要 `cryptography`。双击 `switch_auth.bat` 会自动检测并安装；
手动安装：`python -m pip install cryptography`。青龙里的 `platforms/traework.py` 不需要它。

## 七、本机定时签到（可选）

不装青龙、本机常开时，用 Windows 计划任务每天跑一次：

```bash
schtasks /Create /TN TraeWorkAutoCheckin /SC DAILY /ST 09:00 /F ^
  /TR "cmd /c cd /d <仓库路径> && set /p TRAEWORK=<ql.txt && python platforms\traework.py"
```

其中 `ql.txt` 由 `python switchers/traework/switch_auth.py show > ql.txt` 生成（内容就是 token 行）。

管理：`schtasks /Query /TN TraeWorkAutoCheckin /V /FO LIST`，
卸载：`schtasks /Delete /TN TraeWorkAutoCheckin /F`。

## 八、合规提醒

请遵守 TraeWork 活动条款：同一手机号/账号/设备 ID/IP 关联的多个账号视为同一用户，
严禁多账号套利、刷量等作弊行为。本工具集用于个人账号的日常自动化，请勿用于违规用途。
