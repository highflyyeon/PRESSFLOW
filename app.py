"""PRESSFLOW 웹 서버(Flask). 이 컴퓨터(127.0.0.1)에서만 접속된다."""
from __future__ import annotations

import io
import json
import re
import secrets
import sys
import threading
import zipfile
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, Response, abort, g, jsonify, request, send_file, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash

import ai
import backup
import blog
import classify
import core
import mailer
import pipeline
import proofread
import scheduler
import updater

STATIC = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "static"
STATUS_LABEL = {"drafted": "AI 작성 완료", "review": "검수 필요", "approved": "발행 대기", "published": "발행 완료",
                "failed": "발행 실패", "excluded": "게시 제외"}


def create_app() -> Flask:
    core.init_db()
    app = Flask(__name__, static_folder=str(STATIC), static_url_path="/static")
    sk = core.P["session_key"]
    if not sk.exists():
        sk.write_text(secrets.token_hex(32))
    app.secret_key = sk.read_text().strip()
    app.config.update(SESSION_COOKIE_SAMESITE="Strict", SESSION_COOKIE_HTTPONLY=True,
                      PERMANENT_SESSION_LIFETIME=timedelta(days=14), MAX_CONTENT_LENGTH=64 * 1024 * 1024)

    # ───────── 보안: 로컬 호스트만, 변경 요청은 헤더 필수(CSRF·DNS 리바인딩 방어) ─────────
    @app.before_request
    def guard():
        host = (request.host or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost", "[::1]"):
            abort(403)
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("X-PF") != "1":
            abort(403)
        if request.path.startswith("/api/") and request.path != "/api/health":
            scheduler.touch()

    @app.after_request
    def headers(r):
        r.headers["X-Content-Type-Options"] = "nosniff"
        r.headers["X-Frame-Options"] = "DENY"
        r.headers["Referrer-Policy"] = "no-referrer"
        if request.path.startswith("/api/"):
            r.headers["Cache-Control"] = "no-store"
        return r

    def me():
        uid = session.get("uid")
        if not uid:
            return None
        u = core.row("SELECT * FROM users WHERE id=? AND active=1", uid)
        return u

    def session_user():
        u = me()
        return u["username"] if u else "system"

    def auth(role: str | None = None):
        def deco(fn):
            @wraps(fn)
            def w(*a, **k):
                u = me()
                if not u:
                    return jsonify(error="로그인이 필요합니다."), 401
                if role == "admin" and u["role"] != "admin":
                    return jsonify(error="최고관리자만 사용할 수 있는 기능입니다."), 403
                g.user = u
                return fn(*a, **k)
            return w
        return deco

    def J():
        return request.get_json(silent=True) or {}

    def uname():
        return g.user["username"] if getattr(g, "user", None) else "system"

    # ───────── 정적/PWA ─────────
    @app.get("/")
    def index():
        return send_from_directory(STATIC, "index.html")

    @app.get("/sw.js")
    def sw():
        r = send_from_directory(STATIC, "sw.js")
        r.headers["Service-Worker-Allowed"] = "/"
        r.headers["Cache-Control"] = "no-cache"
        return r

    @app.get("/manifest.webmanifest")
    def manifest():
        return send_from_directory(STATIC, "manifest.webmanifest", mimetype="application/manifest+json")

    @app.get("/favicon.ico")
    def favicon():
        return send_from_directory(STATIC / "icons", "pressflow.ico")

    # ───────── 상태·로그인·초기 설정 ─────────
    @app.get("/api/health")
    def health():
        return jsonify(app="PRESSFLOW", version=core.VERSION)

    @app.get("/api/state")
    def state():
        u = me()
        return jsonify(
            version=core.VERSION, setup_done=bool(core.get("setup_done")),
            has_admin=bool(core.row("SELECT 1 FROM users LIMIT 1")),
            user=({"username": u["username"], "display": u["display"] or u["username"], "role": u["role"]} if u else None),
            blog_id=core.get("blog_id", ""), blog_url=core.get("blog_url", ""),
            mail_user=core.get("mail_user", ""), guide_status=blog.guide()["status"],
            update=_upd_brief())

    def _upd_brief():
        l = core.get("update_last") or {}
        rb = updater.rolled_back_info()
        return {"available": bool(l.get("available")), "latest": l.get("latest"), "rolled_back": rb}

    @app.get("/api/update")
    @auth("admin")
    def upd_status():
        l = core.get("update_last") or {}
        return jsonify(current=core.VERSION, url=updater.manifest_url(), default_url=updater.channel().get("manifest_url", ""),
                       has_key=bool(updater.channel().get("public_key")), auto=bool(core.get("auto_update", True)),
                       last=l, rolled_back=updater.rolled_back_info())

    @app.post("/api/update/settings")
    @auth("admin")
    def upd_settings():
        d = J()
        url = (d.get("url") or "").strip()
        core.put("update_url", url)
        core.put("auto_update", bool(d.get("auto", True)))
        core.audit(session_user(), "update-settings", url[:200])
        return jsonify(ok=True)

    @app.post("/api/update/check")
    @auth("admin")
    def upd_check():
        return jsonify(updater.check())

    @app.post("/api/update/apply")
    @auth("admin")
    def upd_apply():
        try:
            r = updater.apply(user=session_user())
        except Exception as e:
            core.log.error("업데이트 실패: %s", e)
            return jsonify(ok=False, error=str(e)[:400]), 400
        if r.get("updated"):
            updater.restart_soon()
        return jsonify(r)

    @app.post("/api/update/ack-rollback")
    @auth("admin")
    def upd_ack():
        updater.clear_rolled_back()
        return jsonify(ok=True)

    @app.post("/api/setup/admin")
    def setup_admin():
        if core.row("SELECT 1 FROM users LIMIT 1"):
            return jsonify(error="이미 관리자 계정이 있습니다."), 400
        d = J()
        un, pw = (d.get("username") or "").strip(), d.get("password") or ""
        if not re.fullmatch(r"[A-Za-z0-9_.\-]{3,30}", un):
            return jsonify(error="아이디는 영문·숫자·._- 3~30자로 입력하세요."), 400
        if len(pw) < 8:
            return jsonify(error="비밀번호는 8자 이상이어야 합니다."), 400
        uid = core.run("INSERT INTO users(username,display,pw_hash,role,created) VALUES(?,?,?,?,?)",
                       un, (d.get("display") or un).strip(), generate_password_hash(pw), "admin", core.now_iso())
        session.permanent = True
        session["uid"] = uid
        core.audit(un, "관리자 계정 생성")
        return jsonify(ok=True)

    @app.post("/api/login")
    def login():
        d = J()
        u = core.row("SELECT * FROM users WHERE username=? AND active=1", (d.get("username") or "").strip())
        if not u or not check_password_hash(u["pw_hash"], d.get("password") or ""):
            core.audit(d.get("username"), "로그인 실패")
            return jsonify(error="아이디 또는 비밀번호가 올바르지 않습니다."), 401
        session.permanent = True
        session["uid"] = u["id"]
        core.audit(u["username"], "로그인")
        return jsonify(ok=True)

    @app.post("/api/logout")
    def logout():
        session.clear()
        return jsonify(ok=True)

    @app.post("/api/password")
    @auth()
    def change_pw():
        d = J()
        if not check_password_hash(g.user["pw_hash"], d.get("old") or ""):
            return jsonify(error="현재 비밀번호가 맞지 않습니다."), 400
        if len(d.get("new") or "") < 8:
            return jsonify(error="새 비밀번호는 8자 이상이어야 합니다."), 400
        core.run("UPDATE users SET pw_hash=? WHERE id=?", generate_password_hash(d["new"]), g.user["id"])
        core.audit(uname(), "비밀번호 변경")
        return jsonify(ok=True)

    # ───────── 설정 ─────────
    @app.get("/api/settings")
    @auth()
    def get_settings():
        bd = backup.backup_dir()
        return jsonify(
            mail={"user": core.get("mail_user", ""), "has_password": core.has_secret("mail_password"),
                  "minutes": core.get("collect_minutes", 15), "initial_days": core.get("initial_days", 7),
                  "auto": core.get("auto_collect", True), "since": core.get("collect_since", ""),
                  "folders": core.get("mail_folders") or []},
            blog={"url": core.get("blog_url", ""), "id": core.get("blog_id", ""), "write_url": blog.write_url(core.get("blog_id", "")),
                  "mode": "assist"},
            ai={"enabled": core.get("ai_enabled", False), "has_key": core.has_secret("anthropic_key"), "model": core.get("ai_model", "claude-sonnet-5-5")},
            backup={"dir": str(bd), "auto": core.get("auto_backup", True), "retention_days": max(30, core.get("backup_retention_days", 30)),
                    "same_drive": backup.same_device(core.DATA, bd)},
            data_dir=str(core.HOME), setup_done=bool(core.get("setup_done")), proof_dict={**proofread.DEFAULT_DICT, **core.get("proof_dict", {})})

    @app.post("/api/mail/test")
    @auth("admin")
    def mail_test():
        d = J()
        pw = d.get("password") or core.get_secret("mail_password")
        try:
            r = mailer.test(d.get("user") or core.get("mail_user", ""), pw)
            return jsonify(r)
        except Exception as e:
            return jsonify(ok=False, error=str(e)), 200

    @app.post("/api/settings/mail")
    @auth("admin")
    def set_mail():
        d = J()
        user = (d.get("user") or "").strip()
        if not user:
            return jsonify(error="네이버 아이디를 입력하세요."), 400
        changed = user != core.get("mail_user", "")
        core.put("mail_user", user)
        if d.get("password"):
            core.set_secret("mail_password", d["password"])
        core.put("collect_minutes", max(5, int(d.get("minutes") or 15)))
        core.put("initial_days", max(1, min(60, int(d.get("initial_days") or 7))))
        core.put("auto_collect", bool(d.get("auto", True)))
        since = (d.get("since") or "").strip()
        if since:
            try:
                datetime.strptime(since, "%Y-%m-%d")
            except ValueError:
                return jsonify(error="수집 시작일은 2026-10-26 같은 형식이어야 합니다."), 400
        core.put("collect_since", since)
        if changed or not core.get("mail_state"):
            core.put("mail_state", {"connected_at": core.now_iso(), "first_done": False})
        core.audit(uname(), "메일 연결 설정 변경", user)
        return jsonify(ok=True)

    @app.get("/api/mail/folders")
    @auth("admin")
    def mail_folders():
        """네이버 메일함 목록 + 저장된 선택(없으면 지역·기관 이름의 메일함을 자동 추천)."""
        try:
            M = mailer.connect()
            try:
                found = mailer.list_folders(M)
            finally:
                try:
                    M.logout()
                except Exception:
                    pass
        except Exception as e:
            return jsonify(error=str(e)[:300]), 400
        saved = {f["name"]: f for f in (core.get("mail_folders") or [])}
        out = []
        for f in found:
            n = f["name"]
            if n in saved:
                out.append({"name": n, "enabled": bool(saved[n].get("enabled")), "region": saved[n].get("region", ""), "known": True})
                continue
            if n != "INBOX" and any(s in n for s in mailer.SKIP_FOLDERS):
                continue
            dr = classify.default_folder_region(n)
            out.append({"name": n, "enabled": bool(dr) or n == "INBOX", "region": dr if dr != classify.OTHER or n in classify.CATEGORY_FOLDERS else "", "known": False})
        if not saved and any(x["enabled"] and x["name"] != "INBOX" for x in out):
            for x in out:  # 지역 메일함이 따로 있으면 받은메일함(광고·인증 메일 등)은 기본으로 수집하지 않는다
                if x["name"] == "INBOX":
                    x["enabled"] = False
        out.sort(key=lambda x: (not x["enabled"], x["name"] != "INBOX", x["name"]))
        return jsonify(folders=out)

    @app.post("/api/settings/mail-folders")
    @auth("admin")
    def set_mail_folders():
        d = J()
        items = []
        for f in d.get("folders") or []:
            n = str(f.get("name") or "").strip()
            if not n:
                continue
            reg = str(f.get("region") or "")
            if reg and reg not in classify.REGIONS:
                reg = ""
            items.append({"name": n, "enabled": bool(f.get("enabled")), "region": reg})
        core.put("mail_folders", items)
        core.audit(uname(), "수집 메일함 변경", ", ".join(i["name"] for i in items if i["enabled"])[:300])
        return jsonify(ok=True, enabled=sum(1 for i in items if i["enabled"]))

    @app.post("/api/settings/blog")
    @auth("admin")
    def set_blog():
        d = J()
        bid = blog.blog_id(d.get("url", ""))
        if not bid:
            return jsonify(error="블로그 주소(예: https://blog.naver.com/아이디) 또는 블로그 아이디를 입력하세요."), 400
        core.put("blog_id", bid)
        core.put("blog_url", f"https://blog.naver.com/{bid}")
        core.audit(uname(), "블로그 연결 설정", bid)
        return jsonify(ok=True, id=bid, write_url=blog.write_url(bid))

    @app.post("/api/settings/ai")
    @auth("admin")
    def set_ai():
        d = J()
        core.put("ai_enabled", bool(d.get("enabled")))
        if d.get("model"):
            core.put("ai_model", d["model"].strip())
        if d.get("key"):
            core.set_secret("anthropic_key", d["key"].strip())
        core.audit(uname(), "AI 교정 설정 변경", "사용" if d.get("enabled") else "미사용")
        return jsonify(ok=True)

    @app.post("/api/ai/test")
    @auth("admin")
    def ai_test():
        try:
            return jsonify(ok=True, reply=ai.test())
        except Exception as e:
            return jsonify(ok=False, error=str(e)[:300])

    @app.post("/api/settings/backup")
    @auth("admin")
    def set_backup():
        d = J()
        p = Path(d.get("dir") or core.DEFAULT_BACKUP_DIR).expanduser()
        try:
            p.mkdir(parents=True, exist_ok=True)
            t = p / ".write_test"
            t.write_text("x")
            t.unlink()
        except Exception as e:
            return jsonify(error=f"이 폴더에 쓸 수 없습니다: {e}"), 400
        core.put("backup_dir", str(p))
        core.put("auto_backup", bool(d.get("auto", True)))
        core.put("backup_retention_days", max(30, int(d.get("retention_days") or 30)))
        core.audit(uname(), "백업 설정 변경", str(p))
        return jsonify(ok=True, same_drive=backup.same_device(core.DATA, p))

    @app.get("/api/recovery-key")
    @auth("admin")
    def rec_key():
        core.audit(uname(), "복구 키 조회")
        return jsonify(key=core.recovery_key())

    @app.post("/api/setup/finish")
    @auth("admin")
    def setup_finish():
        core.put("setup_done", True)
        if core.get("mail_user") and not (core.get("mail_state") or {}).get("connected_at"):
            core.put("mail_state", {"connected_at": core.now_iso(), "first_done": False})
        core.audit(uname(), "초기 설정 완료")
        if core.get("mail_user") and core.has_secret("mail_password"):
            threading.Thread(target=scheduler.trigger_collect, daemon=True).start()
        return jsonify(ok=True)

    @app.post("/api/proof-dict")
    @auth("admin")
    def set_dict():
        d = J().get("dict") or {}
        clean = {str(k).strip(): str(v).strip() for k, v in d.items() if str(k).strip() and str(v).strip()}
        core.put("proof_dict", clean)
        core.audit(uname(), "교정 표기 사전 수정", f"{len(clean)}건")
        return jsonify(ok=True)

    # ───────── 수집 ─────────
    @app.post("/api/collect/run")
    @auth()
    def collect_run():
        if mailer.STATUS["running"]:
            return jsonify(ok=True, running=True)
        threading.Thread(target=scheduler.trigger_collect, daemon=True).start()
        return jsonify(ok=True, started=True)

    @app.get("/api/collect/status")
    @auth()
    def collect_status():
        return jsonify(running=mailer.STATUS["running"], progress=mailer.STATUS["progress"], last=core.get("last_collect"))

    # ───────── 대시보드 ─────────
    @app.get("/api/dashboard")
    @auth()
    def dashboard():
        today = datetime.now().strftime("%Y-%m-%d")
        one = lambda sql, *a: core.row(sql, *a)[0]  # noqa: E731
        by_status = {r["status"]: r["n"] for r in core.rows("SELECT status, COUNT(*) n FROM articles GROUP BY status")}
        regions = {r["region"]: r["n"] for r in core.rows("SELECT region, COUNT(*) n FROM articles GROUP BY region")}
        reg_today = {r["region"]: r["n"] for r in core.rows(
            "SELECT region, COUNT(*) n FROM articles WHERE substr(created,1,10)=? GROUP BY region", today)}
        last = core.get("last_collect") or {}
        bl = core.get("backup_last_ok")
        errs = [{"at": core.get("last_collect", {}).get("at"), "msg": "메일 수집: " + last.get("error", "")}] if last.get("error") else []
        for k in ("files", "db", "full"):
            b = core.get("backup_last_" + k)
            if b and not b["ok"]:
                errs.append({"at": b["at"], "msg": f"백업({k}): {b['detail']}"})
        proc_err = one("SELECT COUNT(*) FROM articles WHERE flags LIKE '%process_error%'")
        if proc_err:
            errs.append({"at": None, "msg": f"기사 처리 오류 {proc_err}건"})
        return jsonify(
            collect={"mails_today": one("SELECT COUNT(*) FROM mails WHERE substr(created,1,10)=? AND status<>'too_old'", today),
                     "articles_today": one("SELECT COUNT(*) FROM articles WHERE substr(created,1,10)=?", today),
                     "photos": one("SELECT COUNT(*) FROM attachments WHERE kind='image' AND article_id IS NOT NULL"),
                     "txt": one("SELECT COUNT(*) FROM articles WHERE txt_orig_path IS NOT NULL"),
                     "articles_total": one("SELECT COUNT(*) FROM articles"), "regions": regions, "regions_today": reg_today},
            ai={"corrected": one("SELECT COUNT(*) FROM articles WHERE stage IN ('AI 교정 완료','블로그 초안 생성 완료')"),
                "need_review": by_status.get("review", 0),
                "drafts": one("SELECT COUNT(*) FROM articles WHERE stage='블로그 초안 생성 완료'")},
            blog={"pending": by_status.get("approved", 0), "published": by_status.get("published", 0),
                  "failed": by_status.get("failed", 0), "excluded": by_status.get("excluded", 0),
                  "drafted": by_status.get("drafted", 0), "review": by_status.get("review", 0)},
            system={"mail": {"configured": bool(core.get("mail_user") and core.has_secret("mail_password")), "last_ok": last.get("ok", None), "error": last.get("error", "")},
                    "blog": {"configured": bool(core.get("blog_id")), "mode": "수동 보조(자동 발행 미연동)", "id": core.get("blog_id", "")},
                    "last_collect": last.get("at"), "last_publish": (core.row("SELECT MAX(published_at) FROM articles") or [None])[0],
                    "last_backup": bl, "restore_test": core.get("restore_test"), "errors": errs,
                    "running": mailer.STATUS["running"], "guide": blog.guide()["status"], "ai": ai.configured()},
            recent=[{"id": r["id"], "title": r["title"], "region": r["region"], "status": r["status"], "at": r["received_at"]}
                    for r in core.rows("SELECT id,title,region,status,received_at FROM articles ORDER BY id DESC LIMIT 8")])

    # ───────── 기사 ─────────
    def art_row(r, full=False):
        flags = json.loads(r["flags"] or "[]")
        d = {"id": r["id"], "title": r["final_title"] or r["title"], "region": r["region"], "org": r["org"],
             "status": r["status"], "status_label": STATUS_LABEL.get(r["status"], r["status"]), "stage": r["stage"],
             "received_at": r["received_at"], "blog_url": r["blog_url"], "version": r["version"],
             "photos": core.row("SELECT COUNT(*) FROM attachments WHERE article_id=? AND kind='image'", r["id"])[0],
             "open_blocks": sum(1 for f in flags if f["sev"] == "block" and not f.get("resolved")),
             "open_warns": sum(1 for f in flags if f["sev"] == "warn" and not f.get("resolved")),
             "proof": "원문유지" if any(f["code"].startswith("verify_") for f in flags) else ("교정완료" if r["corrected_text"] else "대기")}
        return d

    @app.get("/api/articles")
    @auth()
    def articles():
        w, a = ["1=1"], []
        reg = request.args.get("region")
        if reg and reg != "전체":
            w.append("region=?"); a.append(reg)
        st = request.args.get("status")
        if st:
            w.append("status=?"); a.append(st)
        q = (request.args.get("q") or "").strip()
        if q:
            w.append("(title LIKE ? OR org LIKE ? OR original_text LIKE ? OR final_title LIKE ?)")
            a += [f"%{q}%"] * 4
        if request.args.get("from"):
            w.append("substr(received_at,1,10)>=?"); a.append(request.args["from"])
        if request.args.get("to"):
            w.append("substr(received_at,1,10)<=?"); a.append(request.args["to"])
        page, per = max(1, int(request.args.get("page", 1))), min(100, int(request.args.get("per", 30)))
        total = core.row(f"SELECT COUNT(*) FROM articles WHERE {' AND '.join(w)}", *a)[0]
        rs = core.rows(f"SELECT * FROM articles WHERE {' AND '.join(w)} ORDER BY received_at DESC, id DESC LIMIT ? OFFSET ?", *a, per, (page - 1) * per)
        return jsonify(total=total, page=page, per=per, items=[art_row(r) for r in rs])

    @app.get("/api/regions")
    @auth()
    def regions():
        counts = {r["region"]: r["n"] for r in core.rows("SELECT region, COUNT(*) n FROM articles GROUP BY region")}
        return jsonify(regions=[{"name": n, "count": counts.get(n, 0)} for n in classify.REGIONS],
                       total=sum(counts.values()))

    def photo_json(r):
        return {"id": r["id"], "name": Path(r["stored_path"]).name, "caption": r["caption"] or "", "credit": r["credit"] or "",
                "order": r["order_no"], "cover": bool(r["is_cover"]), "w": r["width"], "h": r["height"], "size": r["size"],
                "ok": r["extract_status"] != "failed", "note": r["extract_note"] or "", "article_id": r["article_id"]}

    def blocking(a):
        fl = json.loads(a["flags"] or "[]")
        return [f for f in fl if f["sev"] == "block" and not f.get("resolved")]

    @app.get("/api/articles/<int:aid>")
    @auth()
    def article(aid):
        a = core.row("SELECT * FROM articles WHERE id=?", aid)
        if not a:
            abort(404)
        m = core.row("SELECT * FROM mails WHERE id=?", a["mail_id"])
        photos = core.rows("SELECT * FROM attachments WHERE article_id=? AND kind='image' ORDER BY order_no", aid)
        docs = core.rows("SELECT id,orig_name,size,extract_status,extract_note FROM attachments WHERE mail_id=? AND kind IN ('doc','other')", a["mail_id"])
        d = art_row(a)
        d.update(
            original_title=a["title"], original_text=a["original_text"], corrected_text=a["corrected_text"],
            final_text=a["final_text"] if a["final_text"] is not None else a["corrected_text"], edited=a["final_text"] is not None,
            blog_html=a["blog_html"], hashtags=a["hashtags"], category=a["category"], flags=json.loads(a["flags"] or "[]"),
            suggestions=json.loads(a["suggestions"] or "[]"), region_reason=a["region_reason"], sub_region=a["sub_region"],
            exclude_reason=a["exclude_reason"], fail_reason=a["fail_reason"], published_at=a["published_at"], published_by=a["published_by"],
            published_version=a["published_version"], txt_orig=bool(a["txt_orig_path"]), txt_corr=bool(a["txt_corr_path"]),
            mail={"id": m["id"], "subject": m["subject"], "sender_name": m["sender_name"], "sender_email": m["sender_email"],
                  "received_at": m["received_at"], "body": m["body_text"]},
            photo_list=[photo_json(p) for p in photos],
            attachments=[{"id": x["id"], "name": x["orig_name"], "size": x["size"], "status": x["extract_status"], "note": x["extract_note"]} for x in docs],
            corrections=[dict(c) for c in core.rows("SELECT rule,before,after,confidence,source FROM corrections WHERE article_id=? ORDER BY id", aid)],
            blockers=[f["msg"] for f in blocking(a)])
        return jsonify(d)

    @app.get("/api/articles/<int:aid>/diff")
    @auth()
    def article_diff(aid):
        a = core.row("SELECT * FROM articles WHERE id=?", aid)
        if not a:
            abort(404)
        pairs = {"original": a["original_text"] or "", "corrected": a["corrected_text"] or "",
                 "final": a["final_text"] if a["final_text"] is not None else (a["corrected_text"] or "")}
        x, y = request.args.get("a", "original"), request.args.get("b", "corrected")
        return jsonify(html=proofread.diff_html(pairs.get(x, ""), pairs.get(y, "")))

    def set_status_from_flags(aid):
        a = core.row("SELECT * FROM articles WHERE id=?", aid)
        if a["status"] in ("published", "excluded", "failed"):
            return
        st = "review" if blocking(a) else ("drafted" if a["status"] == "review" else a["status"])
        core.run("UPDATE articles SET status=?, updated=? WHERE id=?", st, core.now_iso(), aid)

    def rebuild_draft(aid):
        a = core.row("SELECT * FROM articles WHERE id=?", aid)
        photos = [dict(r) for r in core.rows("SELECT * FROM attachments WHERE article_id=? AND kind='image' ORDER BY order_no", aid)]
        d = blog.build_draft(dict(a), photos, blog.guide())
        core.run("UPDATE articles SET blog_html=?, hashtags=?, category=? WHERE id=?", d["html"], d["hashtags"], d["category"], aid)

    @app.post("/api/articles/<int:aid>/edit")
    @auth()
    def article_edit(aid):
        a = core.row("SELECT * FROM articles WHERE id=?", aid)
        if not a:
            abort(404)
        if a["status"] == "published":
            return jsonify(error="이미 발행된 기사입니다. 수정하면 발행 이력과 달라지므로 '게시 제외' 후 새 버전으로 관리하세요."), 400
        d = J()
        text = proofread.normalize_ws(d.get("text") or "")
        title = (d.get("title") or a["title"]).strip()
        old = json.loads(a["flags"] or "[]")
        keep = [f for f in old if not f["code"].startswith("edit_")]
        new = [{**f, "code": "edit_" + f["code"][7:], "msg": "수정본: " + f["msg"], "resolved": False}
               for f in proofread.verify(a["original_text"], text, min_ratio=0.9)]
        for f in new:
            prev = next((o for o in old if o["code"] == f["code"] and o["msg"] == f["msg"] and o.get("resolved")), None)
            if prev:
                f.update(resolved=True, by=prev.get("by"), at=prev.get("at"))
        core.run("UPDATE articles SET final_text=?, final_title=?, version=version+1, flags=?, updated=?, status=CASE WHEN status='approved' THEN 'drafted' ELSE status END WHERE id=?",
                 text, title, json.dumps(keep + new, ensure_ascii=False), core.now_iso(), aid)
        a = core.row("SELECT * FROM articles WHERE id=?", aid)
        m = core.row("SELECT * FROM mails WHERE id=?", a["mail_id"])
        rel = pipeline.write_txt({**dict(a), "title": f"{a['title']}_최종본_v{a['version']}"}, m, "corr", text, [])
        core.run("UPDATE articles SET txt_corr_path=? WHERE id=?", rel, aid)
        rebuild_draft(aid)
        set_status_from_flags(aid)
        core.audit(uname(), "기사 수정", f"#{aid} v{a['version']}")
        return jsonify(ok=True)

    @app.post("/api/articles/<int:aid>/reproofread")
    @auth()
    def article_reproof(aid):
        a = core.row("SELECT * FROM articles WHERE id=?", aid)
        if not a or a["status"] == "published":
            return jsonify(error="발행된 기사는 다시 교정할 수 없습니다."), 400
        core.run("UPDATE articles SET final_text=NULL, final_title=NULL, version=version+1 WHERE id=?", aid)
        pipeline.process_article(aid, reproofread=True)
        core.audit(uname(), "기사 재교정", f"#{aid}")
        return jsonify(ok=True)

    @app.post("/api/articles/<int:aid>/flags/resolve")
    @auth()
    def flag_resolve(aid):
        a = core.row("SELECT * FROM articles WHERE id=?", aid)
        d = J()
        fl = json.loads(a["flags"] or "[]")
        n = 0
        for f in fl:
            if f["code"] == d.get("code") and not f.get("resolved"):
                f.update(resolved=True, by=uname(), at=core.now_iso(), note=(d.get("note") or "")[:200])
                n += 1
        core.run("UPDATE articles SET flags=? WHERE id=?", json.dumps(fl, ensure_ascii=False), aid)
        set_status_from_flags(aid)
        core.audit(uname(), "확인 항목 해결", f"#{aid} {d.get('code')} {d.get('note', '')}")
        return jsonify(ok=True, resolved=n)

    @app.post("/api/articles/<int:aid>/approve")
    @auth()
    def approve(aid):
        a = core.row("SELECT * FROM articles WHERE id=?", aid)
        if not a:
            abort(404)
        d = J()
        if a["blog_url"] or a["status"] == "published":
            return jsonify(error="이미 발행된 기사입니다. 중복 발행을 막기 위해 다시 승인할 수 없습니다."), 400
        if a["status"] == "excluded":
            return jsonify(error="게시 제외된 기사입니다. 먼저 복원하세요."), 400
        blocks = [f["msg"] for f in blocking(a)]
        if not core.get("blog_id"):
            blocks.append("블로그 연결 오류: 설정에서 공식 블로그 주소를 등록하세요.")
        if blocks:
            if not (d.get("override") and g.user["role"] == "admin" and (d.get("reason") or "").strip()):
                return jsonify(error="발행 전 확인이 필요한 항목이 있습니다.", blockers=blocks,
                               can_override=g.user["role"] == "admin"), 409
            core.audit(uname(), "차단 조건 예외 승인", f"#{aid} 사유: {d['reason']} / {'; '.join(blocks)[:600]}")
        core.run("UPDATE articles SET status='approved', updated=? WHERE id=?", core.now_iso(), aid)
        core.audit(uname(), "발행 승인", f"#{aid}")
        return jsonify(ok=True)

    @app.post("/api/articles/<int:aid>/unapprove")
    @auth()
    def unapprove(aid):
        core.run("UPDATE articles SET status='drafted', updated=? WHERE id=? AND status IN ('approved','failed')", core.now_iso(), aid)
        set_status_from_flags(aid)
        return jsonify(ok=True)

    @app.post("/api/articles/<int:aid>/exclude")
    @auth()
    def exclude(aid):
        core.run("UPDATE articles SET status='excluded', exclude_reason=?, updated=? WHERE id=? AND status<>'published'",
                 (J().get("reason") or "")[:200], core.now_iso(), aid)
        core.audit(uname(), "게시 제외", f"#{aid} {J().get('reason', '')}")
        return jsonify(ok=True)

    @app.post("/api/articles/<int:aid>/restore")
    @auth()
    def restore(aid):
        core.run("UPDATE articles SET status='drafted', exclude_reason=NULL, updated=? WHERE id=? AND status='excluded'", core.now_iso(), aid)
        set_status_from_flags(aid)
        core.audit(uname(), "게시 제외 해제", f"#{aid}")
        return jsonify(ok=True)

    @app.post("/api/articles/<int:aid>/published")
    @auth()
    def published(aid):
        a = core.row("SELECT * FROM articles WHERE id=?", aid)
        url = (J().get("url") or "").strip()
        if not re.match(r"^https://(m\.)?blog\.naver\.com/[^\s]+$", url):
            return jsonify(error="네이버 블로그 게시물 주소(https://blog.naver.com/…)를 붙여 넣어 주세요."), 400
        if a["blog_url"]:
            return jsonify(error="이미 발행 기록이 있는 기사입니다."), 400
        if a["status"] not in ("approved", "failed"):
            return jsonify(error="먼저 발행 승인을 해야 합니다."), 400
        dup = core.row("SELECT id FROM articles WHERE blog_url=? AND id<>?", url, aid)
        if dup:
            return jsonify(error=f"이 주소는 이미 기사 #{dup['id']}에 기록되어 있습니다."), 400
        core.run("UPDATE articles SET status='published', blog_url=?, published_at=?, published_by=?, published_version=version, fail_reason=NULL, updated=? WHERE id=?",
                 url, core.now_iso(), uname(), core.now_iso(), aid)
        core.audit(uname(), "발행 완료 기록", f"#{aid} {url}")
        return jsonify(ok=True)

    @app.post("/api/articles/<int:aid>/failed")
    @auth()
    def failed(aid):
        core.run("UPDATE articles SET status='failed', fail_reason=?, updated=? WHERE id=? AND status IN ('approved','failed')",
                 (J().get("reason") or "사유 미입력")[:300], core.now_iso(), aid)
        core.audit(uname(), "발행 실패 기록", f"#{aid}")
        return jsonify(ok=True)

    @app.post("/api/articles/<int:aid>/region")
    @auth()
    def set_region(aid):
        d = J()
        reg = d.get("region")
        if reg not in classify.REGIONS:
            return jsonify(error="알 수 없는 분류입니다."), 400
        a = core.row("SELECT * FROM articles WHERE id=?", aid)
        m = core.row("SELECT * FROM mails WHERE id=?", a["mail_id"])
        core.run("UPDATE articles SET region=?, region_reason=?, updated=? WHERE id=?", reg, f"{uname()}이(가) 직접 분류", core.now_iso(), aid)
        rule = d.get("remember")
        if rule in ("sender", "domain") and m["sender_email"]:
            pat = m["sender_email"] if rule == "sender" else m["sender_email"].split("@")[-1]
            core.run("INSERT INTO region_rules(kind,pattern,region,created) VALUES(?,?,?,?) ON CONFLICT(kind,pattern) DO UPDATE SET region=excluded.region",
                     rule, pat.lower(), reg, core.now_iso())
        # 지역 변경은 블로그 초안(제목 말머리 등)에 영향을 줄 수 있으므로 초안 재생성
        rebuild_draft(aid)
        core.audit(uname(), "분류 변경", f"#{aid} → {reg} ({rule or '이번만'})")
        return jsonify(ok=True)

    @app.get("/api/rules")
    @auth()
    def rules():
        return jsonify(rules=[dict(r) for r in core.rows("SELECT * FROM region_rules ORDER BY id DESC")])

    @app.post("/api/rules")
    @auth("admin")
    def add_rule():
        d = J()
        if d.get("kind") not in ("sender", "domain") or d.get("region") not in classify.REGIONS or not (d.get("pattern") or "").strip():
            return jsonify(error="규칙 형식이 올바르지 않습니다."), 400
        core.run("INSERT INTO region_rules(kind,pattern,region,created) VALUES(?,?,?,?) ON CONFLICT(kind,pattern) DO UPDATE SET region=excluded.region",
                 d["kind"], d["pattern"].strip().lower(), d["region"], core.now_iso())
        return jsonify(ok=True)

    @app.delete("/api/rules/<int:rid>")
    @auth("admin")
    def del_rule(rid):
        core.run("DELETE FROM region_rules WHERE id=?", rid)
        return jsonify(ok=True)

    # ───────── 블로그 게시 도우미 ─────────
    @app.get("/api/articles/<int:aid>/publish-kit")
    @auth()
    def publish_kit(aid):
        a = core.row("SELECT * FROM articles WHERE id=?", aid)
        if not a:
            abort(404)
        photos = list(core.rows("SELECT * FROM attachments WHERE article_id=? AND kind='image' ORDER BY order_no", aid))
        idx = {p["id"]: i + 1 for i, p in enumerate(photos)}
        html_ = a["blog_html"] or ""
        by_id = {p["id"]: p for p in photos}
        preview = re.sub(r"\{IMG:(\d+)\}", lambda m: f"/files/photo/{m.group(1)}", html_)

        def paste_fig(m):
            pid = int(m.group(1))
            cap = (by_id[pid]["caption"] or "") if pid in by_id else ""
            return f"<p>[사진 {idx.get(pid, '?')}]{(' ' + cap) if cap else ''}</p>"
        paste = re.sub(r"<figure[^>]*>\s*<img[^>]*\{IMG:(\d+)\}[^>]*>(?:<figcaption>.*?</figcaption>)?\s*</figure>", paste_fig, html_, flags=re.S)
        plain = re.sub(r"<(?:/p|br\s*/?)>", "\n", paste)
        plain = re.sub(r"<[^>]+>", "", plain)
        import html as H
        plain = re.sub(r"\n{3,}", "\n\n", H.unescape(plain)).strip()
        title = blog.build_draft(dict(a), [], blog.guide())["title"]
        return jsonify(title=title, preview_html=preview, paste_html=paste, plain=plain, hashtags=a["hashtags"], category=a["category"],
                       photos=[{"n": idx[p["id"]], "id": p["id"], "name": Path(p["stored_path"]).name, "caption": p["caption"] or "", "cover": bool(p["is_cover"])} for p in photos],
                       write_url=blog.write_url(core.get("blog_id", "")), blog_id=core.get("blog_id", ""),
                       auto_publish={"available": False, "reason": "네이버 공식 블로그 글쓰기 API가 종료되어 있어 자동 발행은 연결하지 않았습니다. "
                                     "이 도우미로 편집기에 옮긴 뒤 게시물 주소를 기록하세요."})

    def zip_photos(rows_):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
            used = set()
            for r in rows_:
                p = pipeline.P_abs(r["stored_path"])
                if p.exists():
                    n = p.name
                    while n in used:
                        n = "_" + n
                    used.add(n)
                    z.write(p, n)
        buf.seek(0)
        return buf

    @app.get("/api/articles/<int:aid>/photos.zip")
    @auth()
    def article_zip(aid):
        rs = core.rows("SELECT * FROM attachments WHERE article_id=? AND kind='image' ORDER BY order_no", aid)
        t = core.row("SELECT title FROM articles WHERE id=?", aid)
        return send_file(zip_photos(rs), mimetype="application/zip", as_attachment=True, download_name=core.safe_name(t["title"], 60) + "_사진.zip")

    # ───────── 사진 저장함 ─────────
    @app.get("/api/photos")
    @auth()
    def photos():
        w, a = ["a.kind='image'"], []
        q = (request.args.get("q") or "").strip()
        if q:
            w.append("(ar.title LIKE ? OR a.stored_path LIKE ? OR ar.org LIKE ? OR m.subject LIKE ?)"); a += [f"%{q}%"] * 4
        if request.args.get("region") and request.args["region"] != "전체":
            w.append("ar.region=?"); a.append(request.args["region"])
        if request.args.get("from"):
            w.append("substr(m.received_at,1,10)>=?"); a.append(request.args["from"])
        if request.args.get("to"):
            w.append("substr(m.received_at,1,10)<=?"); a.append(request.args["to"])
        if request.args.get("unassigned"):
            w.append("a.article_id IS NULL")
        page, per = max(1, int(request.args.get("page", 1))), 60
        base = "FROM attachments a JOIN mails m ON m.id=a.mail_id LEFT JOIN articles ar ON ar.id=a.article_id WHERE " + " AND ".join(w)
        total = core.row("SELECT COUNT(*) " + base, *a)[0]
        rs = core.rows("SELECT a.*, ar.title ar_title, ar.region ar_region, m.received_at m_at, m.subject m_subject, m.id m_id " + base +
                       " ORDER BY m.received_at DESC, a.id LIMIT ? OFFSET ?", *a, per, (page - 1) * per)
        return jsonify(total=total, page=page, per=per, items=[{**photo_json(r), "article_title": r["ar_title"], "region": r["ar_region"],
                                                                 "received_at": r["m_at"], "mail_subject": r["m_subject"], "mail_id": r["m_id"]} for r in rs])

    @app.patch("/api/photos/<int:pid>")
    @auth()
    def photo_patch(pid):
        r = core.row("SELECT * FROM attachments WHERE id=?", pid)
        if not r:
            abort(404)
        d = J()
        if "caption" in d:
            core.run("UPDATE attachments SET caption=? WHERE id=?", (d["caption"] or "")[:300], pid)
        if "credit" in d:
            core.run("UPDATE attachments SET credit=? WHERE id=?", (d["credit"] or "")[:200], pid)
        if d.get("cover") and r["article_id"]:
            core.run("UPDATE attachments SET is_cover=0 WHERE article_id=? AND kind='image'", r["article_id"])
            core.run("UPDATE attachments SET is_cover=1 WHERE id=?", pid)
        if d.get("move") in ("up", "down") and r["article_id"]:
            lst = list(core.rows("SELECT id FROM attachments WHERE article_id=? AND kind='image' ORDER BY order_no, id", r["article_id"]))
            ids = [x["id"] for x in lst]
            i = ids.index(pid)
            j = i - 1 if d["move"] == "up" else i + 1
            if 0 <= j < len(ids):
                ids[i], ids[j] = ids[j], ids[i]
                for n, x in enumerate(ids, 1):
                    core.run("UPDATE attachments SET order_no=? WHERE id=?", n, x)
        if d.get("article_id") and not r["article_id"]:
            target = core.row("SELECT id FROM articles WHERE id=?", int(d["article_id"]))
            if target:
                core.run("UPDATE attachments SET article_id=? WHERE id=?", target["id"], pid)
                pipeline.finalize_photos(target["id"])
        if r["article_id"]:
            rebuild_draft(r["article_id"])
        return jsonify(ok=True)

    @app.post("/api/photos/zip")
    @auth()
    def photos_zip():
        ids = [int(x) for x in (J().get("ids") or [])][:500]
        if not ids:
            return jsonify(error="선택된 사진이 없습니다."), 400
        rs = core.rows(f"SELECT * FROM attachments WHERE kind='image' AND id IN ({','.join('?' * len(ids))})", *ids)
        return send_file(zip_photos(rs), mimetype="application/zip", as_attachment=True, download_name="PRESSFLOW_사진.zip")

    # ───────── 파일 제공(로그인 필요, 데이터 폴더 밖은 차단) ─────────
    def safe_send(rel: str, **kw):
        p = (core.DATA / rel).resolve()
        if core.DATA.resolve() not in p.parents or not p.exists():
            abort(404)
        return send_file(p, **kw)

    @app.get("/files/photo/<int:pid>")
    @auth()
    def f_photo(pid):
        r = core.row("SELECT stored_path FROM attachments WHERE id=?", pid)
        if not r:
            abort(404)
        dl = request.args.get("dl")
        return safe_send(r["stored_path"], as_attachment=bool(dl), download_name=Path(r["stored_path"]).name)

    @app.get("/files/thumb/<int:pid>")
    @auth()
    def f_thumb(pid):
        r = core.row("SELECT thumb_path, stored_path FROM attachments WHERE id=?", pid)
        if not r:
            abort(404)
        return safe_send(r["thumb_path"] or r["stored_path"])

    @app.get("/files/att/<int:aid>")
    @auth()
    def f_att(aid):
        r = core.row("SELECT stored_path, orig_name FROM attachments WHERE id=?", aid)
        if not r:
            abort(404)
        return safe_send(r["stored_path"], as_attachment=True, download_name=r["orig_name"])

    @app.get("/files/mail/<int:mid>")
    @auth()
    def f_mail(mid):
        r = core.row("SELECT raw_path, subject FROM mails WHERE id=?", mid)
        if not r or not r["raw_path"]:
            abort(404)
        return safe_send(r["raw_path"], as_attachment=True, download_name=core.safe_name(r["subject"], 60) + ".eml")

    @app.get("/files/txt/<int:aid>/<kind>")
    @auth()
    def f_txt(aid, kind):
        r = core.row("SELECT title, txt_orig_path, txt_corr_path FROM articles WHERE id=?", aid)
        rel = r["txt_orig_path"] if kind == "orig" else r["txt_corr_path"]
        if not rel:
            abort(404)
        return safe_send(rel, as_attachment=True, download_name=Path(rel).name, mimetype="text/plain; charset=utf-8")

    # ───────── 스타일 가이드 ─────────
    @app.get("/api/style")
    @auth()
    def style_get():
        return jsonify(guide=blog.guide(), layouts=blog.LAYOUTS, blog_id=core.get("blog_id", ""), analysis=core.get("style_analysis"))

    @app.post("/api/style/analyze")
    @auth("admin")
    def style_analyze():
        d = J()
        items = []
        try:
            if d.get("mode") == "paste":
                parts = [p.strip() for p in re.split(r"\n\s*={3,}\s*\n", d.get("text") or "") if p.strip()]
                for p in parts:
                    lines = p.split("\n")
                    items.append({"title": lines[0].strip(), "text": "\n".join(lines[1:]).strip()})
            else:
                bid = core.get("blog_id")
                if not bid:
                    return jsonify(error="먼저 설정에서 블로그 주소를 등록하세요."), 400
                items = blog.fetch_rss(bid, int(d.get("limit") or 30))
        except Exception as e:
            return jsonify(error=f"게시물을 가져오지 못했습니다: {e}. '직접 붙여넣기'로 분석할 수 있습니다."), 502
        res = blog.analyze(items)
        res["samples"] = [{"title": i.get("title"), "link": i.get("link", "")} for i in items[:30]]
        res["at"] = core.now_iso()
        core.put("style_analysis", res)
        core.audit(uname(), "블로그 스타일 분석", f"{res['count']}건")
        return jsonify(res)

    @app.post("/api/style")
    @auth("admin")
    def style_save():
        d = J()
        gd = blog.guide()
        for k in ("title", "body", "photos", "footer", "hashtags"):
            if isinstance(d.get(k), dict):
                gd[k] = {**gd[k], **d[k]}
        if "category" in d:
            gd["category"] = d["category"]
        if "notes" in d:
            gd["notes"] = d["notes"]
        if d.get("confirm"):
            gd.update(status="confirmed", confirmed_at=core.now_iso(), confirmed_by=uname())
        elif d.get("unconfirm"):
            gd.update(status="draft")
        core.put("style_guide", gd)
        core.audit(uname(), "스타일 가이드 " + ("확정" if d.get("confirm") else "수정"))
        return jsonify(ok=True, status=gd["status"], note="새로 수집·처리되는 기사부터 적용됩니다. 이미 만든 초안은 '재교정'으로 다시 만들 수 있습니다.")

    # ───────── 백업 ─────────
    @app.get("/api/backups")
    @auth()
    def backups():
        return jsonify(dir=str(backup.backup_dir()), items=backup.list_backups()[:60], restore_test=core.get("restore_test"),
                       last={k: core.get("backup_last_" + k) for k in ("files", "db", "full")},
                       same_drive=backup.same_device(core.DATA, backup.backup_dir()), auto=core.get("auto_backup", True))

    @app.post("/api/backups/run")
    @auth("admin")
    def backups_run():
        kind = J().get("kind")
        if kind not in ("files", "db", "full"):
            return jsonify(error="알 수 없는 백업 종류"), 400
        threading.Thread(target=backup.run_backup, args=(kind, "manual"), daemon=True).start()
        core.audit(uname(), "수동 백업 실행", kind)
        return jsonify(ok=True)

    @app.post("/api/backups/verify")
    @auth("admin")
    def backups_verify():
        r = backup.verify_latest()
        core.audit(uname(), "복구 테스트", "성공" if r["ok"] else "실패")
        return jsonify(r)

    # ───────── 사용자·활동기록 ─────────
    @app.get("/api/users")
    @auth("admin")
    def users():
        return jsonify(users=[{"id": u["id"], "username": u["username"], "display": u["display"], "role": u["role"], "active": bool(u["active"])}
                              for u in core.rows("SELECT * FROM users ORDER BY id")])

    @app.post("/api/users")
    @auth("admin")
    def user_add():
        d = J()
        un = (d.get("username") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_.\-]{3,30}", un) or len(d.get("password") or "") < 8:
            return jsonify(error="아이디(영문·숫자 3~30자)와 8자 이상 비밀번호가 필요합니다."), 400
        if core.row("SELECT 1 FROM users WHERE username=?", un):
            return jsonify(error="이미 있는 아이디입니다."), 400
        role = "admin" if d.get("role") == "admin" else "editor"
        core.run("INSERT INTO users(username,display,pw_hash,role,created) VALUES(?,?,?,?,?)", un, d.get("display") or un,
                 generate_password_hash(d["password"]), role, core.now_iso())
        core.audit(uname(), "사용자 추가", f"{un} ({role})")
        return jsonify(ok=True)

    @app.patch("/api/users/<int:uid>")
    @auth("admin")
    def user_patch(uid):
        d = J()
        if uid == g.user["id"] and (d.get("active") is False or d.get("role") == "editor"):
            return jsonify(error="자기 자신의 권한은 낮추거나 비활성화할 수 없습니다."), 400
        if "active" in d:
            core.run("UPDATE users SET active=? WHERE id=?", 1 if d["active"] else 0, uid)
        if d.get("role") in ("admin", "editor"):
            core.run("UPDATE users SET role=? WHERE id=?", d["role"], uid)
        if d.get("password"):
            if len(d["password"]) < 8:
                return jsonify(error="비밀번호는 8자 이상"), 400
            core.run("UPDATE users SET pw_hash=? WHERE id=?", generate_password_hash(d["password"]), uid)
        core.audit(uname(), "사용자 변경", f"#{uid}")
        return jsonify(ok=True)

    @app.get("/api/audit")
    @auth("admin")
    def audit_log():
        return jsonify(items=[dict(r) for r in core.rows("SELECT ts,user,action,detail FROM audit ORDER BY id DESC LIMIT 300")])

    return app


def serve(port: int = 8765):
    from werkzeug.serving import make_server
    app = create_app()
    scheduler.start()
    srv = make_server("127.0.0.1", port, app, threaded=True)
    core.log.info("PRESSFLOW %s 시작: http://127.0.0.1:%s  (데이터: %s)", core.VERSION, port, core.HOME)
    try:
        srv.serve_forever()
    finally:
        scheduler.stop()
