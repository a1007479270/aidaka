// ============================================================
// aidaka · AI 打卡机 - 四平台每日签到 (AirScript 版)
//
// 来源: aidaka / wps-airscript/checkin.js
// 说明文档: wps-airscript/README.md    部署页: wps-airscript/deploy.html
// 模板表格: https://www.kdocs.cn/l/ckNJ04YURB8F
//
// 依赖服务: 网络API (编辑器工具栏 → 服务 → 网络API，已添加则忽略)
// 定时任务: 效率 → 高级开发 → 定时任务，建议「每天 10:30」
//           (Qoder 领取窗口每天 10:00 才开，别早于 10 点)
//
// 表格布局（工作表「签到配置」）:
//   A=平台  B=账号JSON  C=是否签到(脚本写入)  D=Server酱  E=PushPlus
//   F=企业微信Webhook  G=签到结果(脚本写入)
//
// 账号JSON 格式（B列，一行一个账号，平台名填在A列）:
//   ima:       {"ima_uid":"","uid_type":"1","ima_guid":"","refresh_token":"","name":""}
//   workbuddy: {"token":"","uid":"","name":""}
//   qoder:     {"name":"","refreshToken":"","accessToken":"","uid":"","device":{"clientType":"10","machineOS":"Windows","machineHostname":"","machineId":"","machineToken":"","machineCode":"","machineType":"","version":""}}
//   traework:  {"token":"","uid":"","device_id":"","name":""}
//
// 说明: 各平台接口幂等，已签到会返回"今天已签到"，可放心一天多次运行。
// ============================================================

// ---------- 基础工具 ----------
function pad2(n) { return (n < 10 ? "0" : "") + n; }

// 固定输出北京时间，避免云端时区差异
function nowBJ() {
  var d = new Date(Date.now() + 8 * 3600 * 1000);
  return d.getUTCFullYear() + "-" + pad2(d.getUTCMonth() + 1) + "-" + pad2(d.getUTCDate()) +
    " " + pad2(d.getUTCHours()) + ":" + pad2(d.getUTCMinutes()) + ":" + pad2(d.getUTCSeconds());
}

function sleep(ms) {
  var start = Date.now();
  while (Date.now() - start < ms) { /* 同步等待 */ }
}

// ---------- HTTP 封装（AirScript 网络API，同步返回） ----------
function httpReq(method, url, headers, body, timeout) {
  timeout = timeout || 30000;
  var opts = { method: method, headers: headers || {}, timeout: timeout };
  if (body !== null && body !== undefined) opts.body = body;
  if (typeof HTTP !== "undefined" && typeof HTTP.fetch === "function") {
    return HTTP.fetch(url, opts);
  }
  if (typeof HTTP !== "undefined" && typeof HTTP.get === "function" && method === "GET") {
    return HTTP.get(url, { headers: headers || {} });
  }
  if (typeof HTTP !== "undefined" && typeof HTTP.post === "function" && method === "POST") {
    return HTTP.post(url, { headers: headers || {}, body: body });
  }
  throw new Error("HTTP 对象不可用，请在编辑器工具栏→服务→添加「网络API」");
}

function respStatus(resp) {
  if (!resp) return 0;
  if (resp.status !== undefined && resp.status !== null) return resp.status;
  if (resp.statusCode !== undefined && resp.statusCode !== null) return resp.statusCode;
  return 0;
}

function respText(resp) {
  var txt = "";
  try { txt = resp.text(); } catch (e) { }
  if (txt === null || txt === undefined) txt = "";
  return String(txt);
}

// 统一取 JSON：优先 json()，失败则解析 text()
function respJson(resp) {
  try {
    var j = resp.json();
    if (j !== null && j !== undefined) return j;
  } catch (e) { }
  var txt = respText(resp);
  if (!txt) return {};
  try { return JSON.parse(txt); } catch (e) { return { raw: txt.slice(0, 300) }; }
}

