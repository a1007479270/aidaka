#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 checkin.js 生成一键复制页面 deploy.html。

用法:
    python build.py

checkin.js 是唯一的脚本源文件，改脚本后重跑本命令刷新 deploy.html，
避免文档里的脚本与真正部署的版本不一致。
"""
import html
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "checkin.js")
OUT = os.path.join(HERE, "deploy.html")

TEMPLATE_DOC_URL = "https://www.kdocs.cn/l/ckNJ04YURB8F"

PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ai 自动签到 · 金山文档 AirScript 部署页</title>
<style>
  :root {{
    --bg: #f6f7f9; --card: #ffffff; --ink: #1f2328; --muted: #656d76;
    --line: #d8dee4; --brand: #1a73e8; --brand-dark: #1557b0;
    --ok: #1a7f37; --code-bg: #0d1117; --code-ink: #c9d1d9;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 32px 20px 64px; background: var(--bg); color: var(--ink);
    font: 15px/1.7 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
          "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  }}
  .wrap {{ max-width: 940px; margin: 0 auto; }}
  h1 {{ font-size: 26px; margin: 0 0 6px; letter-spacing: -.3px; }}
  .sub {{ color: var(--muted); margin: 0 0 28px; }}
  .card {{
    background: var(--card); border: 1px solid var(--line); border-radius: 12px;
    padding: 22px 24px; margin-bottom: 18px;
  }}
  h2 {{ font-size: 17px; margin: 0 0 14px; display: flex; align-items: center; gap: 8px; }}
  .num {{
    display: inline-flex; align-items: center; justify-content: center;
    width: 22px; height: 22px; border-radius: 50%; background: var(--brand);
    color: #fff; font-size: 12px; font-weight: 600; flex: none;
  }}
  ol {{ margin: 0; padding-left: 22px; }}
  ol li {{ margin: 7px 0; }}
  a {{ color: var(--brand); text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  code {{
    background: #eff1f3; border-radius: 5px; padding: 1px 6px;
    font: 13px/1.5 ui-monospace, SFMono-Regular, Consolas, "Courier New", monospace;
  }}
  .btn {{
    display: inline-flex; align-items: center; gap: 9px; cursor: pointer;
    border: 0; border-radius: 9px; padding: 13px 26px; font-size: 15px; font-weight: 600;
    background: var(--brand); color: #fff; transition: background .15s, transform .06s;
  }}
  .btn:hover {{ background: var(--brand-dark); }}
  .btn:active {{ transform: translateY(1px); }}
  .btn.ok {{ background: var(--ok); }}
  .btn-row {{ display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin: 4px 0 2px; }}
  .hint {{ color: var(--muted); font-size: 13px; }}
  .linkbox {{
    display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
    background: #f0f6ff; border: 1px solid #cfe0ff; border-radius: 9px;
    padding: 11px 14px; margin: 10px 0 0;
    font: 13px/1.5 ui-monospace, SFMono-Regular, Consolas, monospace;
    word-break: break-all;
  }}
  .linkbox span {{ flex: 1 1 380px; color: #0b4bb3; }}
  .mini {{
    cursor: pointer; border: 1px solid #9fc0f5; background: #fff; color: var(--brand);
    border-radius: 7px; padding: 5px 12px; font-size: 12.5px; font-weight: 600; white-space: nowrap;
  }}
  .mini:hover {{ background: #eaf2ff; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 14px; margin: 4px 0 2px; table-layout: fixed; }}
  th, td {{ border: 1px solid var(--line); padding: 8px 11px; text-align: left; vertical-align: top; word-break: break-all; }}
  th:first-child, td:first-child {{ width: 128px; }}
  td code {{ word-break: break-all; }}
  th {{ background: #f6f8fa; font-weight: 600; white-space: nowrap; }}
  details {{ margin-top: 6px; }}
  summary {{ cursor: pointer; color: var(--brand); font-weight: 600; font-size: 14px; }}
  pre {{
    margin: 12px 0 0; padding: 16px 18px; border-radius: 10px; overflow: auto;
    max-height: 420px; background: var(--code-bg); color: var(--code-ink);
    font: 12.5px/1.6 ui-monospace, SFMono-Regular, Consolas, "Courier New", monospace;
    tab-size: 2;
  }}
  .warn {{
    background: #fff8e6; border: 1px solid #f0d48a; border-radius: 10px;
    padding: 14px 18px; margin: 0 0 18px; font-size: 14px;
  }}
  .warn b {{ color: #8a6100; }}
  ul {{ margin: 6px 0 0; padding-left: 20px; }}
  ul li {{ margin: 5px 0; }}
  footer {{ color: var(--muted); font-size: 13px; text-align: center; margin-top: 30px; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>ai 自动签到 · AirScript 部署页</h1>
  <p class="sub">零服务器：把 ima / WorkBuddy / Qoder / TraeWork 四个平台的每日签到交给金山文档云端定时执行。</p>

  <div class="warn">
    <b>先读这条：</b>账号 token 会明文存在表格里，而模板是「免登录可编辑」链接。
    填完账号后请把文档权限改成「仅指定人可编辑」，<b>不要把这个表格链接发给别人</b>。
  </div>

  <div class="card">
    <h2><span class="num">1</span>复制模板表格</h2>
    <p style="margin:0">打开下面这个空白模板，右上角「…」→ 另存为 / 创建副本，存到你自己的金山文档空间。</p>
    <div class="linkbox">
      <span id="tplurl">{tpl_url}</span>
      <button class="mini" onclick="copyTpl(this)">复制链接</button>
    </div>
  </div>

  <div class="card">
    <h2><span class="num">2</span>复制脚本，粘进 AirScript 编辑器</h2>
    <ol>
      <li>表格里点顶部菜单 <code>效率</code> → <code>高级开发</code> → <code>AirScript 脚本编辑器</code></li>
      <li>编辑器工具栏点「服务 / 立方体图标」→ 确认已有 <code>网络API</code>（没有就点「添加服务」加上）</li>
      <li>清空编辑器里的示例代码，点下面按钮复制，<code>Ctrl+V</code> 粘贴进去</li>
      <li>点保存（<code>Ctrl+S</code>），点运行（▶），首次会弹「服务授权」→ 选 <b>允许</b></li>
    </ol>
    <div class="btn-row" style="margin-top:16px">
      <button class="btn" id="copyBtn" onclick="copyScript()">
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="12" height="12" rx="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
        <span id="copyLabel">复制脚本（{lines} 行）</span>
      </button>
      <span class="hint">粘贴后直接能跑，不用改任何一行</span>
    </div>
    <details>
      <summary>展开预览脚本全文</summary>
      <pre id="src">{script_html}</pre>
    </details>
  </div>

  <div class="card">
    <h2><span class="num">3</span>把账号填进表格 B 列</h2>
    <p style="margin:0 0 10px">A 列填平台名（小写），B 列填该平台的账号 JSON，一行一个账号：</p>
    <table>
      <tr><th>平台（A 列）</th><th>账号 JSON（B 列）</th></tr>
      <tr><td><code>ima</code></td><td><code>{{"ima_uid":"","uid_type":"1","ima_guid":"","refresh_token":"","name":""}}</code></td></tr>
      <tr><td><code>workbuddy</code></td><td><code>{{"token":"","uid":"","name":""}}</code></td></tr>
      <tr><td><code>qoder</code></td><td><code>{{"name":"","refreshToken":"","accessToken":"","uid":"","device":{{"clientType":"10","machineOS":"Windows","machineHostname":"","machineId":"","machineToken":"","machineCode":"","machineType":"","version":""}}}}</code></td></tr>
      <tr><td><code>traework</code></td><td><code>{{"token":"","uid":"","device_id":"","name":""}}</code></td></tr>
    </table>
    <p class="hint" style="margin:12px 0 0">
      D / E / F 列可填 Server酱 SendKey、PushPlus token、企业微信机器人 Webhook，跑完自动推送汇总；不填就不推送。
      账号行从本仓库 <code>switchers/&lt;平台&gt;/switch_auth.py show</code> 取自本机登录态，别手抄。
    </p>
  </div>

  <div class="card">
    <h2><span class="num">4</span>挂上每日定时</h2>
    <ol>
      <li><code>效率</code> → <code>高级开发</code> → <code>定时任务</code> → 创建任务</li>
      <li>频率选 <b>每天</b>，时间建议 <b>10:30</b> 之后（Qoder 的活动 10:00 才开新一轮窗口，更早跑会撞到前一天）</li>
      <li>执行脚本选刚保存的那个，确认即可。之后关掉电脑也会照常跑</li>
    </ol>
  </div>

  <div class="card">
    <h2>运维要点</h2>
    <ul>
      <li>各平台接口都是<b>幂等</b>的：已签到会返回「今天已签到」，一天跑多次不会重复领，放心补跑。</li>
      <li><b>Qoder</b>：token 快过期会自动刷新，并把新 token <b>回写 B 列</b>，不用管。</li>
      <li><b>WorkBuddy</b>：token 约 60 天过期，过期后签到报鉴权失败，换掉 B 列那个 JSON 里的 <code>token</code> 即可。</li>
      <li><b>ima</b>：用 refresh_token 每次现换 access_token，只要 refresh_token 不失效就不用管。</li>
      <li><b>TraeWork</b>：JWT 约两周过期，过期后用 switcher 重新取一行。</li>
      <li>结果写在 G 列（最近一次动作 + 消息），C 列写脚本运行时间，方便回看有没有漏跑。</li>
    </ul>
  </div>

  <footer>
    脚本源文件同目录 <code>checkin.js</code>，本页面由 <code>build.py</code> 从它生成，改脚本后重跑即可刷新。
  </footer>
</div>

<script>
const SCRIPT = {script_json};

async function copyText(text, btn, okLabel) {{
  if (!btn.dataset.orig) btn.dataset.orig = btn.innerHTML;
  const old = btn.dataset.orig;
  try {{
    if (navigator.clipboard && window.isSecureContext) {{
      await navigator.clipboard.writeText(text);
    }} else {{
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.top = '-9999px';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
    }}
    btn.innerHTML = okLabel;
    btn.classList.add('ok');
    setTimeout(() => {{ btn.innerHTML = old; btn.classList.remove('ok'); }}, 1800);
  }} catch (e) {{
    alert('复制失败，请手动全选下方脚本复制：\\n' + e.message);
    const pre = document.getElementById('src');
    if (pre) {{ const r = document.createRange(); r.selectNodeContents(pre); const s = getSelection(); s.removeAllRanges(); s.addRange(r); }}
  }}
}}

function copyScript() {{
  const btn = document.getElementById('copyBtn');
  copyText(SCRIPT, btn, '<span>已复制，去编辑器粘贴</span>');
}}

function copyTpl(btn) {{
  copyText(document.getElementById('tplurl').textContent.trim(), btn, '已复制');
}}
</script>
</body>
</html>
"""


def main():
    with open(SRC, "r", encoding="utf-8") as f:
        script = f.read()
    lines = script.count("\n") + (0 if script.endswith("\n") else 1)
    out = PAGE.format(
        tpl_url=TEMPLATE_DOC_URL,
        lines=lines,
        script_html=html.escape(script, quote=False),
        script_json=json.dumps(script, ensure_ascii=False),
    )
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(out)
    print("生成 %s（脚本 %d 行 / %d 字节）" % (OUT, lines, len(script.encode("utf-8"))))


if __name__ == "__main__":
    main()
