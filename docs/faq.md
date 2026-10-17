# FAQ · 常见问题

## 通用

### Q：脚本报 `no_account` / 提示未配置账号？

A：没读到对应平台的环境变量。青龙在「系统设置 → 环境变量」里新建（名称见各平台文档）；
本机跑就先 `set`/`export` 再用 `python checkin.py <平台>`。注意变量名区分大小写。

### Q：token 多久过期？过期了怎么办？

| 平台 | access token | refresh token | 过期后处理 |
| --- | --- | --- | --- |
| ima | 2 小时（脚本自动刷新） | 约 1 年 | 重新扫码登录 ima → `switchers/ima/switch_auth.py extract` → 更新环境变量 |
| WorkBuddy | 约 60 天 | - | 打开桌面端刷新登录态 → `switchers/workbuddy/switch_auth.py show` → 更新环境变量 |
| Qoder | 约 30 天（脚本自动刷新） | 约 1 年 | 打开 Qoder 登录 → `switchers/qoder/switch_auth.py show` → 更新环境变量 |
| TraeWork | 约两周 | 约半年 | 打开 TraeWork 登录 → `switchers/traework/switch_auth.py show` → 更新环境变量 |

ima/Qoder 脚本会在 token 临近过期时自动刷新，正常情况下不需要手动干预。

### Q：一天跑多次会重复领取吗？

A：不会。所有脚本都幂等：今日已签自动跳过（`skip_already_signed`/`skip_already_claimed`），
服务端领取接口本身也幂等。可以放心一天跑多次补漏。

### Q：青龙日志里怎么看结果？

A：每个账号输出一行 JSON，看 `action` 字段：`clicked`=领取成功，
`skip_already_signed`=今日已签，`error`=异常。汇总行在最后。

## ima

### Q：`refresh_failed`（刷新登录失败）？

A：refresh_token 失效（约 1 年）。完全退出 ima（含托盘）→ 重新扫码登录 →
重跑 `python switchers/ima/switch_auth.py extract` → 用 `show` 输出新行更新环境变量。

### Q：提取提示"未找到登录凭证"？

A：确认 1) ima 已在本机登录；2) 提取时已**完全退出** ima（含托盘图标）；
3) 必要时重新扫码登录后再提取。

### Q：`Cookie 使用了 v20(应用绑定)加密, 暂不支持`？

A：客户端升级了加密方案，当前脚本不支持，等待更新。

## WorkBuddy

### Q：`today_checked_in` 一直是 false 但实际已签？

A：已知问题——活动未开始时该字段不可靠，所以脚本不依赖它，直接调签到接口 + 响应判定。

### Q：接口 404？

A：域名必须用 `www.codebuddy.cn`（带 `/v2/`），`copilot.tencent.com` 会 404。

## Qoder

### Q：活动列表为空 / `no_campaign`？

A：三种可能：1) 没到 10:00(UTC+8) 领取窗口；2) 活动已下线；
3) **设备 JSON 缺失或版本不符**（只带 Bearer 头时接口返回 200 但 `campaigns:[]`，
这是最容易踩的坑）。回 Windows 重跑 `python switchers/qoder/switch_auth.py show` 取新行，
`QODER_VERSION` 可手动指定客户端版本号。

### Q：`token_expired`？

A：refreshToken 也失效了（约 1 年）。回 Windows 打开 Qoder 登录后重新 `show` 取号。

### Q：代理报错 `EOF occurred in violation of protocol`？

A：本地代理抖动，脚本已内置 3 次退避重试；持续报错就换个网络环境。

## TraeWork

### Q：服务端返回 `9004`？

A：缺少真实设备 ID。用 `switchers/traework/switch_auth.py show` 获取带第四段设备 ID 的
完整 token 行；不填时脚本会按 token 派生固定值兜底，但服务端可能不认。

### Q：服务端返回 `9074`？

A：服务端繁忙，脚本已自动重试 3 次（间隔 5 秒）；仍失败就过会儿再跑。

### Q：还原登录态失败/被覆盖？

A：还原前必须先**完全退出 TraeWork（含托盘）**，否则客户端退出时会用内存里的旧登录态
把文件覆盖回去。脚本检测到客户端运行时会拒绝还原。

## 其他

### Q：签到脚本要装依赖吗？

A：不要。四个平台签到脚本都是纯标准库。只有 `switchers/ima` 和 `switchers/traework`
的桌面端解密功能需要 `cryptography`（`.bat` 会自动安装）。

### Q：备份目录能拷贝到别的电脑用吗？

A：WorkBuddy 的备份是明文文件，可以；Qoder/TraeWork 的备份含 DPAPI/机器绑定加密数据，
**只能在同一台机器、同一个 Windows 用户下还原**。