// ---------- 表格读写 ----------
function getSheet() {
  try { return Application.Sheets.Item("签到配置"); } catch (e) { return Application.ActiveSheet; }
}

function readCell(sheet, addr) {
  try {
    var v = sheet.Range(addr).Text;
    if (v === null || v === undefined) v = sheet.Range(addr).Value2;
    return v === null || v === undefined ? "" : String(v);
  } catch (e) { return ""; }
}

function writeCell(sheet, addr, val) {
  try { sheet.Range(addr).Value2 = val; return true; }
  catch (e) { console.log("[警告] 写单元格 " + addr + " 失败: " + e); return false; }
}

// ---------- 推送 ----------
function sendNotify(sct, pp, wx, title, text) {
  var sent = [];
  if (sct) {
    try {
      var r = httpReq("POST", "https://sctapi.ftqq.com/" + sct + ".send",
        { "Content-Type": "application/x-www-form-urlencoded" },
        "title=" + encodeURIComponent(title) + "&desp=" + encodeURIComponent(text));
      sent.push("Server酱:" + respStatus(r));
    } catch (e) { sent.push("Server酱失败:" + e); }
  }
  if (pp) {
    try {
      var r2 = httpReq("POST", "https://www.pushplus.plus/send",
        { "Content-Type": "application/json" },
        JSON.stringify({ token: pp, title: title, content: text }));
      sent.push("PushPlus:" + respStatus(r2));
    } catch (e) { sent.push("PushPlus失败:" + e); }
  }
  if (wx) {
    try {
      var r3 = httpReq("POST", wx,
        { "Content-Type": "application/json" },
        JSON.stringify({ msgtype: "text", text: { content: title + "\n" + text } }));
      sent.push("企业微信:" + respStatus(r3));
    } catch (e) { sent.push("企业微信失败:" + e); }
  }
  return sent.join(" ");
}

// ---------- ima（腾讯AI工作台） ----------
function toInt32(v) {
  v = v & 0xFFFFFFFF;
  return v >= 0x80000000 ? v - 0x100000000 : v;
}

// 复刻 ima 页面 JS 的 djb2 签名，输出 x-ima-bkn 头
function bkn(token) {
  var result = 5381;
  for (var i = 0; i < token.length; i++) {
    result = toInt32(result + toInt32(toInt32(result) << 5) + token.charCodeAt(i));
  }
  return toInt32(result) & 0x7FFFFFFF;
}

