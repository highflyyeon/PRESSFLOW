"""AI 교정 엔진: 규칙 기반 교정(항상 동작) + 선택적 Claude 교정 + 원문 대비 검증.

원칙: 사실(이름·기관명·날짜·금액·수치·인용문·사업명)은 건드리지 않는다.
확신이 낮은 교정은 '제안'으로만 남기고 자동 적용하지 않는다.
"""
from __future__ import annotations

import calendar
import datetime as dt
import difflib
import html
import re
from collections import Counter

import core

# ───────────── 사용자 편집 가능한 표기 사전 ─────────────
DEFAULT_DICT = {
    "지역내": "지역 내",
    "복지서비스": "복지 서비스",
}

# 틀린 표기가 확실한 단어(자동 적용)
SAFE_TYPOS = {
    "몇일": "며칠", "몇 일": "며칠", "왠만": "웬만", "어떻해": "어떡해", "설레임": "설렘", "금새": "금세",
    "희안": "희한", "오랫만": "오랜만", "일일히": "일일이", "곰곰히": "곰곰이", "틈틈히": "틈틈이",
    "번번히": "번번이", "깨끗히": "깨끗이", "웬지": "왠지", "어의없": "어이없", "역활": "역할", "덥썩": "덥석",
    "닥달": "닦달", "뒷풀이": "뒤풀이", "됬": "됐", "할께": "할게", "갈께": "갈게", "줄께": "줄게", "볼께": "볼게",
    "올께": "올게", "드릴께": "드릴게", "읍니다": "습니다", "봬요": "봬요",
}

# '~하다' 계열 명사 + 띄어 쓴 어미
HADA_NOUNS = ("추진|실시|개최|진행|운영|지원|마련|확대|협력|지정|시행|제공|발굴|조성|강화|참여|개선|점검|홍보|추가|선정|"
              "체결|확정|발표|전달|기부|후원|봉사|교육|상담|관리|조사|개소|준공|착공|완료|시작|참석|방문|논의|협의|제안|요청|"
              "신청|접수|모집|지급|확인|개편|도입|활용|연계|구축|독려|당부|강조|전개|수행|이행|건의|지시|발전|노력|기여")
HADA_ENDS = ("한다|했다|하고|하여|하는|하며|합니다|했습니다|하겠다|하기로|하였다|하였으며|하게|하도록|하기|했으며|했고|하고자|"
             "해왔|해야|할 계획|한다고|했다고|한다는|한다면")


class Rule:
    def __init__(self, name, pattern, repl, conf="high", flags=0):
        self.name, self.rx, self.repl, self.conf = name, re.compile(pattern, flags), repl, conf


RULES: list[Rule] = [
    Rule("하다 붙여쓰기", rf"({HADA_NOUNS})[ ]+({HADA_ENDS})", r"\1\2"),
    Rule("'수 있다' 띄어쓰기", r"(할|될|갈|볼|있을|없을|받을|줄|쓸|낼|드릴|알|얻을|살|만들|이룰|도울|돕|지킬|누릴|나눌|이끌)[ ]*수[ ]*(있|없)", r"\1 수 \2"),
    Rule("'수 있다' 띄어쓰기", r"(?<=[가-힣])수있", "수 있"),
    Rule("의존명사 '것/때문' + 서술격", r"(것|뿐|때문|따름|중|곳|점|분|바)[ ]+(입니다|이다|이며|이고|이라고|이라는|이었다|이었으며|이었습니다|이므로)", r"\1\2"),
    Rule("조사 앞 불필요한 공백", r"(?<=[가-힣0-9])[ ]+(을|를|에서|에게|으로|부터|까지|처럼|보다)(?=[ ,.\n]|$)", r"\1"),
    Rule("숫자와 단위 붙여쓰기", r"(\d)[ ]+(가구|세대|가정|개소|시간|㎡|km|kg|%)", r"\1\2"),
    Rule("숫자와 단위 붙여쓰기", r"(\d)[ ]+(명|건|개|세|회|곳|팀)(?=(?:이(?!상|하|내|외|후|전)|을|를|은|는|의|에|으로|로|과|와|도|만|씩|째|까지|부터)(?![가-힣])|[^가-힣]|$)", r"\1\2"),
    Rule("연속 마침표 정리", r"(?<![.\d])\.\.(?!\.)", "."),
    Rule("연속 쉼표 정리", r",{2,}", ","),
    Rule("문장부호 앞 공백 제거", r"(?<=[가-힣])[ ]+([,.!?])(?=[ \n]|$)", r"\1"),
    Rule("쉼표 뒤 공백", r"(?<=[가-힣]),(?=[가-힣])", ", "),
    Rule("마침표 뒤 공백", r"(?<=[가-힣])\.(?=[가-힣])", ". "),
    Rule("되요→돼요", r"(?<![가-힣])되요(?![가-힣])", "돼요"),
]

