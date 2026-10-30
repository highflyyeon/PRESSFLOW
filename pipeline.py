"""메일 1통 → 기사·사진·TXT·교정본·블로그 초안까지의 전체 처리 파이프라인."""
from __future__ import annotations

import email
import email.policy
import hashlib
import html
import json
import re
import traceback
from datetime import datetime
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path

from PIL import Image

import ai
import blog
import classify
import core
import extract
import proofread

P = core.P
MIN_INLINE_IMG = 20 * 1024


# ───────────── 유틸 ─────────────
def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def html_to_text(h: str) -> str:
    h = re.sub(r"(?is)<(script|style).*?</\1>", "", h)
    h = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", h)
    return re.sub(r"\n{3,}", "\n\n", html.unescape(re.sub(r"<[^>]+>", "", h))).strip()


def unique_path(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / name
    if not p.exists():
        return p
    stem, suf = p.stem, p.suffix
    i = 2
    while (folder / f"{stem}_{i}{suf}").exists():
        i += 1
    return folder / f"{stem}_{i}{suf}"


def add_flag(flags: list[dict], code: str, sev: str, msg: str):
    if not any(f["code"] == code and f["msg"] == msg for f in flags):
        flags.append({"code": code, "sev": sev, "msg": msg, "resolved": False})


def keep_resolved(old: list[dict], new: list[dict]) -> list[dict]:
    done = {(f["code"], f["msg"]): f for f in old if f.get("resolved")}
    for f in new:
        k = (f["code"], f["msg"])
        if k in done:
            f.update({"resolved": True, "by": done[k].get("by"), "at": done[k].get("at"), "note": done[k].get("note")})
    return new


# ───────────── 메일 수집 → 저장 ─────────────
def ingest_mail(raw: bytes, uidv: str, uid: int) -> int | None:
    """원본 메일 저장 후 기사까지 처리. 이미 저장된 메일이면 None."""
    if core.row("SELECT id FROM mails WHERE uidv=? AND uid=?", uidv, uid):
        return None
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    mid = (msg.get("Message-ID") or "").strip()
    if mid and core.row("SELECT id FROM mails WHERE message_id=?", mid):
        return None  # 다른 폴더/재전송 등으로 중복 수신
    name, addr = parseaddr(str(msg.get("From", "")))
    subject = str(msg.get("Subject", "") or "")
    try:
        recv = parsedate_to_datetime(str(msg.get("Date"))).astimezone().isoformat(timespec="seconds")
    except Exception:
        recv = core.now_iso()

    body = ""
    try:
        part = msg.get_body(preferencelist=("plain", "html"))
        if part:
            c = part.get_content()
            body = html_to_text(c) if part.get_content_type() == "text/html" else c
    except Exception:
        pass
    body = proofread.normalize_ws(body or "")

    mail_id = core.run(
        "INSERT INTO mails(uidv,uid,message_id,subject,sender_name,sender_email,received_at,body_text,status,created)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)", uidv, uid, mid, subject, name, addr.lower(), recv, body, "saved", core.now_iso())
    d = datetime.fromisoformat(recv)
    rp = P["mail_raw"] / f"{d:%Y}" / f"{d:%m}"
    rp.mkdir(parents=True, exist_ok=True)
    raw_path = rp / f"{mail_id}.eml"
    raw_path.write_bytes(raw)  # 원본 메일은 가공하지 않고 그대로 보존
    core.run("UPDATE mails SET raw_path=? WHERE id=?", str(raw_path.relative_to(core.DATA)), mail_id)

    try:
        process_mail(mail_id, msg, d)
    except Exception as e:
        core.log.error("메일 %s 처리 오류: %s\n%s", mail_id, e, traceback.format_exc())
        core.run("UPDATE mails SET status='error', note=? WHERE id=?", str(e)[:300], mail_id)
    return mail_id


def process_mail(mail_id: int, msg, d: datetime):
    m = core.row("SELECT * FROM mails WHERE id=?", mail_id)
    att_dir = P["att"] / str(mail_id)
    att_dir.mkdir(parents=True, exist_ok=True)
    docs, imgs, others = [], [], []
    n = 0
    for part in msg.walk():
        if part.is_multipart() or part.get_content_maintype() == "multipart":
            continue
        fn = part.get_filename()
        disp = (part.get_content_disposition() or "").lower()
        ctype = part.get_content_type()
        if ctype in ("text/plain", "text/html") and not fn and disp != "attachment":
            continue
        try:
            data = part.get_payload(decode=True) or b""
        except Exception:
            continue
        if not data:
            continue
        if not fn:
            ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}.get(ctype, "")
            if not ext:
                continue
            fn = f"inline_{n}{ext}"
            if len(data) < MIN_INLINE_IMG:
                continue  # 서명·로고 등 작은 인라인 이미지는 제외
        n += 1
        ext = Path(fn).suffix.lower()
        stored = unique_path(att_dir, f"{n:02d}_" + core.safe_name(fn, 120))
        stored.write_bytes(data)
        kind = "doc" if ext in extract.DOC_EXT else "image" if ext in extract.IMG_EXT else "other"
        aid = core.run(
            "INSERT INTO attachments(mail_id,kind,orig_name,stored_path,size,sha256,mime,created) VALUES(?,?,?,?,?,?,?,?)",
            mail_id, kind, fn, str(stored.relative_to(core.DATA)), len(data), sha256(data), ctype, core.now_iso())
        {"doc": docs, "image": imgs, "other": others}[kind].append((aid, fn, stored, data))

    # 문서 추출
    extracted = []
    for aid, fn, stored, data in docs:
        r = extract.extract(stored)
        core.run("UPDATE attachments SET extract_status=?, extract_note=?, extracted_text=? WHERE id=?",
                 r["status"], r["note"], r["text"], aid)
        extracted.append((aid, fn, r))

    # 기사 단위 결정
    units = []  # (doc_att_id, text, status, note, stem)
    for aid, fn, r in extracted:
        units.append({"doc": aid, "text": r["text"], "status": r["status"], "note": r["note"], "stem": Path(fn).stem, "fn": fn})
    body = m["body_text"] or ""
    if not units:
        if len(body) >= 100:
            units.append({"doc": None, "text": body, "status": "ok", "note": "", "stem": "", "fn": "메일 본문"})
        elif imgs:
            units.append({"doc": None, "text": body, "status": "failed", "note": "본문·문서 텍스트가 없고 사진만 있습니다.", "stem": "", "fn": "메일 본문"})
    if not units:
        core.run("UPDATE mails SET status='skipped', note=? WHERE id=?", "기사로 볼 수 있는 본문·문서·사진이 없어 자료함에는 보관만 했습니다.", mail_id)
        return

    # 사진 배정: 기사가 1건이면 전부 연결, 여러 건이면 파일명 일치로만 연결(임의 배정 금지)
    assign: dict[int, int | None] = {}
    for i, (aid, fn, stored, data) in enumerate(imgs):
        target = None
        if len(units) == 1:
            target = 0
        else:
            stem = Path(fn).stem
            for ui, u in enumerate(units):
                if u["stem"] and (u["stem"] in stem or stem in u["stem"]):
                    target = ui
                    break
        assign[aid] = target

    art_ids = []
    for ui, u in enumerate(units):
        title = classify.extract_title(u["text"], m["subject"])
        aid_ = core.run(
            "INSERT INTO articles(mail_id,seq,doc_att_id,title,original_text,stage,status,received_at,created,updated)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)", mail_id, ui + 1, u["doc"], title, u["text"], "수집 완료", "review",
            m["received_at"], core.now_iso(), core.now_iso())
        art_ids.append(aid_)
        mine = [a for a, t in assign.items() if t == ui]
        for k, a in enumerate(mine, 1):
            core.run("UPDATE attachments SET article_id=? WHERE id=?", aid_, a)
        if u["doc"]:
            core.run("UPDATE attachments SET article_id=? WHERE id=?", aid_, u["doc"])
        finalize_photos(aid_)
    unassigned = [a for a, t in assign.items() if t is None]
    for aid_ in art_ids:
        process_article(aid_, first_run=True, unassigned=len(unassigned), extract_info=units[art_ids.index(aid_)])
    core.run("UPDATE mails SET status='processed' WHERE id=?", mail_id)