function imaCheckin(acc) {
  var BASE = "https://ima.qq.com";
  // 1) refresh_token 换 access_token（2小时有效）
  var refreshBody = JSON.stringify({
    userId: acc.ima_uid || "",
    refreshToken: acc.refresh_token || "",
    tokenType: -1
  });
  var refreshHeaders = {
    "Content-Type": "application/json",
    "from_browser_ima": "1",
    "extension_version": "5.17.2",
    "x-ima-cookie": "IMA-GUID=" + (acc.ima_guid || "") + "; PLATFORM=H5"
  };
  var r1 = httpReq("POST", BASE + "/cgi-bin/auth_login/refresh", refreshHeaders, refreshBody);
  var d1 = respJson(r1);
  var token = d1.token || "";
  if (d1.code !== 0 || !token) {
    return { status: "error", action: "refresh_failed",
      msg: "刷新登录失败 code=" + d1.code + " msg=" + (d1.msg || "") + "（refresh_token 可能已失效，需重新提取）" };
  }

  // 2) 带签名的鉴权头
  var cookieParts = [
    "IMA-UID=" + (acc.ima_uid || ""),
    "IMA-TOKEN=" + token,
    "IMA-REFRESH-TOKEN=" + (acc.refresh_token || ""),
    "UID-TYPE=" + (acc.uid_type || "1"),
    "IMA-GUID=" + (acc.ima_guid || ""),
    "PLATFORM=H5"
  ];
  function authHeaders() {
    return {
      "Content-Type": "application/json",
      "from_browser_ima": "1",
      "extension_version": "5.17.2",
      "x-ima-cookie": cookieParts.join("; "),
      "x-ima-bkn": String(bkn(token))
    };
  }

  // 3) 查询活动信息
  var r2 = httpReq("POST", BASE + "/cgi-bin/daily_login_activity/get_activity_info", authHeaders(), "{}");
  var info = respJson(r2);
  if (info.code !== 0) {
    return { status: "error", action: "query_failed",
      msg: "查询活动失败 code=" + info.code + " msg=" + (info.msg || "") };
  }
  var today = null, bonus = null;
  var infos = info.infos || [];
  for (var i = 0; i < infos.length; i++) {
    if (infos[i].top === "今日") today = infos[i];
    if (infos[i].top === "满签奖励") bonus = infos[i];
  }
  if (!today) {
    return { status: "error", action: "structure_changed", msg: "未找到今日条目，活动可能已改版" };
  }

  var result = { status: "ok", action: "", msg: "" };
  var st = today.status;
  if (st === 3) {           // 可领取
    var r3 = httpReq("POST", BASE + "/cgi-bin/daily_login_activity/check_in", authHeaders(), JSON.stringify({ type: 1 }));
    var d3 = respJson(r3);
    if (d3.code === 0) {
      result.action = "clicked";
      result.points = d3.rewardReceived || today.reward;
      result.msg = "签到成功";
    } else if (/已签到|请明天/.test(JSON.stringify(d3))) {
      result.action = "skip_already_signed";
      result.msg = "今天已签到";
    } else {
      result.status = "error";
      result.action = "checkin_failed";
      result.msg = "code=" + d3.code + " msg=" + (d3.msg || "");
    }
  } else if (st === 2) {    // 已领取
    result.action = "skip_already_signed";
    result.msg = "今天已签到";
  } else {
    result.action = "not_available";
    result.msg = "今天不可签到 (status=" + st + ")";
  }

  // 4) 满签奖励（连签7天）自动顺带领取
  if (bonus && bonus.status === 3) {
    var r4 = httpReq("POST", BASE + "/cgi-bin/daily_login_activity/check_in", authHeaders(), JSON.stringify({ type: 2 }));
    var d4 = respJson(r4);
    if (d4.code === 0) result.msg += "；满签奖励已领取";
  }
  return result;
}

// ---------- WorkBuddy（腾讯 CodeBuddy） ----------
function wbCheckin(acc) {
  var BASE = "https://www.codebuddy.cn";
  var headers = {
    "Authorization": "Bearer " + (acc.token || ""),
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) WorkBuddyCheckin/1.0",
    "Accept": "application/json, text/plain, */*",
    "Origin": BASE,
    "Referer": BASE + "/"
  };
  var r = httpReq("POST", BASE + "/v2/billing/meter/daily-checkin", headers, "{}");
  var st = respStatus(r);
  var body = respJson(r);
  var text = JSON.stringify(body);
  var msg = body.msg || "";
  if (/已签到|明天再来|请明天|already/i.test(text)) {
    return { status: "ok", action: "skip_already_signed", msg: msg || "今天已签到" };
  }
  var code = body.code;
  var data = body.data || {};
  if (code === 0 || /^(OK|SUCCESS)$/i.test(msg) || /成功/.test(msg)) {
    var points = (data && (data.credit || data.points || data.point || data.reward)) || body.points || body.reward;
    return { status: "ok", action: "clicked", points: points, msg: msg || "领取成功" };
  }
  return { status: "error", action: "checkin_failed", msg: "HTTP " + st + " " + text.slice(0, 300) };
}

