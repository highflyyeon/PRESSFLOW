"""네이버 메일 IMAP 수집. 읽기 전용(readonly)으로 열어 메일을 삭제·이동·읽음표시하지 않는다."""
from __future__ import annotations

import imaplib
import re
import threading
import time
from datetime import datetime, timedelta

import core
import pipeline

HOST, PORT = "imap.naver.com", 993
_lock = threading.Lock()
STATUS = {"running": False, "last_ok": None, "last_error": None, "last_count": 0, "started": None, "progress": ""}


def _login_id(raw: str) -> str:
    return (raw or "").strip().split("@")[0] if (raw or "").lower().endswith("@naver.com") else (raw or "").strip()


def connect(user: str | None = None, password: str | None = None):
    user = user or core.get("mail_user", "")
    password = password or core.get_secret("mail_password")
    if not user or not password:
        raise RuntimeError("네이버 메일 계정이 아직 등록되지 않았습니다.")
    try:
        M = imaplib.IMAP4_SSL(HOST, PORT, timeout=40)
    except (OSError, TimeoutError) as e:
        raise RuntimeError("네이버 메일 서버(imap.naver.com)에 접속하지 못했습니다. 인터넷 연결과 방화벽을 확인하세요. (" + str(e)[:60] + ")")
    try:
        M.login(_login_id(user), password)
    except imaplib.IMAP4.error as e:
        raise RuntimeError("로그인 실패: 네이버 아이디/비밀번호를 확인하세요. 2단계 인증을 쓰는 경우 '애플리케이션 비밀번호'가 필요하고, "
                           "네이버 메일 > 환경설정 > POP3/IMAP 설정에서 IMAP 사용이 켜져 있어야 합니다. (" + str(e)[:80] + ")")
    return M


def test(user: str, password: str) -> dict:
    M = connect(user, password)
    try:
        typ, data = M.select("INBOX", readonly=True)
        total = int(data[0]) if data and data[0] else 0
        try:
            n = len(list_folders(M))
        except Exception:
            n = 0
        return {"ok": True, "total": total, "folders": n}
    finally:
        try:
            M.logout()
        except Exception:
            pass


# ───────── 메일함(폴더) ─────────
def utf7_decode(s: str) -> str:
    """IMAP 수정 UTF-7(&...-) → 한글 등 일반 문자열."""
    out, i = [], 0
    while i < len(s):
        if s[i] == "&":
            j = s.find("-", i)
            if j < 0:
                out.append(s[i:])
                break
            if j == i + 1:
                out.append("&")
            else:
                b = s[i + 1:j].replace(",", "/")
                b += "=" * (-len(b) % 4)
                import base64
                out.append(base64.b64decode(b).decode("utf-16-be"))
            i = j + 1
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def utf7_encode(s: str) -> str:
    import base64
    out, buf = [], []

    def flush():
        if buf:
            b = base64.b64encode("".join(buf).encode("utf-16-be")).decode().rstrip("=").replace("/", ",")
            out.append("&" + b + "-")
            buf.clear()
    for ch in s:
        if 0x20 <= ord(ch) <= 0x7E:
            flush()
            out.append("&-" if ch == "&" else ch)
        else:
            buf.append(ch)
    flush()
    return "".join(out)


_LIST_RE = re.compile(r'^\((?P<flags>[^)]*)\)\s+(?:"(?P<delim>[^"]*)"|NIL)\s+(?P<name>.+)$')


def list_folders(M) -> list[dict]:
    """선택 가능한 모든 메일함. [{raw: 서버 이름, name: 화면 이름}]"""
    typ, data = M.list()
    res = []
    for line in data or []:
        if isinstance(line, tuple):
            line = line[0] + b" " + line[1] if len(line) > 1 else line[0]
        s = line.decode("utf-8", "replace") if isinstance(line, bytes) else str(line)
        mt = _LIST_RE.match(s.strip())
        if not mt or "\\noselect" in mt["flags"].lower():
            continue
        raw = mt["name"].strip()
        if raw.startswith('"') and raw.endswith('"'):
            raw = raw[1:-1]
        res.append({"raw": raw, "name": utf7_decode(raw)})
    return res


SKIP_FOLDERS = ("보낸", "임시보관", "휴지통", "스팸", "내게쓴", "수신확인", "Sent", "Draft", "Trash", "Junk", "Spam")


def _uidvalidity(M) -> str:
    typ, data = M.response("UIDVALIDITY")
    try:
        return (data[0] or b"0").decode()
    except Exception:
        return "0"


def _fetch(M, uid: int) -> bytes | None:
    typ, data = M.uid("FETCH", str(uid), "(BODY.PEEK[])")  # PEEK: 읽음 표시도 바꾸지 않음
    if typ != "OK" or not data:
        return None
    for item in data:
        if isinstance(item, tuple) and len(item) >= 2:
            return item[1]
    return None


def _since_limit(fst: dict, st: dict, anyone_done: bool) -> datetime:
    """이 메일함을 처음 수집할 때 어디까지 거슬러 올라갈지."""
    cs = (core.get("collect_since") or "").strip()
    if cs:
        try:
            return datetime.strptime(cs, "%Y-%m-%d")
        except ValueError:
            pass
    base = fst.get("connected_at") or (st.get("connected_at") if not anyone_done else None) or core.now_iso()
    fst["connected_at"] = base
    return datetime.fromisoformat(base).replace(tzinfo=None) - timedelta(days=int(core.get("initial_days", 7)))


