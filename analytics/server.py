#!/usr/bin/env python3
import base64
import datetime as dt
import html
import json
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


DB_PATH = os.environ.get("ANALYTICS_DB", "analytics.sqlite3")
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
PORT = int(os.environ.get("ANALYTICS_PORT", "8787"))


def now_text():
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def db():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            event_type TEXT NOT NULL,
            page TEXT,
            path TEXT,
            title TEXT,
            feature TEXT,
            href TEXT,
            referrer_host TEXT,
            device TEXT
        )
        """
    )
    return conn


def safe(value, limit=180):
    if not isinstance(value, str):
        return ""
    return value.replace("\x00", "").strip()[:limit]


def referrer_host(referrer):
    try:
        return safe(urlparse(referrer).netloc, 120)
    except Exception:
        return ""


def query_stats():
    conn = db()
    today = dt.datetime.utcnow().date().isoformat()
    week_ago = (dt.datetime.utcnow() - dt.timedelta(days=7)).replace(microsecond=0).isoformat() + "Z"

    def one(sql, args=()):
        return conn.execute(sql, args).fetchone()[0]

    def rows(sql, args=()):
        return [dict(row) for row in conn.execute(sql, args).fetchall()]

    stats = {
        "todayPageViews": one(
            "SELECT COUNT(*) FROM events WHERE event_type='page_view' AND substr(created_at,1,10)=?",
            (today,),
        ),
        "todayClicks": one(
            "SELECT COUNT(*) FROM events WHERE event_type='feature_click' AND substr(created_at,1,10)=?",
            (today,),
        ),
        "weekPageViews": one(
            "SELECT COUNT(*) FROM events WHERE event_type='page_view' AND created_at>=?",
            (week_ago,),
        ),
        "weekClicks": one(
            "SELECT COUNT(*) FROM events WHERE event_type='feature_click' AND created_at>=?",
            (week_ago,),
        ),
        "topFeatures": rows(
            """
            SELECT COALESCE(NULLIF(feature,''), href, '未知功能') AS name, COUNT(*) AS count
            FROM events
            WHERE event_type='feature_click' AND created_at>=?
            GROUP BY name
            ORDER BY count DESC, name ASC
            LIMIT 20
            """,
            (week_ago,),
        ),
        "topPages": rows(
            """
            SELECT COALESCE(NULLIF(page,''), '/') AS name, COUNT(*) AS count
            FROM events
            WHERE event_type='page_view' AND created_at>=?
            GROUP BY name
            ORDER BY count DESC, name ASC
            LIMIT 20
            """,
            (week_ago,),
        ),
        "devices": rows(
            """
            SELECT COALESCE(NULLIF(device,''), 'unknown') AS name, COUNT(*) AS count
            FROM events
            WHERE created_at>=?
            GROUP BY name
            ORDER BY count DESC
            """,
            (week_ago,),
        ),
        "recent": rows(
            """
            SELECT created_at, event_type, page, feature, device
            FROM events
            ORDER BY id DESC
            LIMIT 30
            """
        ),
    }
    conn.close()
    return stats


def admin_html():
    return """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>百宝箱数据后台</title>
