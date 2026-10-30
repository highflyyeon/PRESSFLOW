"""블로그 스타일 가이드(분석·확정)와 블로그 게시용 기사 초안 생성."""
from __future__ import annotations

import html
import re
import statistics
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter

import classify
import core
import proofread

DEFAULT_GUIDE = {
    "status": "draft",  # draft(기본형·미확정) | confirmed
    "confirmed_at": None,
    "confirmed_by": None,
    "blog_url": "",
    "title": {"prefix": "", "suffix": "", "region_bracket": False, "max_len": 0},
    "body": {"dateline": "", "paragraph_gap": True},
    "photos": {"layout": "first_after_title", "align": "center", "caption_template": "{caption}",
               "credit_template": "", "show_caption": True},
    "footer": {"text": "", "reporter": "", "source_line": ""},
    "category": "",
    "hashtags": {"enabled": False, "template": "", "fixed": ""},
    "notes": "",
}

LAYOUTS = {
    "first_after_title": "대표사진 1장을 제목 아래, 나머지는 본문 끝에",
    "all_after_title": "모든 사진을 제목 아래에 연속 배치",
    "distributed": "사진을 문단 사이에 고르게 배치",
    "end": "모든 사진을 본문 끝에 배치",
}


def guide() -> dict:
    g = core.get("style_guide")
    if not g:
        return DEFAULT_GUIDE
    merged = {**DEFAULT_GUIDE, **g}
    for k in ("title", "body", "photos", "footer", "hashtags"):
        merged[k] = {**DEFAULT_GUIDE[k], **g.get(k, {})}
    return merged


# ───────────── 블로그 주소 ─────────────
def blog_id(url_or_id: str) -> str:
    s = (url_or_id or "").strip()
    m = re.search(r"blogId=([A-Za-z0-9_\-]+)", s) or re.search(r"blog\.naver\.com/([A-Za-z0-9_\-]+)", s)
    if m:
        return m.group(1)
    return s if re.fullmatch(r"[A-Za-z0-9_\-]+", s) else ""


def write_url(bid: str) -> str:
    return f"https://blog.naver.com/{bid}/postwrite" if bid else "https://blog.naver.com"


# ───────────── 기존 게시물 분석 ─────────────
def fetch_rss(bid: str, limit: int = 30) -> list[dict]:
    req = urllib.request.Request(f"https://rss.blog.naver.com/{bid}.xml",
                                 headers={"User-Agent": "Mozilla/5.0 PRESSFLOW"})
    with urllib.request.urlopen(req, timeout=20) as r:
        root = ET.fromstring(r.read())
    items = []
    for it in root.iter("item"):
        g = lambda t: (it.findtext(t) or "").strip()  # noqa: E731
        items.append({"title": g("title"), "link": g("link"), "html": g("description"),
                      "category": g("category"), "tags": g("tag"), "date": g("pubDate")})
        if len(items) >= limit:
            break
    return items


def _plain(h: str) -> str:
    h = re.sub(r"<(br|/p|/div)\s*/?>", "\n", h, flags=re.I)
    return re.sub(r"\n{3,}", "\n\n", html.unescape(re.sub(r"<[^>]+>", "", h))).strip()