def _enabled_folders() -> list[str]:
    cfg = core.get("mail_folders")
    if cfg is None:
        return ["INBOX"]
    names = [f["name"] for f in cfg if f.get("enabled")]
    return names or ["INBOX"]


def _collect_folder(M, name: str, raw_name: str, st: dict, progress_prefix: str) -> tuple[int, int]:
    fsts = st.setdefault("folders", {})
    fst = fsts.setdefault(name, {})
    typ, _ = M.select('"' + raw_name.replace('"', '\\"') + '"', readonly=True)
    if typ != "OK":
        raise RuntimeError(f"'{name}' 메일함을 열 수 없습니다.")
    uidv = _uidvalidity(M)
    # 메일함 이름이 달라도 (uidvalidity, uid)가 겹치지 않도록 INBOX 외에는 이름을 붙여 저장
    key = uidv if name == "INBOX" else f"{name}#{uidv}"
    anyone_done = any(v.get("first_done") for k, v in fsts.items() if k != name)
    first = not fst.get("first_done")
    if first:
        limit = _since_limit(fst, st, anyone_done)
        typ, data = M.uid("SEARCH", None, "SINCE", limit.strftime("%d-%b-%Y"))
    else:
        last = int(fst.get("last_uid", 0)) if fst.get("uidv") == uidv else 0
        typ, data = M.uid("SEARCH", None, "UID", f"{last + 1}:*")
    uids = sorted(int(x) for x in (data[0] or b"").split())
    if not first and fst.get("uidv") == uidv:
        uids = [u for u in uids if u > int(fst.get("last_uid", 0))]
    maxuid = int(fst.get("last_uid", 0)) if fst.get("uidv") == uidv else 0
    saved = 0
    total = len(uids)
    for i, uid in enumerate(uids, 1):
        STATUS["progress"] = f"{progress_prefix} {i}/{total}"
        raw = _fetch(M, uid)
        if raw is None:
            continue
        if first:
            md = _mail_date(raw)
            if md and md < limit:
                maxuid = max(maxuid, uid)  # 시작일 이전 메일은 가져오지 않음
                continue
        if pipeline.ingest_mail(raw, key, uid, name):
            saved += 1
        maxuid = max(maxuid, uid)
        fst.update(uidv=uidv, last_uid=maxuid)
        core.put("mail_state", st)  # 메일마다 진행 위치 저장 → 중단 후 이어받기
    fst.update(uidv=uidv, last_uid=maxuid, first_done=True)
    core.put("mail_state", st)
    return saved, total


def collect(connected_at: str | None = None, M=None) -> dict:
    """신규 메일 수집(선택한 모든 메일함). 최초에는 시작일(또는 연결 시점 기준 최근 N일)부터.
    중단되어도 UID·Message-ID 중복 검사로 이어서 수집된다."""
    if not _lock.acquire(blocking=False):
        return {"ok": False, "skipped": "이미 수집이 진행 중입니다."}
    STATUS.update(running=True, started=core.now_iso(), last_error=None, progress="접속 중")
    saved = total = 0
    errors: list[str] = []
    own = M is None
    try:
        M = M or connect()
        st = core.get("mail_state") or {}
        if "folders" not in st:  # 예전 버전(받은메일함만) 상태를 새 형식으로 옮김
            st["folders"] = {}
            if st.get("first_done") or st.get("last_uid"):
                st["folders"]["INBOX"] = {k: st[k] for k in ("uidv", "last_uid", "first_done") if k in st}
        st["connected_at"] = st.get("connected_at") or connected_at or core.now_iso()
        avail = {f["name"]: f["raw"] for f in list_folders(M)}
        avail.setdefault("INBOX", "INBOX")
        wanted = _enabled_folders()
        for n, name in enumerate(wanted, 1):
            if name not in avail:
                errors.append(f"'{name}' 메일함을 찾을 수 없습니다(이름이 바뀌었나요?)")
                continue
            try:
                s, t = _collect_folder(M, name, avail[name], st, f"[{n}/{len(wanted)}] {name}")
                saved += s
                total += t
            except Exception as e:  # 한 메일함이 실패해도 나머지는 계속
                errors.append(f"{name}: {str(e)[:120]}")
                core.log.error("메일함 %s 수집 실패: %s", name, e)
        STATUS.update(last_ok=core.now_iso(), last_count=saved, progress="")
        err = " / ".join(errors)[:300]
        core.put("last_collect", {"at": core.now_iso(), "count": saved, "ok": not (errors and not saved and not total),
                                  "error": err, "folders": len(wanted)})
        return {"ok": True, "saved": saved, "checked": total, "folders": len(wanted), "errors": errors}
    except Exception as e:
        msg = str(e)[:300]
        STATUS["last_error"] = msg
        core.put("last_collect", {"at": core.now_iso(), "count": saved, "ok": False, "error": msg})
        core.log.error("메일 수집 실패: %s", msg)
        return {"ok": False, "error": msg, "saved": saved}
    finally:
        STATUS["running"] = False
        if own and M:
            try:
                M.logout()
            except Exception:
                pass
        _lock.release()


def _mail_date(raw: bytes):
    from email.parser import BytesParser
    from email.utils import parsedate_to_datetime
    try:
        h = BytesParser().parsebytes(raw, headersonly=True)
        return parsedate_to_datetime(h["Date"]).astimezone().replace(tzinfo=None)
    except Exception:
        return None