<style>
body{margin:0;background:#070b10;color:#eaf0f7;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:28px 18px 48px}
.hero{border:1px solid #2b4058;border-radius:18px;padding:22px;background:linear-gradient(135deg,rgba(89,25,35,.34),rgba(12,19,29,.92));box-shadow:0 18px 50px rgba(0,0,0,.35)}
h1{margin:0;color:#f2cf62;font-size:30px}.muted{color:#91a2b6}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:18px 0}
.card,.panel{border:1px solid #263b52;border-radius:16px;background:rgba(10,17,26,.88);padding:18px}.num{font-size:34px;color:#ffd95e;font-weight:800}
.panel{margin-top:16px}h2{margin:0 0 12px;color:#f2cf62;font-size:20px}
.row{display:flex;justify-content:space-between;gap:14px;border-bottom:1px solid rgba(66,91,118,.35);padding:10px 0}.row:last-child{border-bottom:0}
.bar{height:8px;border-radius:99px;background:#182636;overflow:hidden;margin-top:6px}.bar i{display:block;height:100%;background:linear-gradient(90deg,#b83d3d,#f2cf62)}
.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}.tag{color:#70d9a6}
@media(max-width:760px){.grid,.two{grid-template-columns:1fr}.wrap{padding:18px 12px}.num{font-size:28px}}
</style>
</head>
<body>
<main class="wrap">
<section class="hero">
<h1>百宝箱数据后台</h1>
<p class="muted">只统计页面访问和功能点击，不记录搜索内容。</p>
</section>
<section class="grid" id="metrics"></section>
<section class="two">
<div class="panel"><h2>功能点击排行（近7天）</h2><div id="features"></div></div>
<div class="panel"><h2>页面访问排行（近7天）</h2><div id="pages"></div></div>
</section>
<section class="two">
<div class="panel"><h2>设备分布（近7天）</h2><div id="devices"></div></div>
<div class="panel"><h2>最近事件</h2><div id="recent"></div></div>
</section>
</main>
<script>
function esc(s){return String(s||'').replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function rows(el, data){
  var max=Math.max(1,...data.map(function(x){return x.count||1}))
  el.innerHTML=data.length?data.map(function(x){return '<div class="row"><span>'+esc(x.name)+'</span><b>'+x.count+'</b></div><div class="bar"><i style="width:'+Math.round((x.count/max)*100)+'%"></i></div>'}).join(''):'<p class="muted">暂无数据</p>'
}
fetch('/admin/stats').then(function(r){return r.json()}).then(function(s){
  metrics.innerHTML=[
    ['今日访问',s.todayPageViews],['今日点击',s.todayClicks],['7天访问',s.weekPageViews],['7天点击',s.weekClicks]
  ].map(function(x){return '<div class="card"><div class="muted">'+x[0]+'</div><div class="num">'+x[1]+'</div></div>'}).join('')
  rows(features,s.topFeatures); rows(pages,s.topPages); rows(devices,s.devices)
  recent.innerHTML=s.recent.length?s.recent.map(function(x){return '<div class="row"><span>'+esc(x.created_at)+' · '+esc(x.page)+'</span><b class="tag">'+esc(x.feature||x.event_type)+'</b></div>'}).join(''):'<p class="muted">暂无数据</p>'
})
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        if not ADMIN_PASSWORD:
            return False
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            raw = base64.b64decode(header[6:]).decode("utf-8")
        except Exception:
            return False
        return raw == f"{ADMIN_USER}:{ADMIN_PASSWORD}"

    def require_auth(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="baibaoxiang-admin"')
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/admin":
            if not self.authorized():
                return self.require_auth()
            body = admin_html().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/admin/stats":
            if not self.authorized():
                return self.require_auth()
            return self.send_json(query_stats())
        self.send_error(404)

    def do_POST(self):
        if urlparse(self.path).path != "/api/track":
            return self.send_error(404)
        length = min(int(self.headers.get("Content-Length", "0") or 0), 4096)
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except Exception:
            data = {}
        event_type = safe(data.get("type"), 40)
        if event_type not in ("page_view", "feature_click"):
            self.send_response(204)
            self.end_headers()
            return
        conn = db()
        conn.execute(
            """
            INSERT INTO events
            (created_at, event_type, page, path, title, feature, href, referrer_host, device)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now_text(),
                event_type,
                safe(data.get("page"), 160),
                safe(data.get("path"), 240),
                safe(data.get("title"), 120),
                safe(data.get("feature"), 100),
                safe(data.get("href"), 200),
                referrer_host(data.get("referrer")),
                safe(data.get("device"), 20),
            ),
        )
        conn.commit()
        conn.close()
        self.send_response(204)
        self.end_headers()


if __name__ == "__main__":
    db().close()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"analytics server listening on 127.0.0.1:{PORT}")
    server.serve_forever()