# ───────────── 사진 저장(기사 제목 파일명) ─────────────
def finalize_photos(article_id: int):
    """기사에 연결된 사진을 '기사 제목_01.jpg' 형식으로 저장한다(원본 바이트 그대로)."""
    a = core.row("SELECT * FROM articles WHERE id=?", article_id)
    m = core.row("SELECT * FROM mails WHERE id=?", a["mail_id"])
    d = datetime.fromisoformat(m["received_at"])
    folder = P["photos"] / f"{d:%Y-%m}"
    seen = set()
    for i, r in enumerate(core.rows("SELECT * FROM attachments WHERE article_id=? AND kind='image' ORDER BY id", article_id), 1):
        if r["sha256"] in seen:  # 같은 기사 안의 중복 사진은 연결하지 않음(원본은 첨부 폴더에 보존)
            core.run("UPDATE attachments SET article_id=NULL, extract_note='중복 사진' WHERE id=?", r["id"])
            continue
        seen.add(r["sha256"])
        src = P_abs(r["stored_path"])
        ext = src.suffix.lower()
        try:
            with Image.open(src) as im:
                im.verify()
            with Image.open(src) as im:
                w, h = im.size
                im.thumbnail((480, 480))
                th = P["thumbs"] / f"{r['id']}.jpg"
                im.convert("RGB").save(th, "JPEG", quality=82)
            ok = True
        except Exception as e:
            w = h = 0
            th = None
            ok = False
            core.run("UPDATE attachments SET extract_note=? WHERE id=?", f"이미지 파일을 열 수 없음: {e}"[:200], r["id"])
        name = f"{core.safe_name(a['title'], 80)}_{i:02d}{ext}"
        dest = unique_path(folder, name)
        dest.write_bytes(src.read_bytes())
        core.run("UPDATE attachments SET stored_path=?, width=?, height=?, thumb_path=?, order_no=?, is_cover=?, extract_status=? WHERE id=?",
                 str(dest.relative_to(core.DATA)), w, h, str(th.relative_to(core.DATA)) if th else None, i,
                 1 if i == 1 else 0, "ok" if ok else "failed", r["id"])
        # 최초 업로드 원본은 attachments/ 폴더에 그대로 남아 있음


