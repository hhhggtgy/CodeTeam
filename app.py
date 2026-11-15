import os, io, csv, time, html, sqlite3, secrets
from functools import wraps
from flask import Flask, request, Response, send_from_directory

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "visits.db")
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ["ADMIN_PASS"]            # обязательно задай!
BEHIND_PROXY = os.environ.get("BEHIND_PROXY") == "1"  # 1 если стоит nginx/Caddy

app = Flask(__name__)


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


with conn() as c:
    c.execute("""CREATE TABLE IF NOT EXISTS visits(
        id INTEGER PRIMARY KEY, ts INTEGER, ip TEXT, ua TEXT,
        lang TEXT, scr TEXT, tz TEXT, ref TEXT, path TEXT)""")


def client_ip():
    if BEHIND_PROXY:
        xff = request.headers.get("X-Forwarded-For", "")
        if xff:
            return xff.split(",")[0].strip()
    return request.remote_addr


def admin_only(f):
    @wraps(f)
    def w(*a, **k):
        au = request.authorization
        ok = (au and secrets.compare_digest(au.username or "", ADMIN_USER)
              and secrets.compare_digest(au.password or "", ADMIN_PASS))
        if not ok:
            return Response("Нужен вход", 401,
                            {"WWW-Authenticate": 'Basic realm="admin"'})
        return f(*a, **k)
    return w


@app.get("/")
def index():
    return send_from_directory(BASE, "index.html")


@app.post("/log")
def log():
    # вызывается страницей ТОЛЬКО после того, как человек нажал «Принять»
    d = request.get_json(silent=True) or {}
    cut = lambda v, n: str(v or "")[:n]
    with conn() as c:
        c.execute(
            "INSERT INTO visits(ts,ip,ua,lang,scr,tz,ref,path) VALUES(?,?,?,?,?,?,?,?)",
            (int(time.time()), client_ip(), cut(request.headers.get("User-Agent"), 300),
             cut(d.get("lang"), 20), cut(d.get("scr"), 20), cut(d.get("tz"), 60),
             cut(d.get("ref"), 300), cut(d.get("path"), 200)))
    return "", 204


@app.get("/admin")
@admin_only
def admin():
    with conn() as c:
        rows = c.execute("SELECT * FROM visits ORDER BY id DESC LIMIT 500").fetchall()
        total = c.execute("SELECT COUNT(*) FROM visits").fetchone()[0]
        uniq = c.execute("SELECT COUNT(DISTINCT ip) FROM visits").fetchone()[0]
    e = html.escape
    tr = "".join(
        "<tr>" + "".join(f"<td>{e(str(v))}</td>" for v in (
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["ts"])),
            r["ip"], r["lang"], r["scr"], r["tz"], r["ua"], r["ref"])) + "</tr>"
        for r in rows)
    page = f"""<!doctype html><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Посетители</title>
<style>body{{font:14px system-ui;margin:12px}}table{{border-collapse:collapse;font-size:12px}}
td,th{{border:1px solid #8884;padding:4px 6px;text-align:left;word-break:break-all}}
.s{{overflow-x:auto}}</style>
<h2>Посетители</h2>
<p>Всего визитов: {total} · уникальных IP: {uniq} ·
<a href="/admin/export.csv">CSV</a></p>
<form method=post action=/admin/purge onsubmit="return confirm('Удалить весь журнал?')">
<button>Удалить весь журнал</button></form><br>
<div class=s><table><tr><th>Время</th><th>IP</th><th>Язык</th><th>Экран</th>
<th>Пояс</th><th>Браузер</th><th>Откуда</th></tr>{tr}</table></div>"""
    return page


@app.get("/admin/export.csv")
@admin_only
def export():
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["time", "ip", "lang", "screen", "tz", "ua", "ref", "path"])
    with conn() as c:
        for r in c.execute("SELECT * FROM visits ORDER BY id"):
            w.writerow([r["ts"], r["ip"], r["lang"], r["scr"], r["tz"], r["ua"], r["ref"], r["path"]])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=visits.csv"})


@app.post("/admin/purge")
@admin_only
def purge():
    with conn() as c:
        c.execute("DELETE FROM visits")
    return Response("Журнал очищен. <a href=/admin>назад</a>", mimetype="text/html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
