"""백그라운드 자동화: 15분 메일 수집, 6시간 증분 백업, 매일 DB 백업, 매주 전체 백업 + 복구 테스트.
컴퓨터가 꺼져 있던 동안 놓친 작업은 앱이 다시 켜질 때 바로 따라잡는다."""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta

import backup
import core
import mailer

_stop = threading.Event()
RUNNING: dict[str, bool] = {}


def _due(job: str, every: timedelta) -> bool:
    last = core.get("job_" + job)
    if not last:
        return True
    return datetime.fromisoformat(last) + every <= datetime.now().astimezone()


def _mark(job: str):
    core.put("job_" + job, core.now_iso())


def trigger_collect() -> dict:
    if not core.get("mail_user") or not core.has_secret("mail_password"):
        return {"ok": False, "error": "메일 계정이 등록되지 않았습니다."}
    r = mailer.collect()
    if r.get("ok"):
        _mark("collect")
    return r


def _collect_loop():
    time.sleep(4)
    while not _stop.is_set():
        try:
            minutes = max(5, int(core.get("collect_minutes", 15)))
            if core.get("setup_done") and core.get("auto_collect", True) and core.get("mail_user") and _due("collect", timedelta(minutes=minutes)):
                RUNNING["collect"] = True
                try:
                    r = mailer.collect()
                    _mark("collect")
                    if not r.get("ok") and not r.get("skipped"):
                        core.log.warning("자동 수집 실패: %s", r.get("error"))
                finally:
                    RUNNING["collect"] = False
        except Exception as e:
            core.log.error("수집 루프 오류: %s", e)
        _stop.wait(30)


def _backup_loop():
    time.sleep(20)
    while not _stop.is_set():
        try:
            if core.get("setup_done") and core.get("auto_backup", True):
                if _due("backup_files", timedelta(hours=6)):
                    backup.run_backup("files"); _mark("backup_files")
                if _due("backup_db", timedelta(hours=24)):
                    backup.run_backup("db"); _mark("backup_db")
                if _due("backup_full", timedelta(days=7)):
                    backup.run_backup("full"); _mark("backup_full")
                if _due("restore_test", timedelta(days=7)) and core.get("job_backup_full"):
                    backup.verify_latest(); _mark("restore_test")
        except Exception as e:
            core.log.error("백업 루프 오류: %s", e)
        _stop.wait(120)


LAST_ACTIVITY = [0.0]


def touch():
    LAST_ACTIVITY[0] = time.time()


def _update_loop():
    """6시간마다 새 버전 확인. 자동 설치는 수집·백업 중이 아니고, 10분 이상 아무도 화면을 쓰지 않을 때만."""
    import updater
    time.sleep(45)
    updater.confirm_ok()  # 45초 동안 정상 가동 → 방금 한 업데이트를 확정
    while not _stop.is_set():
        try:
            if core.get("setup_done") and updater.manifest_url():
                if _due("update_check", timedelta(hours=6)):
                    updater.check()
                    _mark("update_check")
                last = core.get("update_last") or {}
                idle = time.time() - LAST_ACTIVITY[0] > 600
                busy = RUNNING.get("collect") or backup._lock.locked()
                if core.get("auto_update", True) and last.get("available") and idle and not busy:
                    r = updater.apply(user="auto-update")
                    if r.get("updated"):
                        core.log.info(r["message"])
                        updater.restart_soon()
                        return
        except Exception as e:
            core.log.error("업데이트 루프 오류: %s", e)
            core.put("update_last", {**(core.get("update_last") or {}), "error": str(e)[:300], "available": False})
            _mark("update_check")
        _stop.wait(300)


def start():
    for fn in (_collect_loop, _backup_loop, _update_loop):
        threading.Thread(target=fn, daemon=True, name=fn.__name__).start()


def stop():
    _stop.set()