# 자동 적용하지 않고 '제안'만 하는 규칙 (확신 낮음)
SUGGEST_RULES: list[Rule] = [
    Rule("반복 단어", r"(?<![가-힣])([가-힣]{2,8})[ ]+\1(?![가-힣])", r"\1", "medium"),
    Rule("'바램' → '바람' 확인", r"바램", "바람", "medium"),
    Rule("'는데' → '는 데'(의존명사) 확인", r"(?<=[가-힣])는데(?= (?:목적|필요|도움|기여|효과|활용|사용|쓰이|쓰인|초점|중점))", "는 데", "medium"),
    Rule("'안되' → '안 되' 확인", r"(?<![가-힣])안되(?=[는고며어서야]|었|지|면|고|니)", "안 되", "medium"),
    Rule("'–로서/–로써' 확인", r"(?<![가-힣])([가-힣]{2,6})로써(?=[ ,])", r"\1로서/\1로써", "low"),
]

# 보호 구간: 인용문·작은따옴표 사업명·URL·이메일·전화번호
_PROTECT = re.compile(
    r"“[^”]{1,600}”|\"[^\"\n]{1,600}\"|‘[^’]{1,200}’|「[^」]{1,200}」|『[^』]{1,200}』|"
    r"https?://\S+|[\w.+-]+@[\w-]+\.[\w.-]+|\b0\d{1,2}[-)\s]?\d{3,4}-\d{4}\b")


def normalize_ws(t: str) -> str:
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"[​‌‍﻿]", "", t)
    t = t.replace(" ", " ").replace("　", " ")
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _apply_rules(text: str, rules, dictionary: dict, log: list, conf_tag="high") -> str:
    def make(rule):
        def cb(m):
            new = m.expand(rule.repl)
            if new != m.group(0):
                log.append({"rule": rule.name, "before": m.group(0), "after": new, "confidence": rule.conf})
            return new
        return cb
    for rule in rules:
        text = rule.rx.sub(make(rule), text)
    for k, v in {**SAFE_TYPOS, **dictionary}.items():
        if k in text and k != v:
            n = text.count(k)
            log.append({"rule": "표기 사전", "before": k, "after": v, "confidence": "high", "count": n})
            text = text.replace(k, v)
    return text