// ---------- Qoder（CN 个人版） ----------
function qoderCheckin(acc) {
  var BASE = (acc.base || "https://openapi.qoder.com.cn").replace(/\/$/, "");
  var COSY = {
    clientType: "Cosy-ClientType",
    machineOS: "Cosy-MachineOS",
    machineHostname: "Cosy-MachineHostname",
    machineId: "Cosy-MachineId",
    machineToken: "Cosy-MachineToken",
    machineCode: "Cosy-MachineCode",
    machineType: "Cosy-MachineType",
    version: "Cosy-Version"
  };
  var device = acc.device || {};
  if (!device.machineToken) {
    return { status: "error", action: "no_device", msg: "缺少设备标识(Cosy-MachineToken)，活动接口不会下发活动" };
  }
  function headers(token) {
    var h = {
      "Accept": "application/json",
      "Content-Type": "application/json",
      "User-Agent": "Qoder/claim"
    };
    for (var k in COSY) {
      if (device[k] !== undefined && device[k] !== null && String(device[k]) !== "") {
        h[COSY[k]] = String(device[k]);
      }
    }
    if (!h["Cosy-ClientType"]) h["Cosy-ClientType"] = "10";
    if (token) h["Authorization"] = "Bearer " + token;
    return h;
  }
  function refreshToken() {
    var r = httpReq("POST", BASE + "/api/v1/deviceToken/refresh", headers(null),
      JSON.stringify({ refresh_token: acc.refreshToken || "" }));
    var d = respJson(r);
    if (respStatus(r) !== 200) {
      return { token: null, err: "刷新失败 HTTP " + respStatus(r) + " " + JSON.stringify(d).slice(0, 200) };
    }
    var tk = d.token || d.accessToken || d.access_token || "";
    if (!tk) return { token: null, err: "刷新响应里没有 token" };
    acc.accessToken = tk;
    if (d.refreshToken || d.refresh_token) acc.refreshToken = d.refreshToken || d.refresh_token;
    return { token: tk, err: "" };
  }

  var token = acc.accessToken || acc.token || "";
  if (!token) {
    var rf = refreshToken();
    if (!rf.token) return { status: "error", action: "token_expired", msg: rf.err };
    token = rf.token;
  }

  var r = httpReq("GET", BASE + "/sash/api/v1/me/campaigns", headers(token), null);
  var st = respStatus(r);
  var data = respJson(r);
  if (st === 401) {
    var rf2 = refreshToken();
    if (!rf2.token) return { status: "error", action: "token_expired", msg: rf2.err };
    token = rf2.token;
    r = httpReq("GET", BASE + "/sash/api/v1/me/campaigns", headers(token), null);
    st = respStatus(r);
    data = respJson(r);
  }
  if (st !== 200) {
    return { status: "error", action: "campaign_failed", msg: "HTTP " + st + " " + JSON.stringify(data).slice(0, 300) };
  }
  var campaigns = data.campaigns || [];
  if (!campaigns.length) {
    return { status: "ok", action: "no_campaign",
      msg: "活动列表为空：可能未到10:00窗口、活动已下线，或设备头与客户端版本不符" };
  }

  var now = Date.now();
  var UNCLAIMED = ["UNCLAIMED", "NOT_CLAIMED", "PENDING", "AVAILABLE", "CLAIMABLE"];
  var pending = [];
  for (var i = 0; i < campaigns.length; i++) {
    var c = campaigns[i];
    if (!c.campaignId) continue;
    var cst = String(c.claimStatus || "").toUpperCase();
    if (cst === "CLAIMED") continue;
    var start = c.startAt || 0, end = c.endAt || 0;
    var inWindow = (!start || now >= start) && (!end || now <= end);
    if (UNCLAIMED.indexOf(cst) >= 0 || (inWindow && !cst)) pending.push(c);
  }
  if (!pending.length) {
    return { status: "ok", action: "skip_already_claimed", msg: "本轮已领" };
  }

  var gained = 0, failed = [];
  for (var j = 0; j < pending.length; j++) {
    var c2 = pending[j];
    var key = c2.campaignKey || c2.campaignId;
    var expect = (c2.benefit || {}).amount || 0;
    var r2 = httpReq("POST", BASE + "/sash/api/v1/me/campaigns/" + c2.campaignId + "/claim", headers(token), "{}");
    var st2 = respStatus(r2);
    var d2 = respJson(r2);
    if (st2 === 401) {
      var rf3 = refreshToken();
      if (!rf3.token) { failed.push(key + ":token失效"); break; }
      token = rf3.token;
      r2 = httpReq("POST", BASE + "/sash/api/v1/me/campaigns/" + c2.campaignId + "/claim", headers(token), "{}");
      st2 = respStatus(r2);
      d2 = respJson(r2);
    }
    var claimStatus = String(d2.status || "").toUpperCase();
    if (st2 === 200 && ["CLAIMED", "REPLAYED", "SUCCESS"].indexOf(claimStatus) >= 0) {
      if (d2.replayed) continue;   // 服务端认为已领，业务正常
      gained += Number((d2.benefit || {}).amount || expect || 0);
    } else {
      failed.push(key + ":HTTP" + st2 + " " + JSON.stringify(d2).slice(0, 120));
    }
  }
  if (failed.length) {
    return { status: gained > 0 ? "ok" : "error", action: "claim_failed",
      msg: failed.join("; ") + (gained ? "（已领 " + gained + " Credits）" : "") };
  }
  return { status: "ok", action: "clicked", credits: gained, msg: "领取成功 " + gained + " Credits" };
}

