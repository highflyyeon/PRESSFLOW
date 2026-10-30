"""체험·테스트용 예시 보도자료. 실제 파이프라인(저장·추출·분류·교정·초안)을 그대로 통과시킨다.
실제 업무 데이터와 섞이지 않도록, 실제 수집 메일이 있는 데이터 폴더에서는 실행되지 않는다."""
from __future__ import annotations

import io
import zipfile
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid

from PIL import Image, ImageDraw
from werkzeug.security import generate_password_hash

import core
import pipeline


def _docx(paragraphs: list[str]) -> bytes:
    body = "".join(f"<w:p><w:r><w:t xml:space=\"preserve\">{p}</w:t></w:r></w:p>" for p in paragraphs)
    doc = ('<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           f"<w:body>{body}</w:body></w:document>")
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" '
                   'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("word/document.xml", doc)
    return b.getvalue()


def _hwpx(paragraphs: list[str]) -> bytes:
    ps = "".join(f"<hp:p><hp:run><hp:t>{p}</hp:t></hp:run></hp:p>" for p in paragraphs)
    sec = ('<?xml version="1.0" encoding="UTF-8"?><hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
           f'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">{ps}</hs:sec>')
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("mimetype", "application/hwp+zip")
        z.writestr("Contents/section0.xml", sec)
    return b.getvalue()


def _jpg(label: str, color) -> bytes:
    im = Image.new("RGB", (1600, 1067), color)
    d = ImageDraw.Draw(im)
    for i in range(0, 1600, 80):
        d.line([(i, 0), (1600 - i, 1067)], fill=(255, 255, 255), width=2)
    d.rectangle([40, 40, 1560, 1027], outline=(255, 255, 255), width=6)
    b = io.BytesIO()
    im.save(b, "JPEG", quality=92)
    return b.getvalue()


def _mail(sender_name, sender, subject, body, attachments, hours_ago=2, dup_of: str | None = None) -> bytes:
    m = EmailMessage()
    m["From"] = f"{sender_name} <{sender}>"
    m["To"] = "press@example.kr"
    m["Subject"] = subject
    m["Date"] = format_datetime(datetime.now().astimezone() - timedelta(hours=hours_ago))
    m["Message-ID"] = dup_of or make_msgid(domain="demo.pressflow")
    m.set_content(body)
    for fn, data, mt, st in attachments:
        m.add_attachment(data, maintype=mt, subtype=st, filename=fn)
    return m.as_bytes()


WONJU = [
    "원주시, 취약계층 복지지원 사업 확대",
    "원주시가 지역내 취약계층의 복지서비스 확대를 위해 새로운 사업을 추진 한다고 밝혔다.",
    "이번 사업은 2026년 11월부터 12월까지 관내 저소득 가구 1,250 가구를 대상으로 하며, 총 사업비는 3억 5천만원 규모다.",
    "시는 오는 11월 7일(금) 오후 2시 시청 대회의실에서 사업 설명회를 열 예정이다.",
    "원주시 복지정책과장은 “어려운 이웃이 소외되지 않도록 현장 중심으로 꼼꼼히 챙기겠다”고 말했다.",
    "문의 : 복지정책과 033-000-0000",
]
PROV = [
    "강원특별자치도, 사회복지시설 종사자 처우개선 추진",
    "강원특별자치도는 사회복지시설 종사자의 처우 개선을 위해 내년도 예산에 12억원을 반영했다고 밝혔다.",
    "도는 18개 시군과 협력하여 현장의 의견을 듣고 단계적으로 지원 범위를 넓혀 나갈 계획이다.",
    "이번 계획은 종사자 근무 환경을 개선하고 서비스의 질을 높이는데 목적이 있다.",
]
ORG = [
    "강원특별자치도사회복지협의회, 연말 나눔 캠페인 개최",
    "강원특별자치도사회복지협의회는 연말을 맞아 ‘희망나눔 캠페인’을 개최한다고 밝혔다.",
    "이번 캠페인은 12월 한 달간 도내 복지관과 함께 진행되며 후원금은 취약계층 지원에 사용된다.",
]
UNK = [
    "취약 노인 안부 확인 사업 시작",
    "엠바고: 11월 3일 오전 9시 이후 보도 바랍니다.",
    "이번 사업은 홀로 사는 노인의 안부를 정기적으로 확인하기 위한 것이다. 담당자 연락처 010-1234-5678",
]


def seed():
    core.init_db()
    if core.row("SELECT 1 FROM mails WHERE uidv<>'demo' LIMIT 1"):
        print("이 데이터 폴더에는 실제 수집 메일이 있어 체험 자료를 넣지 않습니다.\n"
              "별도 폴더에서 실행하세요:  PRESSFLOW_HOME=~/PRESSFLOW_DEMO python pressflow.py demo")
        return
    if not core.row("SELECT 1 FROM users LIMIT 1"):
        core.run("INSERT INTO users(username,display,pw_hash,role,created) VALUES(?,?,?,?,?)",
                 "demo", "체험 관리자", generate_password_hash("pressflow-demo"), "admin", core.now_iso())
        core.put("setup_done", True)
        print("체험 계정 → 아이디: demo / 비밀번호: pressflow-demo")
    first = "<dup-demo@demo.pressflow>"
    mails = [
        _mail("원주시청 복지정책과", "welfare@wonju-example.kr", "[보도자료] 원주시, 취약계층 복지지원 사업 확대", "보도자료를 송부합니다.",
              [("원주시 복지지원 보도자료.docx", _docx(WONJU), "application", "vnd.openxmlformats-officedocument.wordprocessingml.document"),
               ("현장_01.jpg", _jpg("a", (30, 110, 98)), "image", "jpeg"), ("현장_02.jpg", _jpg("b", (200, 140, 40)), "image", "jpeg")], 3, first),
        _mail("강원특별자치도 사회복지과", "sw@provin-example.kr", "[보도자료] 사회복지시설 종사자 처우개선", "붙임 참조",
              [("보도자료.hwpx", _hwpx(PROV), "application", "octet-stream"), ("도청사진.jpg", _jpg("c", (40, 70, 120)), "image", "jpeg")], 5),
        _mail("강원특별자치도사회복지협의회", "info@kasw-example.or.kr", "연말 나눔 캠페인 보도자료", "\n".join(ORG),
              [("campaign.txt", "\n".join(ORG).encode("utf-8"), "text", "plain")], 8),
        _mail("홍보담당", "pr.team@gmail.com", "취약 노인 안부 확인 사업", "\n".join(UNK), [], 12),
        _mail("원주시청 복지정책과", "welfare@wonju-example.kr", "[보도자료] 원주시, 취약계층 복지지원 사업 확대 (재발송)", "보도자료를 다시 송부합니다.",
              [("원주시 복지지원 보도자료.docx", _docx(WONJU), "application", "vnd.openxmlformats-officedocument.wordprocessingml.document")], 1),
        _mail("영월군청", "ywg@yeongwol-example.kr", "[보도자료] 영월군 경로당 지원", "첨부 확인 바랍니다.",
              [("깨진파일.hwp", b"not a real hwp file", "application", "octet-stream")], 20),
    ]
    for i, raw in enumerate(mails, 1):
        pipeline.ingest_mail(raw, "demo", i)
    n = core.row("SELECT COUNT(*) FROM articles")[0]
    print(f"예시 보도자료 {len(mails)}통 → 기사 {n}건을 처리했습니다.")
