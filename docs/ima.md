# ima 自动签到

ima（ima.copilot 腾讯 AI 工作台）「每日登录福利」自动签到：每日签到 + 连签 7 天满签奖励自动领取。

- **奖励**：每日 **50 积分**（算力）；连签满 7 天额外 **+100 积分**，一周共 **450 积分**
- 签到脚本：`platforms/ima.py`（单文件自包含，零依赖）
- 凭证管理：`switchers/ima/switch_auth.py`（Windows，提取/备份/还原）

## 一、环境变量

青龙 → 系统设置 → 环境变量 → 新建：

| 名称 | 值 |
| --- | --- |
| `IMA` | `ima_uid#uid_type#ima_guid#refresh_token#备注`（多账号换行） |

示例：

```
10001#1#GUID-AAA#rt_xxx#主号
10002#1#GUID-BBB#rt_yyy#小号
```

也支持**单账号本地模式**：把凭证保存为脚本同目录的 `credentials.json`
（或用环境变量 `IMA_CRED_FILE` 指定路径），格式：

```json
{
  "ima_uid": "10001",
  "uid_type": "1",
  "ima_guid": "GUID-AAA",
  "refresh_token": "rt_xxx"
}
```

环境变量优先；未配置时才回退到 `credentials.json`。

## 二、取凭证（每个账号做一次）

ima 的凭证藏在客户端本地加密存储里，用本项目脚本一键提取（**ima 开着也能提取**，
脚本用共享读取打开 Cookie 库，不必退出客户端）：

```bash
python switchers/ima/switch_auth.py extract
```

产物 `switchers/ima/credentials.json` 即所需字段。然后：

```bash
python switchers/ima/switch_auth.py show
```

会直接打印青龙环境变量行，复制即用。

> 提取功能仅支持 Windows（需要 DPAPI 解出 Cookie 库主密钥），但**零第三方依赖**：
> AES-256-GCM 是脚本自带的纯标准库实现，不用 `pip install` 任何东西。

## 三、定时任务

- 命令：`task platforms/ima.py`（路径按青龙实际上传位置改）
- 定时规则：一天 1~2 次即可，推荐 `0 9,21 * * *`

## 四、输出字段

每个账号一行 JSON：

- `action=clicked` → 签到成功（`points` 本次获得积分）
- `action=skip_already_signed` → 今天已签到
- `action=refresh_failed` → refresh_token 失效，需重新扫码登录 ima 后重新 extract
- `action=structure_changed` → 活动改版，需更新脚本

满签奖励（连签 7 天）可领时会自动顺带领取，结果里 `weekly_bonus_claimed=true`。

## 五、关键实现说明

- `access_token` 仅 2 小时有效，脚本每次先用 `refresh_token` 换新，无需手动维护。
- 请求头 `x-ima-bkn` 是复刻 ima 页面 JS 的 djb2 签名，服务端不严格校验具体值。
- 接口与签名算法参考自公开项目 LeapYa/ima-qiandao。

## 六、多账号凭证管理（switchers/ima）

```bash
python switchers/ima/switch_auth.py            # 交互式菜单
python switchers/ima/switch_auth.py list       # 列出所有凭证备份
python switchers/ima/switch_auth.py backup     # 备份当前凭证(带时间戳)
python switchers/ima/switch_auth.py show       # 查看当前凭证 + 青龙环境变量行
python switchers/ima/switch_auth.py extract    # 从 ima 客户端提取凭证(Windows)
python switchers/ima/switch_auth.py restore <备份名或序号>   # 还原指定凭证
```

- 备份目录 `ima_cred_backup/` 跟随脚本自身存放，拷到任意目录都能用。
- 还原前会自动先备份当前凭证，防止丢失。
- 菜单 `[c]` 可用当前凭证立即签到一次（调用仓库 `platforms/ima.py`，
  可用环境变量 `IMA_CHECKIN_SCRIPT` 覆盖路径）。

## 七、常见问题

- **`refresh_failed`**：refresh_token 失效（约 1 年）。完全退出 ima → 重新扫码登录 →
  重跑 `extract` → 更新环境变量。
- **提取提示找不到凭证**：确认 ima 已登录、提取时已完全退出（含托盘）。
- **`v20(应用绑定)加密, 暂不支持`**：客户端升级了加密方案，需等待脚本更新。