// ---------- TraeWork（国内个人版） ----------
function traeworkCheckin(acc) {
  var BASE = "https://api.trae.cn";
  var token = acc.token || "";
  var deviceId = acc.device_id || "";
  function headers() {
    return {
      "Authorization": "Cloud-IDE-JWT " + token,
      "Content-Type": "application/json",
      "Accept": "application/json",
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) TraeWorkCheckin/1.0",
      "X-User-Region": "CN",
      "x-device-id": deviceId
    };
  }
  // 1) 查状态（幂等）
  var r = httpReq("POST", BASE + "/trae/api/v2/ug/checkin_credits/status", headers(), JSON.stringify({ req_source: 2 }));
  var st = respStatus(r);
  var status = respJson(r);
  if (st !== 200 || status.checked_in === undefined) {
    return { status: "error", action: "query_failed",
      msg: "查询签到状态失败（HTTP " + st + "）：" + (status.message || JSON.stringify(status).slice(0, 200)) };
  }
  if (status.checked_in) {
    return { status: "ok", action: "skip_already_signed", msg: "今天已签到", credits: status.credits };
  }
  if (status.enable === false) {
    return { status: "ok", action: "disabled", msg: "该账号未开启签到功能" };
  }
  // 2) 领取（9074 服务端繁忙自动重试）
  for (var attempt = 0; attempt < 4; attempt++) {
    var r2 = httpReq("POST", BASE + "/trae/api/v2/ug/checkin_credits/claim", headers(), JSON.stringify({ req_source: 2 }));
    var st2 = respStatus(r2);
    var resp = respJson(r2);
    if (st2 === 200 && resp.code === 0) {
      var data = resp.data || {};
      return { status: "ok", action: "clicked",
        credits: data.credits !== undefined ? data.credits : status.credits,
        msg: resp.message || "签到成功" };
    }
    var bizCode = resp.code;
    var msg = resp.message || JSON.stringify(resp);
    if (bizCode === 9074 && attempt < 3) { sleep(5000); continue; }
    var m = "签到失败（HTTP " + st2 + "）：" + msg;
    if (bizCode === 9074) m += "（服务端繁忙，已重试多次）";
    if (bizCode === 9004) m += "；请重新获取带设备ID的账号配置";
    return { status: "error", action: "claim_failed", msg: m };
  }
  return { status: "error", action: "claim_failed", msg: "重试后仍失败" };
}