def local_proofread(text: str, user_dict: dict | None = None) -> dict:
    """규칙 기반 교정. 반환: corrected, changes(적용), suggestions(제안)."""
    dictionary = {**DEFAULT_DICT, **(user_dict or {})}
    text = normalize_ws(text)
    protected: list[str] = []

    def hold(m):
        protected.append(m.group(0))
        return f"{len(protected) - 1}"

    body = _PROTECT.sub(hold, text)
    changes: list[dict] = []
    body = _apply_rules(body, RULES, dictionary, changes)

    suggestions: list[dict] = []
    for rule in SUGGEST_RULES:
        for m in rule.rx.finditer(body):
            ctx = body[max(0, m.start() - 14): m.end() + 14].replace("\n", " ")
            ctx = re.sub(r"(\d+)", lambda mm: protected[int(mm.group(1))], ctx)
            suggestions.append({"rule": rule.name, "before": m.group(0), "after": m.expand(rule.repl),
                                "context": ctx, "confidence": rule.conf})

    # 보호 구간 복원 + 보호 구간 내부 오탈자는 '제안'으로만 남김
    def restore(m):
        return protected[int(m.group(1))]
    out = re.sub(r"(\d+)", restore, body)
    for seg in protected:
        if seg.startswith(("“", '"', "‘", "「", "『")):
            probe: list[dict] = []
            fixed = _apply_rules(seg, RULES, dictionary, probe)
            if fixed != seg:
                suggestions.append({"rule": "인용문/사업명 내부 표기", "before": seg[:80], "after": fixed[:80],
                                    "context": "직접 인용·사업명은 자동 수정하지 않습니다. 필요 시 직접 수정하세요.",
                                    "confidence": "medium"})
    return {"corrected": out, "changes": changes, "suggestions": suggestions}


# ───────────── 문단 정리(줄바꿈) ─────────────
_BULLET = re.compile(r"^\s*([□○●■◆▶▷◇◦•·ㆍ※\-–—*]|\d{1,2}[.)]|[가-하][.)]|[①-⑩]|\(\d+\)|<[^>]+>|\[[^\]]+\])")
_TERM = re.compile(r"[.!?다요음임함됨”\"')\]]$")


def to_paragraphs(text: str) -> list[str]:
    paras: list[str] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        cur = ""
        for line in block.split("\n"):
            line = line.strip()
            if not line:
                continue
            if not cur:
                cur = line
            elif _BULLET.match(line) or _TERM.search(cur):
                paras.append(cur)
                cur = line
            else:
                cur += " " + line
        if cur:
            paras.append(cur)
    return paras


# ───────────── 검증 ─────────────
def _strip(t: str) -> str:
    return re.sub(r"\s+", "", t)


def _nums(t: str) -> Counter:
    return Counter(re.findall(r"\d[\d,.]*\d|\d", t))


def _quotes(t: str) -> Counter:
    return Counter(_strip(m) for m in re.findall(r"“[^”]+”|\"[^\"\n]+\"|‘[^’]+’|「[^」]+」|『[^』]+』", t))


_ORG = re.compile(r"[가-힣]{2,10}(?:특별자치도|시|군|청|센터|협회|협의회|연합회|재단|복지관|공단|위원회|학교|병원|도)")


def _orgs(t: str) -> Counter:
    return Counter(m.group(0) for m in _ORG.finditer(_strip(t)))


def _dates(t: str) -> Counter:
    return Counter(re.findall(r"\d{1,2}월\d{1,2}일|\d{4}년|\d{1,2}시\d{0,2}분?", _strip(t)))


def _sentences(t: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?다])\s+|\n+", t) if len(_strip(s)) >= 12]


def verify(original: str, corrected: str, min_ratio: float = 0.985) -> list[dict]:
    """원문 대비 검증. 문제가 있으면 flags 반환(severity: block/warn)."""
    flags: list[dict] = []
    a, b = _strip(original), _strip(corrected)

    def diff_counter(c1: Counter, c2: Counter) -> str:
        lost, new = c1 - c2, c2 - c1
        parts = []
        if lost:
            parts.append("사라짐: " + ", ".join(list(lost)[:5]))
        if new:
            parts.append("생김: " + ", ".join(list(new)[:5]))
        return " / ".join(parts)

    for code, label, f in (("verify_numbers", "숫자·수치", _nums), ("verify_quotes", "인용문·사업명(따옴표)", _quotes),
                           ("verify_dates", "날짜·시간", _dates), ("verify_orgs", "기관·지명", _orgs)):
        c1, c2 = f(original), f(corrected)
        if c1 != c2:
            flags.append({"code": code, "sev": "block", "msg": f"{label}이(가) 원문과 다릅니다 — {diff_counter(c1, c2)}"})

    ratio = difflib.SequenceMatcher(None, a, b, autojunk=False).quick_ratio() if len(a) > 4000 else \
        difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()
    if ratio < min_ratio:
        flags.append({"code": "verify_ratio", "sev": "block", "msg": f"원문과의 일치율이 {ratio * 100:.1f}%로 낮습니다(내용 변경 의심)."})

    # 누락 문장
    if a not in b:
        csents = [_strip(s) for s in _sentences(corrected)]
        missing = []
        for s in _sentences(original):
            ss = _strip(s)
            if ss in b:
                continue
            best = max((difflib.SequenceMatcher(None, ss, c).ratio() for c in csents), default=0) if csents else 0
            if best < 0.85:
                missing.append(s.strip()[:40])
        if missing:
            flags.append({"code": "verify_missing", "sev": "block", "msg": "누락이 의심되는 문장: " + " | ".join(missing[:3])})
    return flags


