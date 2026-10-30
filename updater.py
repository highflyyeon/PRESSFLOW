"""PRESSFLOW 자동 업데이트.

배포자가 올린 '업데이트 묶음(zip)'을 주기적으로 확인해, 서명이 맞을 때만 설치한다.
 - 서명: Ed25519. 공개키는 update_channel.json(프로그램 폴더)에 있고, 개인키는 배포자만 가진다.
   → 업데이트 주소가 바뀌거나 탈취되어도 개인키 없이는 코드를 설치시킬 수 없다.
 - 설치 전 데이터 백업, 설치 후 시작 실패 시 이전 버전으로 자동 복귀.
 - 데이터 폴더(PRESSFLOW_HOME)는 건드리지 않는다.
이 파일은 의도적으로 core 에 의존하지 않는다(복귀 로직이 항상 동작해야 하므로) — 설정 접근만 지연 import.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))  # 설치형(.exe): 코드는 묶여 있어 파일 교체 대신 새 설치 파일을 실행한다
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
UPD = ROOT / ".update"
PENDING = UPD / "pending.json"
PREV = UPD / "prev"
CHANNEL = ROOT / "update_channel.json"
INSTALLED = UPD / "installed_files.json"
KEEP = {"venv", ".update", "update_channel.json", "__pycache__", ".git", "dist", "release_private.key"}
MAX_ZIP = 200 * 1024 * 1024
MAX_UNPACKED = 400 * 1024 * 1024


def vtuple(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v or "0")[:4]) or (0,)


def channel() -> dict:
    try:
        return json.loads(CHANNEL.read_text(encoding="utf-8"))
    except Exception:
        return {}


def current_version() -> str:
    import core
    return core.VERSION


def manifest_url() -> str:
    import core
    return (core.get("update_url") or channel().get("manifest_url") or "").strip()


def _read(url: str, limit: int) -> bytes:
    if re.match(r"^https?://", url, re.I):
        req = urllib.request.Request(url, headers={"User-Agent": "PRESSFLOW-updater"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read(limit + 1)
    else:  # 공유 폴더·NAS·로컬 경로 (file:// 포함)
        p = url[7:] if url.lower().startswith("file://") else url
        if re.match(r"^/[A-Za-z]:", p):
            p = p[1:]
        with open(p, "rb") as f:
            data = f.read(limit + 1)
    if len(data) > limit:
        raise RuntimeError("업데이트 파일이 너무 큽니다.")
    return data


def _sibling(base: str, name: str) -> str:
    if re.match(r"^https?://", base, re.I):
        return urllib.parse.urljoin(base, name)
    if re.match(r"^https?://", name, re.I):
        return name
    b = base[7:] if base.lower().startswith("file://") else base
    return str(Path(b).parent / name)


def verify_sig(version: str, sha: str, sig_b64: str) -> None:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    pk = (channel().get("public_key") or "").strip()
    if not pk:
        raise RuntimeError("업데이트 서명 공개키(update_channel.json)가 없어 설치할 수 없습니다.")
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(pk)).verify(base64.b64decode(sig_b64), f"{version}:{sha}".encode())
    except (InvalidSignature, ValueError, TypeError):
        raise RuntimeError("업데이트 서명이 올바르지 않습니다. 설치하지 않았습니다.")


def fetch_manifest() -> dict:
    url = manifest_url()
    if not url:
        raise RuntimeError("업데이트 주소가 설정되지 않았습니다.")
    m = json.loads(_read(url, 200_000).decode("utf-8"))
    for k in ("version", "file", "sha256", "sig"):
        if not m.get(k):
            raise RuntimeError("업데이트 정보 파일 형식이 올바르지 않습니다.")
    m["_url"] = url
    return m


def check() -> dict:
    """새 버전이 있는지만 확인(설치 안 함)."""
    import core
    cur = current_version()
    res = {"current": cur, "checked": core.now_iso(), "available": False}
    try:
        m = fetch_manifest()
        verify_sig(m["version"], m["sha256"], m["sig"])  # 서명 안 맞는 정보는 아예 '업데이트 있음'으로 보여주지 않는다
        res.update(latest=m["version"], notes=m.get("notes", ""), date=m.get("date", ""),
                   available=vtuple(m["version"]) > vtuple(cur))
        try:
            bad = json.loads((UPD / "blocked.json").read_text(encoding="utf-8")).get("version")
        except Exception:
            bad = None
        if bad and vtuple(m["version"]) <= vtuple(bad):  # 시작에 실패해 되돌린 버전은 더 새 버전이 나올 때까지 건너뜀
            res["available"] = False
            res["skipped"] = f"{bad} 버전은 이 컴퓨터에서 시작되지 않아 건너뜁니다."
    except Exception as e:
        res["error"] = str(e)[:300]
    core.put("update_last", res)
    return res


def _safe_extract(zpath: Path, dest: Path) -> None:
    total = 0
    with zipfile.ZipFile(zpath) as z:
        for i in z.infolist():
            n = i.filename.replace("\\", "/")
            parts = [p for p in n.split("/") if p]
            if n.startswith("/") or ".." in parts or (parts and ":" in parts[0]):
                raise RuntimeError("업데이트 묶음에 안전하지 않은 경로가 있습니다.")
            if (i.external_attr >> 16) & 0o170000 == stat.S_IFLNK:
                raise RuntimeError("업데이트 묶음에 바로가기 파일이 있어 거부했습니다.")
            total += i.file_size
            if total > MAX_UNPACKED:
                raise RuntimeError("업데이트 묶음이 비정상적으로 큽니다.")
        z.extractall(dest)


def _files(base: Path) -> list[str]:
    out = []
    for p in base.rglob("*"):
        if p.is_file():
            rel = p.relative_to(base).as_posix()
            if rel.split("/")[0] in KEEP or "__pycache__" in rel or rel.endswith(".pyc"):
                continue
            out.append(rel)
    return sorted(out)


def _replace(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".new")
    shutil.copy2(src, tmp)
    os.replace(tmp, dst)


def apply(manifest: dict | None = None, user: str = "system") -> dict:
    """내려받기 → 검증 → 백업 → 교체. (재시작은 호출한 쪽에서 restart_soon())"""
    import core
    m = manifest or fetch_manifest()
    cur = current_version()
    if vtuple(m["version"]) <= vtuple(cur):
        return {"ok": True, "updated": False, "message": "이미 최신 버전입니다."}
    verify_sig(m["version"], m["sha256"], m["sig"])
    if m.get("min_python") and sys.version_info[:2] < tuple(int(x) for x in str(m["min_python"]).split(".")[:2]):
        raise RuntimeError(f"이 업데이트는 Python {m['min_python']} 이상이 필요합니다.")
    if FROZEN:
        return _apply_installer(m, cur, user)
    data = _read(_sibling(m["_url"], m["file"]), MAX_ZIP)
    if hashlib.sha256(data).hexdigest() != m["sha256"].lower():
        raise RuntimeError("내려받은 파일이 손상되었거나 변조되었습니다(해시 불일치). 설치하지 않았습니다.")

    UPD.mkdir(exist_ok=True)
    stage = UPD / "stage"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir()
    zpath = UPD / "download.zip"
    zpath.write_bytes(data)
    try:
        _safe_extract(zpath, stage)
        root = stage
        if not (root / "pressflow.py").exists():  # zip 안에 폴더가 하나 더 있는 경우
            subs = [d for d in stage.iterdir() if d.is_dir() and (d / "pressflow.py").exists()]
            if len(subs) != 1:
                raise RuntimeError("업데이트 묶음에 pressflow.py 가 없습니다.")
            root = subs[0]
        mm = re.search(r'^VERSION\s*=\s*"([^"]+)"', (root / "core.py").read_text(encoding="utf-8"), re.M)
        if not mm or mm.group(1) != m["version"]:
            raise RuntimeError("업데이트 묶음의 버전이 정보 파일과 다릅니다.")
        for f in ("app.py", "core.py", "static/index.html"):
            if not (root / f).exists():
                raise RuntimeError(f"업데이트 묶음에 {f} 가 없습니다.")
        # 문법 검사: 깨진 파일을 설치하지 않는다
        for p in root.rglob("*.py"):
            try:
                compile(p.read_text(encoding="utf-8"), str(p.relative_to(root)), "exec")
            except SyntaxError as e:
                raise RuntimeError(f"업데이트 묶음의 {p.name} 에 문법 오류가 있어 설치하지 않았습니다: {e.msg}")

        # 1) 데이터 백업
        if core.get("setup_done"):
            import backup
            r = backup.run_backup("pre-update")
            if isinstance(r, dict) and r.get("error"):
                raise RuntimeError("업데이트 전 백업에 실패해 중단했습니다: " + str(r["error"])[:150])

        # 2) 새 필수 구성요소
        newreq, oldreq = root / "requirements.txt", ROOT / "requirements.txt"
        if newreq.exists() and (not oldreq.exists() or newreq.read_bytes() != oldreq.read_bytes()):
            p = subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", str(newreq)],
                               capture_output=True, text=True, timeout=600)
            if p.returncode != 0:
                raise RuntimeError("필수 구성요소 설치에 실패했습니다(인터넷 확인): " + (p.stderr or "")[-200:])

        # 3) 이전 버전 보관 후 교체
        newfiles = _files(root)
        try:
            oldfiles = json.loads(INSTALLED.read_text(encoding="utf-8"))
        except Exception:  # 설치 기록이 없으면 '교체되는 파일'만 이전 버전으로 보관 → 알 수 없는 파일은 지우지 않는다
            oldfiles = [f for f in _files(ROOT) if f in set(newfiles)]
        shutil.rmtree(PREV, ignore_errors=True)
        PREV.mkdir(parents=True)
        for rel in set(oldfiles) | set(newfiles):
            s = ROOT / rel
            if s.exists():
                _replace(s, PREV / rel)
        for rel in newfiles:
            _replace(root / rel, ROOT / rel)
        for rel in set(oldfiles) - set(newfiles):  # 새 버전에서 사라진 파일
            (ROOT / rel).unlink(missing_ok=True)
        INSTALLED.write_text(json.dumps(newfiles), encoding="utf-8")
        (PREV / ".prev_files.json").write_text(json.dumps(sorted(set(oldfiles))), encoding="utf-8")
        PENDING.write_text(json.dumps({"from": cur, "to": m["version"], "tries": 0, "ts": time.time()}), encoding="utf-8")
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        zpath.unlink(missing_ok=True)
    core.audit(user, "update", f"{cur} → {m['version']}")
    core.put("update_last", {"current": m["version"], "latest": m["version"], "available": False, "checked": core.now_iso(),
                             "installed": core.now_iso(), "notes": m.get("notes", "")})
    return {"ok": True, "updated": True, "from": cur, "to": m["version"], "message": f"{m['version']} 으로 업데이트했습니다. 곧 다시 시작합니다."}


_INSTALLER: list = []


def _apply_installer(m: dict, cur: str, user: str) -> dict:
    """설치형: 서명된 새 설치 파일을 내려받아 검증하고, 재시작 시점에 조용히 실행한다(설치 파일이 앱 교체·재실행을 맡는다)."""
    import core
    inst = (m.get("installer") or {}).get("windows")
    if not inst:
        raise RuntimeError("이 버전에는 설치형 업데이트 파일이 없습니다. 새 설치 파일을 직접 받아 설치하세요.")
    verify_sig(m["version"], inst["sha256"], inst["sig"])
    data = _read(_sibling(m["_url"], inst["file"]), 400 * 1024 * 1024)
    if hashlib.sha256(data).hexdigest() != inst["sha256"].lower():
        raise RuntimeError("내려받은 설치 파일이 손상되었거나 변조되었습니다(해시 불일치). 실행하지 않았습니다.")
    if core.get("setup_done"):
        import backup
        r = backup.run_backup("pre-update")
        if isinstance(r, dict) and r.get("error"):
            raise RuntimeError("업데이트 전 백업에 실패해 중단했습니다: " + str(r["error"])[:150])
    d = core.HOME / "updates"
    d.mkdir(parents=True, exist_ok=True)
    for old in d.glob("*.exe"):
        old.unlink(missing_ok=True)
    f = d / inst["file"]
    f.write_bytes(data)
    _INSTALLER[:] = [str(f)]
    core.audit(user, "update", f"{cur} → {m['version']} (설치 파일)")
    core.put("update_last", {"current": m["version"], "latest": m["version"], "available": False, "checked": core.now_iso(),
                             "installed": core.now_iso(), "notes": m.get("notes", "")})
    return {"ok": True, "updated": True, "from": cur, "to": m["version"], "installer": True,
            "message": f"{m['version']} 으로 업데이트합니다. 곧 다시 시작합니다."}


# ── 시작 실패 시 자동 복귀 (stdlib 만 사용) ─────────────────────────
def rollback() -> bool:
    if not PREV.exists():
        return False
    try:
        info = json.loads(PENDING.read_text(encoding="utf-8")) if PENDING.exists() else {}
    except Exception:
        info = {}
    cur = INSTALLED.exists() and json.loads(INSTALLED.read_text(encoding="utf-8")) or []
    prevfiles = []
    pf = PREV / ".prev_files.json"
    if pf.exists():
        prevfiles = json.loads(pf.read_text(encoding="utf-8"))
    for rel in set(cur) - set(prevfiles):
        (ROOT / rel).unlink(missing_ok=True)
    for rel in prevfiles:
        if (PREV / rel).exists():
            _replace(PREV / rel, ROOT / rel)
    INSTALLED.write_text(json.dumps(prevfiles), encoding="utf-8")
    PENDING.unlink(missing_ok=True)
    (UPD / "blocked.json").write_text(json.dumps({"version": info.get("to")}), encoding="utf-8")  # 같은 버전을 다시 설치하지 않도록
    (UPD / "rolled_back.json").write_text(json.dumps({"from": info.get("to"), "to": info.get("from"), "ts": time.time()}), encoding="utf-8")
    return True


def guard() -> None:
    """서버 시작 직전에 호출. 새 버전이 세 번 연속 '정상 가동 확인' 없이 시작되면 이전 버전으로 되돌린다."""
    if not PENDING.exists():
        return
    try:
        info = json.loads(PENDING.read_text(encoding="utf-8"))
    except Exception:
        PENDING.unlink(missing_ok=True)
        return
    info["tries"] = int(info.get("tries", 0)) + 1
    if info["tries"] >= 3:
        if rollback():
            os.execv(sys.executable, [sys.executable] + sys.argv)  # 되돌린 코드로 다시 시작
        PENDING.unlink(missing_ok=True)
        return
    PENDING.write_text(json.dumps(info), encoding="utf-8")


def confirm_ok() -> None:
    """정상 가동이 확인되면 호출(보류 표시 삭제)."""
    PENDING.unlink(missing_ok=True)


def rolled_back_info() -> dict | None:
    f = UPD / "rolled_back.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
    except Exception:
        return None


def clear_rolled_back() -> None:
    (UPD / "rolled_back.json").unlink(missing_ok=True)


# ── 재시작 ──────────────────────────────────────────────────────────
def restart_soon(delay: float = 1.5) -> None:
    """자신이 종료된 뒤(포트가 비면) 새 코드로 다시 시작하는 도우미를 띄우고, 잠시 후 종료한다."""
    import threading
    exe = sys.executable
    if os.name == "nt" and exe.lower().endswith("python.exe") and Path(exe[:-10] + "pythonw.exe").exists():
        exe = exe[:-10] + "pythonw.exe"
    kw: dict = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL, "cwd": str(ROOT)}
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000
    else:
        kw["start_new_session"] = True
    if _INSTALLER:  # 설치형: 새 설치 파일이 이 프로그램을 닫고 교체한 뒤 다시 실행한다
        subprocess.Popen([_INSTALLER[0], "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"], **kw)
        delay = max(delay, 4.0)
    elif FROZEN:
        subprocess.Popen([exe, "_restart"], **kw)
    else:
        subprocess.Popen([exe, str(ROOT / "pressflow.py"), "_restart"], **kw)
    threading.Timer(delay, lambda: os._exit(0)).start()