// ---------- 主流程 ----------
function main() {
  var sheet = getSheet();
  var rows = [];
  var MAXROW = 30;
  for (var r = 2; r <= MAXROW; r++) {
    var platform = readCell(sheet, "A" + r).replace(/^\s+|\s+$/g, "").toLowerCase();
    if (!platform) continue;
    var accountJson = readCell(sheet, "B" + r).replace(/^\s+|\s+$/g, "");
    if (!accountJson) continue;
    var acc;
    try { acc = JSON.parse(accountJson); }
    catch (e) {
      writeCell(sheet, "G" + r, "账号JSON解析失败: " + e);
      continue;
    }
    var origToken = acc.accessToken || acc.token || "";
    var sct = readCell(sheet, "D" + r).replace(/^\s+|\s+$/g, "");
    var pp = readCell(sheet, "E" + r).replace(/^\s+|\s+$/g, "");
    var wx = readCell(sheet, "F" + r).replace(/^\s+|\s+$/g, "");

    var res;
    try {
      if (platform === "ima") res = imaCheckin(acc);
      else if (platform === "workbuddy") res = wbCheckin(acc);
      else if (platform === "qoder") res = qoderCheckin(acc);
      else if (platform === "traework") res = traeworkCheckin(acc);
      else res = { status: "error", action: "unknown_platform", msg: "未知平台: " + platform };
    } catch (e) {
      res = { status: "error", action: "exception", msg: String(e).slice(0, 200) };
    }

    // token 轮换后写回 B 列（qoder）
    var newToken = acc.accessToken || acc.token || "";
    if (platform === "qoder" && newToken && newToken !== origToken) {
      try {
        writeCell(sheet, "B" + r, JSON.stringify(acc));
        console.log("[" + platform + "] token 已刷新并写回 B" + r);
      } catch (e) { console.log("[警告] token 写回失败: " + e); }
    }

    // 写运行时间与结果
    writeCell(sheet, "C" + r, nowBJ());
    var name = acc.name || acc.uid || acc.remark || "";
    var detail = "[" + platform + "] " + name + " " + res.action + ": " + (res.msg || "");
    if (res.points !== undefined && res.points !== null) detail += " (+" + res.points + ")";
    if (res.credits !== undefined && res.credits !== null) detail += " (" + res.credits + " Credits)";
    writeCell(sheet, "G" + r, detail.slice(0, 500));
    console.log(detail);

    rows.push({ platform: platform, name: name, res: res, sct: sct, pp: pp, wx: wx });
    sleep(1500);   // 账号间间隔，降低风控
  }

  if (!rows.length) {
    console.log("没有读取到任何账号（A列平台名 + B列账号JSON）");
    return;
  }

  // 汇总推送（按推送渠道配置去重）
  var channels = {};
  for (var i = 0; i < rows.length; i++) {
    var row = rows[i];
    if (!row.sct && !row.pp && !row.wx) continue;
    var key = row.sct + "|" + row.pp + "|" + row.wx;
    if (!channels[key]) channels[key] = { sct: row.sct, pp: row.pp, wx: row.wx, lines: [] };
    var line = "[" + row.platform + "] " + row.name + " → " + row.res.action + ": " + (row.res.msg || "");
    channels[key].lines.push(line);
  }
  var okCount = 0, errCount = 0;
  for (var m = 0; m < rows.length; m++) {
    if (rows[m].res.status === "ok") okCount++; else errCount++;
  }
  var title = "ai自动签到 " + nowBJ().slice(0, 10) + "（正常" + okCount + "/异常" + errCount + "）";
  for (var k in channels) {
    var ch = channels[k];
    var r = sendNotify(ch.sct, ch.pp, ch.wx, title, ch.lines.join("\n"));
    console.log("推送结果: " + r);
  }
  console.log("=== 完成: 正常 " + okCount + " 个, 异常 " + errCount + " 个 ===");
}

main();