def second_pass(corrected: str, user_dict: dict | None = None) -> bool:
    """2차 검증: 교정본에 다시 교정을 돌려도 더 바뀌는 것이 없어야 한다(안정성)."""
    again = local_proofread(corrected, user_dict)
    return again["corrected"] == corrected or not again["changes"]


# ───────────── 사실관계 점검(요일·날짜 유효성) ─────────────
_WD = "월화수목금토일"


def fact_flags(text: str, ref: dt.date) -> list[dict]:
    """날짜-요일 불일치·존재하지 않는 날짜 탐지. 연도가 없으면 메일 수신일 기준으로 가장 가까운 해를 적용."""
    flags: list[dict] = []
    seen = set()
    rx = re.compile(r"(?:(\d{4})\s*[.년]\s*)?(\d{1,2})\s*[.월]\s*(\d{1,2})\s*[.일]?\s*\(\s*([월화수목금토일])\s*\)")
    for m in rx.finditer(text):
        y = int(m.group(1)) if m.group(1) else None
        mo, d, wd = int(m.group(2)), int(m.group(3)), m.group(4)
        key = (y, mo, d, wd)
        if key in seen:
            continue
        seen.add(key)
        if not (1 <= mo <= 12):
            flags.append({"code": "fact_date_invalid", "sev": "block", "msg": f"존재하지 않는 날짜: '{m.group(0)}'"})
            continue
        yy = y
        if yy is None:
            yy = ref.year
            try:
                cand = dt.date(yy, mo, min(d, 28))
                if cand < ref - dt.timedelta(days=120):
                    yy += 1
                elif cand > ref + dt.timedelta(days=245):
                    yy -= 1
            except ValueError:
                pass
        if not (1 <= d <= calendar.monthrange(yy, mo)[1]):
            flags.append({"code": "fact_date_invalid", "sev": "block", "msg": f"존재하지 않는 날짜: '{m.group(0)}'"})
            continue
        actual = _WD[dt.date(yy, mo, d).weekday()]
        if actual != wd:
            flags.append({"code": "fact_weekday", "sev": "block",
                          "msg": f"날짜와 요일이 맞지 않습니다: '{m.group(0)}' — {yy}년 {mo}월 {d}일은 {actual}요일입니다. 사실관계 확인 필요"})
    return flags


# ───────────── 변경 이력 표시용 diff ─────────────
def diff_html(a: str, b: str) -> str:
    ta, tb = re.findall(r"\s+|\S+", a), re.findall(r"\s+|\S+", b)
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ta, tb, autojunk=False).get_opcodes():
        if op == "equal":
            out.append(html.escape("".join(ta[i1:i2])))
        else:
            if i2 > i1:
                out.append("<del>" + html.escape("".join(ta[i1:i2])) + "</del>")
            if j2 > j1:
                out.append("<ins>" + html.escape("".join(tb[j1:j2])) + "</ins>")
    return "".join(out).replace("\n", "<br>")