def analyze(items: list[dict]) -> dict:
    """게시물 목록(title/html/text/category/tags)에서 공통 형식을 '제안'으로 추출. 확정은 관리자가 한다."""
    n = len(items)
    if not n:
        return {"count": 0, "evidence": ["분석할 게시물이 없습니다."], "proposal": {}}
    ev: list[str] = []
    prop = {"title": {}, "body": {}, "photos": {}, "footer": {}, "hashtags": {}}
    titles = [i.get("title", "") for i in items]
    lens = [len(t) for t in titles]
    ev.append(f"제목 길이: 중앙값 {int(statistics.median(lens))}자 (최소 {min(lens)} · 최대 {max(lens)})")
    prop["title"]["max_len"] = 0
    regions = classify.CITIES + classify.COUNTIES
    rb = sum(1 for t in titles if re.match(r"^\s*[\[\(【]\s*[가-힣]{2,6}\s*[\]\)】]", t))
    if rb / n >= 0.5:
        prop["title"]["region_bracket"] = True
        ev.append(f"제목이 [지역] 괄호로 시작하는 게시물 {rb}/{n}건")
    startreg = sum(1 for t in titles if any(t.lstrip("[( ").startswith(r[:-1]) for r in regions))
    ev.append(f"제목이 시·군 이름으로 시작하는 게시물 {startreg}/{n}건")
    pre = Counter(re.match(r"^(\[[^\]]+\]|\([^)]+\)|【[^】]+】)", t).group(1) for t in titles if re.match(r"^(\[[^\]]+\]|\([^)]+\)|【[^】]+】)", t))
    if pre and pre.most_common(1)[0][1] / n >= 0.5:
        prop["title"]["prefix"] = pre.most_common(1)[0][0] + " "
        ev.append(f"고정 말머리 후보: {pre.most_common(1)[0][0]} ({pre.most_common(1)[0][1]}/{n}건)")

    texts = [(i.get("text") or _plain(i.get("html", ""))) for i in items]
    imgs = [len(re.findall(r"<img\b", i.get("html", ""), flags=re.I)) for i in items]
    if any(i.get("html") for i in items):
        ev.append(f"게시물당 사진 수: 중앙값 {int(statistics.median(imgs))}장")
    # 말미 고정 문구
    tails = Counter()
    for t in texts:
        lines = [l.strip() for l in t.split("\n") if l.strip() and not l.strip().startswith("#")]
        for l in lines[-3:]:
            if 4 <= len(l) <= 80:
                tails[l] += 1
    fixed = [(l, c) for l, c in tails.most_common(3) if c / n >= 0.4]
    if fixed:
        prop["footer"]["text"] = "\n".join(l for l, _ in fixed)
        ev.append("말미 고정 문구 후보: " + " / ".join(f"'{l}'({c}/{n})" for l, c in fixed))
    # 첫 문단 dateline
    dl = Counter()
    for t in texts:
        m = re.match(r"^\s*([(\[【][^)\]】\n]{2,30}[)\]】])", t)
        if m:
            dl[re.sub(r"[가-힣]{2,4}(시|군)", "{지역}", m.group(1))] += 1
    if dl and dl.most_common(1)[0][1] / n >= 0.4:
        prop["body"]["dateline"] = dl.most_common(1)[0][0]
        ev.append(f"본문 첫머리 표기 후보: {dl.most_common(1)[0][0]}")
    # 해시태그
    tagged = 0
    tagc = Counter()
    for i, t in zip(items, texts):
        tags = re.findall(r"#([^\s#]+)", t) or [x.strip() for x in re.split(r"[,\s]+", i.get("tags", "")) if x.strip()]
        if tags:
            tagged += 1
            tagc.update(tags)
    if tagged / n >= 0.4:
        prop["hashtags"]["enabled"] = True
        prop["hashtags"]["fixed"] = " ".join("#" + t for t, c in tagc.most_common(5) if c / n >= 0.4)
        ev.append(f"해시태그 사용 {tagged}/{n}건, 자주 쓰는 태그: " + ", ".join(f"#{t}({c})" for t, c in tagc.most_common(6)))
    else:
        ev.append(f"해시태그 사용 {tagged}/{n}건 — 사용하지 않는 것으로 보임")
    cats = Counter(i.get("category", "") for i in items if i.get("category"))
    if cats:
        ev.append("카테고리 분포: " + ", ".join(f"{c}({k}건)" for c, k in cats.most_common(5)))
        prop["category"] = cats.most_common(1)[0][0]
    ev.append("사진 정렬·크기·캡션·출처 표기는 RSS 요약만으로 확정하기 어렵습니다. 아래 항목을 직접 선택해 주세요.")
    return {"count": n, "evidence": ev, "proposal": prop}


# ───────────── 초안 생성 ─────────────
def _fmt(tpl: str, **kw) -> str:
    try:
        return tpl.format(**kw)
    except Exception:
        return tpl


