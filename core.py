"""PRESSFLOW 핵심: 경로, 데이터베이스, 설정, 비밀정보 암호화, 감사 로그."""
from __future__ import annotations

import datetime as dt
import json
import logging
import logging.handlers
import os
import re
import sqlite3
import stat
import sys
import threading
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

APP = "PRESSFLOW"
APP_KO = "강원사회복지신문 통합 콘텐츠 자동화 플랫폼"
VERSION = "1.2.1"

HOME = Path(os.environ.get("PRESSFLOW_HOME") or (Path.home() / "PRESSFLOW")).expanduser()
DATA = HOME / "data"
P = {
    "db": DATA / "pressflow.sqlite",
    "mail_raw": DATA / "mail_raw",
    "att": DATA / "attachments",
    "photos": DATA / "photos",
    "thumbs": DATA / "thumbs",
    "txt_orig": DATA / "txt" / "original",
    "txt_corr": DATA / "txt" / "corrected",
    "key": DATA / ".pressflow.key",
    "session_key": DATA / ".session.key",
    "logs": HOME / "logs",
}
DEFAULT_BACKUP_DIR = HOME / "backups"

log = logging.getLogger("pressflow")


def ensure_dirs() -> None:
    for k, p in P.items():
        if k in ("db", "key", "session_key"):
            continue
        p.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    if not log.handlers:
        log.setLevel(logging.INFO)
        h = logging.handlers.RotatingFileHandler(P["logs"] / "pressflow.log", maxBytes=2_000_000,
                                                 backupCount=5, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(h)
        if sys.stderr is not None:  # pythonw(콘솔 없음)에서는 stderr가 없다
            sh = logging.StreamHandler()
            sh.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
            log.addHandler(sh)


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def safe_name(s: str, maxlen: int = 80) -> str:
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", s or "")
    s = re.sub(r"\s+", " ", s).strip(" .")
    return s[:maxlen].strip(" .") or "untitled"


# ───────────────────────── 데이터베이스 ─────────────────────────
_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, display TEXT, pw_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'editor', active INTEGER DEFAULT 1, created TEXT);
CREATE TABLE IF NOT EXISTS mails(
  id INTEGER PRIMARY KEY, uidv TEXT, uid INTEGER, message_id TEXT, subject TEXT,
  sender_name TEXT, sender_email TEXT, received_at TEXT, body_text TEXT, raw_path TEXT,
  status TEXT, note TEXT, created TEXT,
  UNIQUE(uidv, uid));
CREATE INDEX IF NOT EXISTS ix_mail_msgid ON mails(message_id);
CREATE TABLE IF NOT EXISTS articles(
  id INTEGER PRIMARY KEY, mail_id INTEGER REFERENCES mails(id), seq INTEGER DEFAULT 1,
  doc_att_id INTEGER, title TEXT, final_title TEXT, org TEXT, region TEXT, region_reason TEXT, sub_region TEXT,
  original_text TEXT, corrected_text TEXT, final_text TEXT, blog_html TEXT, hashtags TEXT, category TEXT,
  stage TEXT, status TEXT, flags TEXT DEFAULT '[]', suggestions TEXT DEFAULT '[]',
  content_hash TEXT, txt_orig_path TEXT, txt_corr_path TEXT,
  blog_url TEXT, published_at TEXT, published_by TEXT, published_version INTEGER,
  version INTEGER DEFAULT 1, exclude_reason TEXT, fail_reason TEXT, received_at TEXT,
  created TEXT, updated TEXT);
CREATE INDEX IF NOT EXISTS ix_art_status ON articles(status);
CREATE INDEX IF NOT EXISTS ix_art_region ON articles(region);
CREATE INDEX IF NOT EXISTS ix_art_hash ON articles(content_hash);
CREATE TABLE IF NOT EXISTS attachments(
  id INTEGER PRIMARY KEY, mail_id INTEGER REFERENCES mails(id), article_id INTEGER,
  kind TEXT, orig_name TEXT, stored_path TEXT, size INTEGER, sha256 TEXT, mime TEXT,
  extract_status TEXT, extract_note TEXT, extracted_text TEXT,
  order_no INTEGER DEFAULT 0, caption TEXT, credit TEXT, is_cover INTEGER DEFAULT 0,
  width INTEGER, height INTEGER, thumb_path TEXT, rights_flag INTEGER DEFAULT 0, created TEXT);
CREATE INDEX IF NOT EXISTS ix_att_art ON attachments(article_id);
CREATE INDEX IF NOT EXISTS ix_att_mail ON attachments(mail_id);
CREATE TABLE IF NOT EXISTS corrections(
  id INTEGER PRIMARY KEY, article_id INTEGER, rule TEXT, before TEXT, after TEXT,
  confidence TEXT, source TEXT, created TEXT);
CREATE INDEX IF NOT EXISTS ix_corr_art ON corrections(article_id);
CREATE TABLE IF NOT EXISTS region_rules(
  id INTEGER PRIMARY KEY, kind TEXT, pattern TEXT, region TEXT, created TEXT,
  UNIQUE(kind, pattern));
CREATE TABLE IF NOT EXISTS audit(
  id INTEGER PRIMARY KEY, ts TEXT, user TEXT, action TEXT, detail TEXT);
"""


def db() -> sqlite3.Connection:
    c = getattr(_local, "c", None)
    if c is None:
        c = sqlite3.connect(P["db"], timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("PRAGMA foreign_keys=ON")
        _local.c = c
    return c


def init_db() -> None:
    ensure_dirs()
    db().executescript(SCHEMA)
    _add_column("mails", "folder", "TEXT")
    # 마이그레이션은 컬럼 추가만 허용 — 기존 데이터를 지우거나 초기화하지 않는다.
    if get("schema_version") is None:
        put("schema_version", 1)


def _add_column(table: str, col: str, decl: str) -> None:
    if col not in [r["name"] for r in db().execute(f"PRAGMA table_info({table})").fetchall()]:
        db().execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def rows(sql: str, *a) -> list[sqlite3.Row]:
    return db().execute(sql, a).fetchall()


def row(sql: str, *a):
    return db().execute(sql, a).fetchone()


def run(sql: str, *a) -> int:
    return db().execute(sql, a).lastrowid


def get(key: str, default=None):
    r = row("SELECT value FROM settings WHERE key=?", key)
    if r is None:
        return default
    try:
        return json.loads(r["value"])
    except Exception:
        return default


def put(key: str, value) -> None:
    run("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        key, json.dumps(value, ensure_ascii=False))


def audit(user: str | None, action: str, detail: str = "") -> None:
    run("INSERT INTO audit(ts,user,action,detail) VALUES(?,?,?,?)", now_iso(), user or "system", action, detail[:2000])


# ───────────────────────── 비밀정보 암호화 ─────────────────────────
def _key() -> bytes:
    kp = P["key"]
    if not kp.exists():
        DATA.mkdir(parents=True, exist_ok=True)
        kp.write_bytes(Fernet.generate_key())
        try:
            kp.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except Exception:
            pass
    return kp.read_bytes().strip()


def fernet() -> Fernet:
    return Fernet(_key())


def recovery_key() -> str:
    return _key().decode()


def set_secret(name: str, value: str) -> None:
    put("secret:" + name, fernet().encrypt(value.encode()).decode() if value else "")


def get_secret(name: str) -> str:
    v = get("secret:" + name, "")
    if not v:
        return ""
    try:
        return fernet().decrypt(v.encode()).decode()
    except InvalidToken:
        return ""


def has_secret(name: str) -> bool:
    return bool(get("secret:" + name, ""))
