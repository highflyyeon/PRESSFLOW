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
        return {"ok": True, "total": total}
    finally:
        try:
            M.logout()
        except Exception:
            pass


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


def collect(connected_at: str | None = None, M=None) -> dict:
    """신규 메일 수집. 최초에는 연결 시점 기준 최근 7일. 중단되어도 UID 중복 검사로 이어서 수집된다."""
    if not _lock.acquire(blocking=False):
        return {"ok": False, "skipped": "이미 수집이 진행 중입니다."}
    STATUS.update(running=True, started=core.now_iso(), last_error=None, progress="접속 중")
    saved = 0
    own = M is None
    try:
        M = M or connect()
        M.select("INBOX", readonly=True)
        uidv = _uidvalidity(M)
        st = core.get("mail_state") or {}
        if not st.get("first_done"):
            since_dt = datetime.fromisoformat(st.get("connected_at") or connected_at or core.now_iso()) - timedelta(days=int(core.get("initial_days", 7)))
            st["connected_at"] = st.get("connected_at") or connected_at or core.now_iso()
            crit = ("SINCE", since_dt.strftime("%d-%b-%Y"))
            typ, data = M.uid("SEARCH", None, *crit)
        else:
            last = int(st.get("last_uid", 0))
            if st.get("uidv") and st["uidv"] != uidv:
                last = 0  # 메일함이 재구성됨 → 메시지 ID로 중복 방지하며 처음부터 확인
            typ, data = M.uid("SEARCH", None, "UID", f"{last + 1}:*")
        uids = sorted(int(x) for x in (data[0] or b"").split())
        if st.get("first_done"):
            uids = [u for u in uids if u > int(st.get("last_uid", 0)) or st.get("uidv") != uidv]
        total = len(uids)
        cutoff = datetime.fromisoformat(st["connected_at"]) - timedelta(days=int(core.get("initial_days", 7))) if not st.get("first_done") else None
        maxuid = int(st.get("last_uid", 0)) if st.get("uidv") == uidv else 0
        for i, uid in enumerate(uids, 1):
            STATUS["progress"] = f"{i}/{total}"
            raw = _fetch(M, uid)
            if raw is None:
                continue
            if cutoff and _mail_date(raw) and _mail_date(raw) < cutoff.replace(tzinfo=None):
                maxuid = max(maxuid, uid)  # 최초 수집 기간(7일) 밖의 메일은 가져오지 않음
                continue
            if pipeline.ingest_mail(raw, uidv, uid):
                saved += 1
            maxuid = max(maxuid, uid)
            st.update(uidv=uidv, last_uid=maxuid)
            core.put("mail_state", st)  # 메일마다 진행 위치 저장 → 중단 후 이어받기
        st.update(uidv=uidv, last_uid=maxuid, first_done=True)
        core.put("mail_state", st)
        STATUS.update(last_ok=core.now_iso(), last_count=saved, progress="")
        core.put("last_collect", {"at": core.now_iso(), "count": saved, "ok": True, "error": ""})
        return {"ok": True, "saved": saved, "checked": total}
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