def build_draft(art: dict, photos: list[dict], g: dict | None = None) -> dict:
    """final_text(없으면 corrected_text)로 블로그 게시용 제목·HTML·태그를 만든다."""
    g = g or guide()
    text = art.get("final_text") or art.get("corrected_text") or art.get("original_text") or ""
    title = art.get("final_title") or art.get("title") or ""
    ctx = {"org": art.get("org") or "", "region": art.get("region") or "", "title": title,
           "date": (art.get("received_at") or "")[:10]}
    t = g["title"]
    if t.get("region_bracket") and art.get("region") in (classify.CITIES + classify.COUNTIES) and not title.startswith("["):
        title = f"[{art['region']}] {title}"
    title = (t.get("prefix") or "") + title + (t.get("suffix") or "")
    if t.get("max_len") and len(title) > t["max_len"]:
        title = title[: t["max_len"]].rstrip()

    paras = proofread.to_paragraphs(text)
    # 제목과 같은 첫 줄은 중복이므로 제거
    if paras and re.sub(r"\W", "", paras[0]) == re.sub(r"\W", "", art.get("final_title") or art.get("title") or ""):
        paras = paras[1:]
    if g["body"].get("dateline"):
        paras.insert(0, _fmt(g["body"]["dateline"], **ctx))

    def fig(p):
        cap = (p.get("caption") or "").strip()
        credit = (p.get("credit") or "").strip()
        c = ""
        if g["photos"].get("show_caption") and cap:
            c = html.escape(_fmt(g["photos"]["caption_template"], caption=cap, **ctx))
        if credit and g["photos"].get("credit_template"):
            c += " " + html.escape(_fmt(g["photos"]["credit_template"], credit=credit, **ctx))
        al = g["photos"].get("align", "center")
        return (f'<figure style="text-align:{al};margin:16px 0"><img src="{{IMG:{p["id"]}}}" alt="{html.escape(cap or title)}" '
                f'style="max-width:100%"><figcaption>{c}</figcaption></figure>' if c else
                f'<figure style="text-align:{al};margin:16px 0"><img src="{{IMG:{p["id"]}}}" alt="{html.escape(cap or title)}" style="max-width:100%"></figure>')

    photos = sorted(photos, key=lambda p: (not p.get("is_cover"), p.get("order_no", 0)))
    parts: list[str] = []
    lay = g["photos"].get("layout", "first_after_title")
    body_html = [f"<p>{html.escape(p)}</p>" for p in paras]
    if g["body"].get("paragraph_gap", True):
        body_html = [b + "<p><br></p>" for b in body_html]
    if photos and lay == "all_after_title":
        parts += [fig(p) for p in photos] + body_html
    elif photos and lay == "distributed" and len(paras) > 1:
        step = max(1, len(paras) // (len(photos) + 1))
        pi = 0
        for i, b in enumerate(body_html):
            parts.append(b)
            if pi < len(photos) and (i + 1) % step == 0:
                parts.append(fig(photos[pi])); pi += 1
        parts += [fig(p) for p in photos[pi:]]
    elif photos and lay == "end":
        parts += body_html + [fig(p) for p in photos]
    else:  # first_after_title
        parts += [fig(photos[0])] if photos else []
        parts += body_html + [fig(p) for p in photos[1:]]

    f = g["footer"]
    foot = []
    if f.get("source_line"):
        foot.append(_fmt(f["source_line"], **ctx))
    if f.get("reporter"):
        foot.append(f["reporter"])
    if f.get("text"):
        foot += f["text"].split("\n")
    parts += [f"<p>{html.escape(x)}</p>" for x in foot if x.strip()]

    tags = ""
    h = g["hashtags"]
    if h.get("enabled"):
        tags = " ".join(x for x in (_fmt(h.get("template", ""), **ctx), h.get("fixed", "")) if x).strip()
        if tags:
            parts.append(f"<p>{html.escape(tags)}</p>")
    return {"title": title, "html": "\n".join(parts), "hashtags": tags, "category": g.get("category", ""),
            "paragraphs": len(paras)}
