import os, io, re, json, uuid, time, base64, hashlib, secrets, string
import subprocess, shutil, contextlib, traceback
import requests, telebot

TOKEN = os.environ["BOT_TOKEN"]
OWNER = int(os.environ["OWNER_ID"])  # твой Telegram ID (узнать: @userinfobot)
bot = telebot.TeleBot(TOKEN)

HELP = """🛠 DevBot

/sh <cmd> — shell (owner)
/py <code> — выполнить Python (owner)
/sys — CPU/RAM/диск/аптайм
/ip — внешний IP и гео
/ping <host> — пинг
/http <url> — статус, время, заголовки
/b64e, /b64d <text> — base64
/hash <text> — md5/sha1/sha256
/json <json> — красиво отформатировать
/re <pattern> <text> — проверка regex
/ts [unix] — время <-> unix timestamp
/uuid — новый UUID4
/pass [n] — случайный пароль"""


def arg(m):
    p = m.text.split(maxsplit=1)
    return p[1].strip() if len(p) > 1 else ""


def say(m, text):
    text = str(text).strip() or "(пусто)"
    for i in range(0, len(text), 4000):
        bot.reply_to(m, text[i:i + 4000])


def owner_only(f):
    def wrapper(m):
        if m.from_user.id != OWNER:
            return bot.reply_to(m, "⛔ только для владельца")
        f(m)
    return wrapper


@bot.message_handler(commands=["start", "help"])
def start(m):
    say(m, HELP)


@bot.message_handler(commands=["sh"])
@owner_only
def sh(m):
    cmd = arg(m)
    if not cmd:
        return say(m, "Пример: /sh ls -la")
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=20)
        say(m, (r.stdout + r.stderr) or f"exit {r.returncode}")
    except subprocess.TimeoutExpired:
        say(m, "⏱ таймаут 20с")


@bot.message_handler(commands=["py"])
@owner_only
def py(m):
    code = arg(m)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            exec(code, {"__name__": "__bot__"})
    except Exception:
        buf.write(traceback.format_exc(limit=1))
    say(m, buf.getvalue())


@bot.message_handler(commands=["sys"])
def sysinfo(m):
    d = shutil.disk_usage(os.path.expanduser("~"))
    out = [f"💾 Диск: {d.used // 2**30}/{d.total // 2**30} GB"]
    try:
        mem = {l.split(":")[0]: int(l.split()[1]) for l in open("/proc/meminfo")}
        used = mem["MemTotal"] - mem["MemAvailable"]
        out.append(f"🧠 RAM: {used // 1024}/{mem['MemTotal'] // 1024} MB")
        up = float(open("/proc/uptime").read().split()[0])
        out.append(f"⏳ Аптайм: {int(up // 3600)}ч {int(up % 3600 // 60)}м")
    except Exception:
        out.append("(RAM/uptime недоступны на этом устройстве)")
    say(m, "\n".join(out))


@bot.message_handler(commands=["ip"])
def ip(m):
    try:
        j = requests.get("https://ipinfo.io/json", timeout=8).json()
        say(m, f"{j.get('ip')}\n{j.get('city')}, {j.get('country')}\n{j.get('org')}")
    except Exception as e:
        say(m, f"Ошибка: {e}")


@bot.message_handler(commands=["ping"])
def ping(m):
    host = arg(m)
    if not re.fullmatch(r"[\w.\-]+", host):
        return say(m, "Пример: /ping google.com")
    r = subprocess.run(["ping", "-c", "3", host], capture_output=True, text=True, timeout=20)
    say(m, r.stdout + r.stderr)


@bot.message_handler(commands=["http"])
def http(m):
    url = arg(m)
    if not url.startswith("http"):
        url = "https://" + url
    try:
        t = time.time()
        r = requests.get(url, timeout=10)
        ms = int((time.time() - t) * 1000)
        hdr = "\n".join(f"{k}: {v}" for k, v in list(r.headers.items())[:8])
        say(m, f"{r.status_code} за {ms} мс, {len(r.content)} байт\n\n{hdr}")
    except Exception as e:
        say(m, f"Ошибка: {e}")


@bot.message_handler(commands=["b64e"])
def b64e(m):
    say(m, base64.b64encode(arg(m).encode()).decode())


@bot.message_handler(commands=["b64d"])
def b64d(m):
    try:
        say(m, base64.b64decode(arg(m)).decode(errors="replace"))
    except Exception:
        say(m, "Невалидный base64")


@bot.message_handler(commands=["hash"])
def hsh(m):
    b = arg(m).encode()
    say(m, "\n".join(f"{n}: {hashlib.new(n, b).hexdigest()}" for n in ("md5", "sha1", "sha256")))


@bot.message_handler(commands=["json"])
def js(m):
    try:
        say(m, json.dumps(json.loads(arg(m)), indent=2, ensure_ascii=False))
    except Exception as e:
        say(m, f"Невалидный JSON: {e}")


@bot.message_handler(commands=["re"])
def rx(m):
    p = arg(m).split(maxsplit=1)
    if len(p) < 2:
        return say(m, "Пример: /re \\d+ abc 123 def 45")
    try:
        found = [x.group(0) for x in re.finditer(p[0], p[1])]
        say(m, f"Совпадений: {len(found)}\n" + "\n".join(map(repr, found)))
    except re.error as e:
        say(m, f"Ошибка regex: {e}")


@bot.message_handler(commands=["ts"])
def ts(m):
    a = arg(m)
    if a.isdigit():
        say(m, time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(int(a))))
    else:
        say(m, f"Сейчас: {int(time.time())}")


@bot.message_handler(commands=["uuid"])
def uid(m):
    say(m, str(uuid.uuid4()))


@bot.message_handler(commands=["pass"])
def pw(m):
    n = min(int(arg(m)), 64) if arg(m).isdigit() else 16
    chars = string.ascii_letters + string.digits + "!@#$%^&*-_"
    say(m, "".join(secrets.choice(chars) for _ in range(n)))


print("Бот запущен")
bot.infinity_polling()
