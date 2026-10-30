"""백업: 6시간 증분(파일) · 매일 DB · 매주 전체 · 업데이트 전. 모두 암호화 후 보관, 복구 테스트 포함.

암호화 키는 데이터 폴더의 .pressflow.key 이며 백업에는 포함되지 않는다.
설정 마법사에서 보여 주는 '복구 키'를 별도로 보관해야 다른 컴퓨터에서 복구할 수 있다.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import struct
import tempfile
import threading
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from cryptography.fernet import Fernet

import core

MAGIC = b"PFB1"
CHUNK = 8 * 1024 * 1024
_lock = threading.Lock()
EXCLUDE_DIRS = {"thumbs"}
EXCLUDE_NAMES = {".pressflow.key", ".session.key", "pressflow.sqlite-wal", "pressflow.sqlite-shm", "pressflow.sqlite"}


def backup_dir() -> Path:
    return Path(core.get("backup_dir") or core.DEFAULT_BACKUP_DIR).expanduser()


def same_device(a: Path, b: Path) -> bool:
    try:
        a.mkdir(parents=True, exist_ok=True)
        b.mkdir(parents=True, exist_ok=True)
        return os.stat(a).st_dev == os.stat(b).st_dev
    except Exception:
        return False


def enc_file(src: Path, dst: Path, f: Fernet | None = None):
    f = f or core.fernet()
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".part")
    with open(src, "rb") as r, open(tmp, "wb") as w:
        w.write(MAGIC)
        while True:
            b = r.read(CHUNK)
            if not b:
                break
            t = f.encrypt(b)
            w.write(struct.pack("<I", len(t)))
            w.write(t)
    tmp.replace(dst)


def dec_file(src: Path, dst: Path, f: Fernet | None = None):
    f = f or core.fernet()
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(src, "rb") as r, open(dst, "wb") as w:
        if r.read(4) != MAGIC:
            raise ValueError("PRESSFLOW 백업 파일이 아닙니다.")
        while True:
            h = r.read(4)
            if not h:
                break
            n = struct.unpack("<I", h)[0]
            w.write(f.decrypt(r.read(n)))


def _snapshot_db(dst: Path):
    src = sqlite3.connect(core.P["db"])
    out = sqlite3.connect(dst)
    with out:
        src.backup(out)
    out.close()
    src.close()


def _iter_data_files():
    for root, dirs, files in os.walk(core.DATA):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for fn in files:
            if fn in EXCLUDE_NAMES or fn.endswith(".part"):
                continue
            yield Path(root) / fn


def _record(kind: str, ok: bool, detail: str):
    core.put("backup_last_" + kind, {"at": core.now_iso(), "ok": ok, "detail": detail})
    if ok:
        core.put("backup_last_ok", core.now_iso())


# ───────────── 백업 종류 ─────────────
def backup_db(tag: str = "daily") -> dict:
    d = backup_dir() / "db"
    d.mkdir(parents=True, exist_ok=True)
    name = f"db_{datetime.now():%Y%m%d-%H%M%S}_{tag}.sqlite.gz.pfb"
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.sqlite"
        _snapshot_db(snap)
        gz = Path(td) / "snap.gz"
        with open(snap, "rb") as r, gzip.open(gz, "wb", 6) as w:
            shutil.copyfileobj(r, w)
        enc_file(gz, d / name)
    return {"file": str(d / name), "size": (d / name).stat().st_size}


def backup_files_incremental(tag: str = "inc") -> dict:
    root = backup_dir()
    mf_path = root / "files_manifest.json"
    mf = json.loads(mf_path.read_text("utf-8")) if mf_path.exists() else {}
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}_{tag}"
    dest = root / "files" / stamp
    n = 0
    total = 0
    for p in _iter_data_files():
        rel = str(p.relative_to(core.DATA))
        st = p.stat()
        sig = [st.st_size, int(st.st_mtime)]
        if mf.get(rel) == sig:
            continue
        enc_file(p, dest / (rel + ".pfb"))
        mf[rel] = sig
        n += 1
        total += st.st_size
    mf_path.parent.mkdir(parents=True, exist_ok=True)
    mf_path.write_text(json.dumps(mf, ensure_ascii=False), "utf-8")
    return {"files": n, "bytes": total, "dir": str(dest) if n else ""}


def backup_full(tag: str = "weekly") -> dict:
    d = backup_dir() / "full"
    d.mkdir(parents=True, exist_ok=True)
    name = f"full_{datetime.now():%Y%m%d-%H%M%S}_{tag}.zip.pfb"
    with tempfile.TemporaryDirectory() as td:
        z = Path(td) / "full.zip"
        snap = Path(td) / "pressflow.sqlite"
        _snapshot_db(snap)
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED, compresslevel=3) as zf:
            zf.write(snap, "pressflow.sqlite")
            for p in _iter_data_files():
                zf.write(p, str(p.relative_to(core.DATA)))
        enc_file(z, d / name)
    return {"file": str(d / name), "size": (d / name).stat().st_size}


def run_backup(kind: str, tag: str | None = None) -> dict:
    """kind: db | files | full | pre-update"""
    with _lock:
        try:
            if kind == "db":
                r = backup_db(tag or "daily")
            elif kind == "files":
                r = backup_files_incremental(tag or "inc")
            elif kind == "full":
                r = backup_full(tag or "weekly")
            elif kind == "pre-update":
                r = {"db": backup_db("pre-update"), "full": backup_full("pre-update")}
            else:
                raise ValueError(kind)
            _record(kind, True, json.dumps(r, ensure_ascii=False)[:300])
            cleanup()
            return {"ok": True, **r}
        except Exception as e:
            core.log.error("백업 실패(%s): %s", kind, e)
            _record(kind, False, str(e)[:300])
            return {"ok": False, "error": str(e)[:300]}


def cleanup():
    """보관기간(최소 30일) 지난 백업 삭제. 종류별 최신 2개는 항상 남긴다."""
    days = max(30, int(core.get("backup_retention_days", 30)))
    limit = time.time() - days * 86400
    root = backup_dir()
    for sub in ("db", "full"):
        fs = sorted((root / sub).glob("*.pfb"), key=lambda p: p.stat().st_mtime, reverse=True) if (root / sub).exists() else []
        for p in fs[2:]:
            if p.stat().st_mtime < limit:
                p.unlink(missing_ok=True)
    fd = root / "files"
    if fd.exists():
        for d in fd.iterdir():
            if d.is_dir() and d.stat().st_mtime < limit:
                shutil.rmtree(d, ignore_errors=True)


def list_backups() -> list[dict]:
    root = backup_dir()
    out = []
    for sub in ("db", "full"):
        for p in (root / sub).glob("*.pfb") if (root / sub).exists() else []:
            out.append({"kind": sub, "name": p.name, "size": p.stat().st_size,
                        "at": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")})
    fd = root / "files"
    if fd.exists():
        for d in fd.iterdir():
            if d.is_dir():
                cnt = sum(1 for _ in d.rglob("*.pfb"))
                out.append({"kind": "files", "name": d.name, "size": sum(f.stat().st_size for f in d.rglob("*.pfb")),
                            "at": datetime.fromtimestamp(d.stat().st_mtime).isoformat(timespec="seconds"), "count": cnt})
    return sorted(out, key=lambda x: x["at"], reverse=True)


# ───────────── 복구 테스트 / 복원 ─────────────
def verify_latest() -> dict:
    """가장 최근 DB·전체 백업을 실제로 복호화·열어 보는 복구 테스트."""
    res = []
    root = backup_dir()
    ok_all = True
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        for sub in ("db", "full"):
            fs = sorted((root / sub).glob("*.pfb"), key=lambda p: p.stat().st_mtime, reverse=True) if (root / sub).exists() else []
            if not fs:
                res.append(f"{sub}: 백업 없음")
                ok_all = ok_all and sub != "db"
                continue
            p = fs[0]
            try:
                if sub == "db":
                    gz = td / "x.gz"
                    dec_file(p, gz)
                    sq = td / "x.sqlite"
                    with gzip.open(gz, "rb") as r, open(sq, "wb") as w:
                        shutil.copyfileobj(r, w)
                    c = sqlite3.connect(sq)
                    chk = c.execute("PRAGMA integrity_check").fetchone()[0]
                    n = c.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
                    c.close()
                    ok = chk == "ok"
                    res.append(f"DB 백업 {p.name}: 무결성 {chk}, 기사 {n}건")
                else:
                    z = td / "x.zip"
                    dec_file(p, z)
                    with zipfile.ZipFile(z) as zf:
                        bad = zf.testzip()
                        names = zf.namelist()
                    ok = bad is None and "pressflow.sqlite" in names
                    res.append(f"전체 백업 {p.name}: 파일 {len(names)}개, {'정상' if ok else '손상: ' + str(bad)}")
                ok_all = ok_all and ok
            except Exception as e:
                ok_all = False
                res.append(f"{sub} 복구 실패: {e}")
    out = {"at": core.now_iso(), "ok": ok_all, "detail": res}
    core.put("restore_test", out)
    return out


def restore(backup_file: str, dest: str, key: str | None = None):
    """백업을 dest 폴더에 풀어 놓는다(실행 중인 데이터는 건드리지 않음)."""
    f = Fernet(key.encode()) if key else core.fernet()
    src, dst = Path(backup_file), Path(dest)
    dst.mkdir(parents=True, exist_ok=True)
    if src.name.endswith(".sqlite.gz.pfb"):
        gz = dst / "tmp.gz"
        dec_file(src, gz, f)
        with gzip.open(gz, "rb") as r, open(dst / "pressflow.sqlite", "wb") as w:
            shutil.copyfileobj(r, w)
        gz.unlink()
    elif src.name.endswith(".zip.pfb"):
        z = dst / "tmp.zip"
        dec_file(src, z, f)
        with zipfile.ZipFile(z) as zf:
            zf.extractall(dst)
        z.unlink()
    else:
        raise ValueError("복원할 수 있는 파일은 db_*.sqlite.gz.pfb 또는 full_*.zip.pfb 입니다.")
    return str(dst)