def P_abs(rel: str) -> Path:
    return core.DATA / rel


# ───────────── 기사 처리(분류·TXT·교정·검증·초안) ─────────────
def write_txt(art, mail, kind: str, text: str, atts: list) -> str:
    folder = P["txt_orig"] if kind == "orig" else P["txt_corr"]
    base = core.safe_name(art["title"], 90)
    path = folder / f"{base}.txt"
    if path.exists():
        path = unique_path(folder, f"{base}_{art['id']}.txt")
    head = [f"보도자료 제목: {art['title']}", f"발신기관: {mail['sender_name'] or ''} <{mail['sender_email']}>",
            f"수신 날짜: {mail['received_at']}", f"원본 이메일 제목: {mail['subject']}",
            f"분류: {art['region'] or ''}", f"고유번호: {art['id']}",
            "첨부파일: " + (", ".join(a["orig_name"] for a in atts) or "없음"), "=" * 60, ""]
    if kind == "orig":
        body = text
        if mail["body_text"] and mail["body_text"].strip() and mail["body_text"].strip() != text.strip():
            body += "\n\n" + "=" * 60 + "\n[메일 본문]\n" + mail["body_text"]
        for a in atts:
            if a["kind"] == "doc" and a["extracted_text"] and a["extracted_text"].strip() != text.strip():
                body += "\n\n" + "=" * 60 + f"\n[첨부문서: {a['orig_name']}]\n" + a["extracted_text"]
    else:
        body = text
    with open(path, "x", encoding="utf-8", newline="\r\n") as f:  # 'x': 기존 파일을 덮어쓰지 않음, 윈도우 메모장 호환 줄바꿈
        f.write("\n".join(head) + body + "\n")
    return str(path.relative_to(core.DATA))


