"""지역·기관 분류, 제목 추출, 발행 차단 조건 탐지."""
from __future__ import annotations

import re

import core

PROVINCE = "강원특별자치도청"
CITIES = ["춘천시", "원주시", "강릉시", "동해시", "태백시", "속초시", "삼척시"]
COUNTIES = ["홍천군", "횡성군", "영월군", "평창군", "정선군", "철원군", "화천군", "양구군", "인제군", "고성군", "양양군"]
OTHER = "유관기관·단체"
UNKNOWN = "분류 확인 필요"
REGIONS = [PROVINCE] + CITIES + COUNTIES + [OTHER, UNKNOWN]

ORG_WORDS = ["협회", "협의회", "연합회", "복지관", "재단", "공단", "센터", "단체", "연맹", "총연합", "사회복지회",
             "복지회", "공동모금회", "모금회", "자원봉사", "위원회", "법인", "노인회", "장애인", "학회", "조합", "종합사회복지"]
OUT_OF_GANGWON = ["경상남도", "경남", "경상북도", "경북", "충청", "전라", "경기", "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "제주"]


CATEGORY_FOLDERS = ["청소년", "여성가족", "노인", "장애인"]  # 분야별 메일함 → 기본은 '유관기관·단체'(설정에서 바꿀 수 있음)


def default_folder_region(name: str) -> str:
    """메일함 이름으로 지역을 추정. 지역·기관 메일함이 아니면 ''."""
    n = re.sub(r"\s+", "", name or "").split("/")[-1].split(".")[-1]
    if n in ("강원도", "강원특별자치도", "강원특별자치도청", "도청"):
        return PROVINCE
    for r in CITIES + COUNTIES:
        if n == r or n == r[:-1]:
            return r
    if n in CATEGORY_FOLDERS:
        return OTHER
    return ""


def folder_region(name: str) -> str:
    """저장된 메일함 설정(관리자가 고른 지역)을 우선하고, 없으면 이름으로 추정."""
    for f in core.get("mail_folders") or []:
        if f.get("name") == name:
            return f.get("region") or ""
    return default_folder_region(name)


def _rules():
    return core.rows("SELECT kind, pattern, region FROM region_rules")


def classify(sender_name: str, sender_email: str, subject: str, body: str) -> dict:
    """반환: region, reason, sub_region. 근거가 약하면 '분류 확인 필요'로 보낸다(임의 분류 금지)."""
    sender_name = sender_name or ""
    sender_email = (sender_email or "").lower()
    domain = sender_email.split("@")[-1] if "@" in sender_email else ""
    subject = subject or ""
    head = (body or "")[:1500]

    # 1) 관리자가 저장한 규칙(보낸 사람 주소 > 도메인)
    for r in _rules():
        if r["kind"] == "sender" and r["pattern"].lower() == sender_email:
            return {"region": r["region"], "reason": f"저장된 규칙(발신 주소 {sender_email})", "sub_region": ""}
    for r in _rules():
        if r["kind"] == "domain" and domain and domain == r["pattern"].lower():
            return {"region": r["region"], "reason": f"저장된 규칙(도메인 {domain})", "sub_region": ""}

    # 2) 지역명 점수
    score: dict[str, float] = {}
    why: dict[str, list[str]] = {}

    def add(region, pts, note):
        score[region] = score.get(region, 0) + pts
        why.setdefault(region, []).append(note)

    names = CITIES + COUNTIES
    for n in names:
        stem = n[:-1]
        if n in sender_name:
            add(n, 6, f"발신기관명 '{sender_name}'")
        if re.search(r"[\[\(【<]\s*" + re.escape(stem) + r"(시|군)?\s*[\]\)】>]", subject) or subject.strip().startswith(n):
            add(n, 4, f"제목 '{subject[:30]}'")
        elif n in subject:
            add(n, 3, "제목에 지역명")
        c = head.count(n)
        if c:
            add(n, min(c, 3) * 0.7, f"본문 {c}회 언급")
    if "강원특별자치도" in sender_name or "강원도" in sender_name:
        if not any(n in sender_name for n in names):
            add(PROVINCE, 6, f"발신기관명 '{sender_name}'")
    if re.search(r"^\s*[\[\(【]?\s*강원(특별자치)?도(청)?", subject):
        add(PROVINCE, 3, "제목에 강원특별자치도")
    if head.count("강원특별자치도") >= 2:
        add(PROVINCE, 1, "본문 다수 언급")

    org_like = any(w in sender_name for w in ORG_WORDS)
    best_region = max(score, key=score.get) if score else None

    # 3) 유관기관·협회·연합회·단체
    if org_like:
        sub = best_region if best_region and best_region not in (PROVINCE,) else ""
        return {"region": OTHER, "reason": f"발신기관명 '{sender_name}'에 단체 성격 표기", "sub_region": sub or ""}

    if not score:
        return {"region": UNKNOWN, "reason": "발신기관·제목·본문에서 지역을 확인하지 못함", "sub_region": ""}

    ranked = sorted(score.items(), key=lambda kv: -kv[1])
    top, top_s = ranked[0]
    second_s = ranked[1][1] if len(ranked) > 1 else 0
    # 고성군은 타 지역(경남 고성)과 혼동 가능
    if top == "고성군" and any(w in (sender_name + subject + head[:300]) for w in OUT_OF_GANGWON):
        return {"region": UNKNOWN, "reason": "'고성군'이지만 강원 외 지역 표기가 함께 있어 확인 필요", "sub_region": ""}
    if top_s < 3 or (top_s - second_s) < 2:
        return {"region": UNKNOWN, "reason": f"근거 부족({top} {top_s:.1f}점)", "sub_region": ""}
    return {"region": top, "reason": " · ".join(why[top][:3]), "sub_region": ""}


# ───────────── 제목 추출 ─────────────
_SKIP_LINE = re.compile(
    r"^(보\s*도\s*자\s*료|보도\s*참고\s*자료|참고\s*자료|배\s*포|배포\s*일|보도\s*일|담당|문의|사진|붙임|별첨|첨부|"
    r"\d{4}\s*[.\-년]|\(?\s*\d{1,2}\s*[.\-]\s*\d{1,2}|부서|전화|연락처|페이지|-\s*\d+\s*-|엠바고|즉시|취재|제공|"
    r"[A-Za-z]{0,3}\s*\d{2,4}-\d{3,4}-\d{4})", re.I)


def clean_subject(s: str) -> str:
    s = re.sub(r"^\s*((re|fw|fwd|회신|전달)\s*:\s*)+", "", s or "", flags=re.I)
    s = re.sub(r"[\[\(【]\s*(보도자료|보도|배포|긴급|사진|사진포함|첨부|공지|강원)\s*[\]\)】]\s*", "", s)
    return re.sub(r"\s+", " ", s).strip()


def extract_title(doc_text: str, subject: str) -> str:
    sub = clean_subject(subject)
    lines = [l.strip() for l in (doc_text or "").split("\n") if l.strip()][:14]
    for l in lines:
        l2 = re.sub(r"^[\-\s·•ㆍ○◦▶■□◆※\"“]+|[\"”]+$", "", l)
        if _SKIP_LINE.match(l2) or not (6 <= len(l2) <= 90) or l2.endswith("다.") and len(l2) > 70:
            continue
        # 제목처럼 보이는 첫 줄(문장형 종결이 아닌 줄) 선택
        return l2
    return sub or "제목 없음"


# ───────────── 발행 차단 조건 탐지 ─────────────
def detect_embargo(text: str, subject: str) -> str | None:
    blob = (subject or "") + "\n" + (text or "")[:800]
    m = re.search(r"엠바고[^\n]{0,60}|embargo[^\n]{0,60}|보도\s*시점[^\n]{0,40}|발행\s*금지[^\n]{0,30}", blob, re.I)
    if m:
        s = m.group(0).strip()
        if re.search(r"없음|해당\s*없|즉시", s):
            return None
        return s
    return None


def detect_personal(text: str) -> list[str]:
    out = []
    if re.search(r"\b\d{6}\s*-\s*[1-4]\d{6}\b", text or ""):
        out.append("주민등록번호 형식")
    if re.search(r"\b01[016789][\s\-.]?\d{3,4}[\s\-.]?\d{4}\b", text or ""):
        out.append("휴대전화번호")
    return out


def detect_photo_rights(text: str) -> str | None:
    m = re.search(r"[^\n]{0,30}(무단\s*(전재|복제|사용|도용)|재배포\s*금지|저작권[^\n]{0,20}(있|보호|귀속)|사진\s*(제공|출처)\s*[:：][^\n]{0,30})", text or "")
    return m.group(0).strip() if m else None
