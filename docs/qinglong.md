# 青龙面板部署指南

daily-checkin 的每个平台脚本都是**单文件自包含**（纯标准库、无跨文件依赖），
青龙部署只需要上传 `platforms/` 下对应的那一个文件，不需要上传整个仓库。

## 一、上传脚本

把需要的平台文件上传到青龙脚本目录（如 `/ql/data/scripts/`），重命名随意，路径对即可：

| 文件 | 平台 |
| --- | --- |
| `platforms/ima.py` | ima |
| `platforms/workbuddy.py` | WorkBuddy |
| `platforms/qoder.py` | Qoder |
| `platforms/traework.py` | TraeWork |

> 想一条命令跑全部平台，也可以上传整个仓库后在青龙里跑 `python checkin.py`，
> 但通常没必要——青龙按平台建多个定时任务更直观，日志也更好排查。

## 二、环境变量

青龙 → 系统设置 → 环境变量 → 新建，多账号用**换行**分隔：

| 名称 | 值 |
| --- | --- |
| `IMA` | `ima_uid#uid_type#ima_guid#refresh_token#备注` |
| `WORKBUDDY` | `ACCESS_TOKEN#UID#备注` |
| `QODER` | `ACCESS_TOKEN#REFRESH_TOKEN#UID#备注#设备JSON` |
| `TRAEWORK` | `ACCESS_TOKEN#UID#备注#设备ID` |

token 行用桌面端 switcher 一键获取（详见各平台文档），例如：

```bash
python switchers/qoder/switch_auth.py show
```

## 三、定时任务

青龙 → 定时任务 → 新建：

| 平台 | 命令 | 定时规则 | 说明 |
| --- | --- | --- | --- |
| ima | `task platforms/ima.py` | `0 9,21 * * *` | 一天 1~2 次 |
| WorkBuddy | `task platforms/workbuddy.py` | `0 9,21 * * *` | 一天 1~2 次 |
| Qoder | `task platforms/qoder.py` | `5 10,21 * * *` | **10:00 后才开放领取**，别在 10 点前跑 |
| TraeWork | `task platforms/traework.py` | `0 9,21 * * *` | 一天 1~2 次 |

脚本均幂等，一天跑多次不会重复领取，可放心多跑补漏。

## 四、通知与日志

- 每个账号输出**一行 JSON**，青龙通知可直接按 `action` 字段解析：
  `clicked`（领取成功）/ `skip_already_signed`（今日已签）/ `error`（异常）。
- 全部账号正常退出码 `0`，存在异常退出码 `1`，青龙据此判成败。
- 建议在青龙「通知」里配置渠道（钉钉/企业微信/Telegram 等），token 失效时能第一时间知道。

## 五、多账号维护建议

1. **token 集中放环境变量**：青龙环境变量里换行追加即可，不用改脚本。
2. **定期巡检**：某平台连续几天 `status=error`，多半是 token 过期，回 Windows
   重跑对应 `switchers/<平台>/switch_auth.py show` 更新。
3. **Qoder token 轮换**：设 `QD_STATE_FILE` 让脚本把刷新后的最新 token 行写回文件，
   定期复制回环境变量，减少重新取号次数。
4. **备份目录不要上传青龙**：`switchers/` 的备份目录含真实凭据，只放本机。

## 六、安全红线

- 不要把任何含真实 token 的文件提交到公开仓库（`.gitignore` 已挡，但手动上传/分享时也要当心）。
- 青龙环境变量等同账号钥匙，服务器/面板请设置强密码并开启双重验证。