def process_article(article_id: int, first_run: bool = False, unassigned: int = 0, extract_info: dict | None = None,
                    reproofread: bool = False):
    a = core.row("SELECT * FROM articles WHERE id=?", article_id)
    m = core.row("SELECT * FROM mails WHERE id=?", a["mail_id"])
    old_flags = json.loads(a["flags"] or "[]")
    flags: list[dict] = []
    try:
        text = a["original_text"] or ""
        atts = core.rows("SELECT * FROM attachments WHERE mail_id=?", a["mail_id"])
        info = extract_info or {}
        if first_run and info.get("status") in ("failed", "manual"):
            add_flag(flags, "extract_failed" if info["status"] == "failed" else "extract_manual", "block",
                     f"'{info.get('fn', '')}' 원문 추출 불가 — {info.get('note', '')}")
        # 분류
        if first_run or not a["region"]:
            c = classify.classify(m["sender_name"], m["sender_email"], m["subject"], text or m["body_text"])
            core.run("UPDATE articles SET region=?, region_reason=?, sub_region=?, org=? WHERE id=?",
                     c["region"], c["reason"], c["sub_region"], m["sender_name"] or m["sender_email"], article_id)
            a = core.row("SELECT * FROM articles WHERE id=?", article_id)
        if a["region"] == classify.UNKNOWN:
            add_flag(flags, "region_unknown", "warn", "발신기관을 명확히 알 수 없어 '분류 확인 필요'로 보관했습니다.")
        # 원문 TXT (최초 1회, 덮어쓰지 않음)
        if first_run and not a["txt_orig_path"]:
            p = write_txt(a, m, "orig", text, atts)
            core.run("UPDATE articles SET txt_orig_path=? WHERE id=?", p, article_id)

        if not text.strip():
            add_flag(flags, "no_text", "block", "기사 본문 텍스트가 없습니다. 원본을 확인하세요.")
            core.run("UPDATE articles SET stage='수집 완료', status='review', flags=?, updated=? WHERE id=?",
                     json.dumps(keep_resolved(old_flags, flags), ensure_ascii=False), core.now_iso(), article_id)
            return
        core.run("UPDATE articles SET stage='원문 추출 완료' WHERE id=?", article_id)

        # 차단 조건 탐지
        emb = classify.detect_embargo(text, m["subject"])
        if emb:
            add_flag(flags, "embargo", "block", f"엠바고/발행 시점 표시 감지: '{emb}'")
        for w in classify.detect_personal(text):
            add_flag(flags, "personal_info", "block", f"개인정보 노출 위험: {w} 포함")
        pr = classify.detect_photo_rights(text + "\n" + (m["body_text"] or ""))
        if pr and core.row("SELECT 1 FROM attachments WHERE article_id=? AND kind='image'", article_id):
            add_flag(flags, "photo_rights", "block", f"사진 이용 권한 확인 필요: '{pr[:50]}'")
        if unassigned:
            add_flag(flags, "photo_unassigned", "warn", f"기사에 연결하지 못한 사진 {unassigned}장이 있습니다(사진저장함 '미배정').")

        # 교정 1차(규칙) → (선택) AI → 검증
        user_dict = core.get("proof_dict", {})
        loc = proofread.local_proofread(text, user_dict)
        corrected, changes, sugg = loc["corrected"], loc["changes"], loc["suggestions"]
        source = "규칙"
        if ai.configured():
            try:
                cand = ai.proofread(corrected)
                v = proofread.verify(text, cand, min_ratio=0.97)
                if not v:
                    corrected, source = cand, "AI+규칙"
                else:
                    add_flag(flags, "ai_rejected", "warn", "AI 교정본이 원문 검증을 통과하지 못해 규칙 기반 교정본을 사용했습니다.")
            except Exception as e:
                add_flag(flags, "ai_error", "warn", f"AI 교정 호출 실패, 규칙 기반 교정만 적용: {e}"[:200])
        # 2차 검증
        vflags = proofread.verify(text, corrected)
        if vflags:
            for f in vflags:
                add_flag(flags, f["code"], f["sev"], f["msg"])
            corrected, changes = proofread.normalize_ws(text), []  # 검증 실패 시 원문(공백 정리만) 유지
            source = "원문 유지"
        elif source == "규칙" and not proofread.second_pass(corrected, user_dict):
            add_flag(flags, "second_pass", "warn", "2차 검증에서 추가 교정 여지가 발견되었습니다. 변경 내용을 확인하세요.")
        ref = datetime.fromisoformat(a["received_at"] or core.now_iso()).date()
        for f in proofread.fact_flags(corrected, ref):
            add_flag(flags, f["code"], f["sev"], f["msg"])
        if sugg:
            add_flag(flags, "suggestions", "warn", f"자동 확정하지 않은 교정 제안 {len(sugg)}건 — '교정 제안'에서 확인하세요.")

        # 중복 발행 방지
        chash = sha256(re.sub(r"\s+", "", text).encode())
        dup = core.row("SELECT id,status,blog_url FROM articles WHERE content_hash=? AND id<>? ORDER BY id LIMIT 1", chash, article_id)
        if dup:
            if dup["status"] == "published" or dup["blog_url"]:
                add_flag(flags, "duplicate_published", "block", f"이미 발행된 기사(#{dup['id']})와 같은 내용입니다. 재게시하지 않습니다.")
            else:
                add_flag(flags, "duplicate", "block", f"같은 내용의 기사(#{dup['id']})가 이미 있습니다.")

        # 변경 이력 저장
        core.run("DELETE FROM corrections WHERE article_id=? AND source IN ('규칙','AI+규칙')", article_id)
        for ch in changes:
            core.run("INSERT INTO corrections(article_id,rule,before,after,confidence,source,created) VALUES(?,?,?,?,?,?,?)",
                     article_id, ch["rule"], ch["before"][:200], ch["after"][:200], ch["confidence"], source, core.now_iso())
        core.run("UPDATE articles SET corrected_text=?, content_hash=?, suggestions=?, stage='AI 교정 완료' WHERE id=?",
                 corrected, chash, json.dumps(sugg, ensure_ascii=False), article_id)

        # 교정본 TXT (버전 보존)
        a = core.row("SELECT * FROM articles WHERE id=?", article_id)
        ver = (a["version"] or 1)
        p = write_txt({**dict(a), "title": a["title"] + (f"_교정본" if ver <= 1 else f"_교정본_v{ver}")}, m, "corr", corrected, [])
        core.run("UPDATE articles SET txt_corr_path=? WHERE id=?", p, article_id)

        # 블로그 초안
        g = blog.guide()
        if g["status"] != "confirmed":
            add_flag(flags, "guide_unconfirmed", "warn", "블로그 스타일 가이드가 확정되기 전의 '기본형'으로 작성되었습니다.")
        a = core.row("SELECT * FROM articles WHERE id=?", article_id)
        photos = [dict(r) for r in core.rows("SELECT * FROM attachments WHERE article_id=? AND kind='image' ORDER BY order_no", article_id)]
        if not photos:
            add_flag(flags, "no_photos", "info", "첨부 사진이 없는 기사입니다(글만으로 작성).")
        d = blog.build_draft(dict(a), photos, g)
        status = "review" if any(f["sev"] == "block" and not f.get("resolved") for f in flags) else "drafted"
        flags = keep_resolved(old_flags, flags)
        if status == "drafted" and any(f["sev"] == "block" and not f.get("resolved") for f in flags):
            status = "review"
        if not first_run and a["status"] in ("published", "excluded"):
            status = a["status"]
        elif not first_run and a["status"] == "approved" and status == "drafted":
            status = "approved"
        core.run("UPDATE articles SET blog_html=?, hashtags=?, category=?, stage='블로그 초안 생성 완료', status=?, flags=?, updated=? WHERE id=?",
                 d["html"], d["hashtags"], d["category"], status, json.dumps(flags, ensure_ascii=False), core.now_iso(), article_id)
    except Exception as e:
        core.log.error("기사 %s 처리 오류: %s\n%s", article_id, e, traceback.format_exc())
        add_flag(flags, "process_error", "block", f"처리 중 오류: {e}"[:250])
        core.run("UPDATE articles SET status='review', flags=?, updated=? WHERE id=?",
                 json.dumps(keep_resolved(old_flags, flags), ensure_ascii=False), core.now_iso(), article_id)
