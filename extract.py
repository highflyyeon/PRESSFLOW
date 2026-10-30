"""문서 텍스트 추출: HWP · HWPX · DOCX · DOC · PDF · TXT. 추출 실패 시 예외 대신 상태값을 돌려준다."""
from __future__ import annotations

import re
import shutil
import struct
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile
import zlib
from pathlib import Path

DOC_EXT = {".hwp", ".hwpx", ".doc", ".docx", ".pdf", ".txt"}
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp"}


def _clean(t: str) -> str:
    t = t.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    t = re.sub(r"[​‌‍﻿]", "", t)
    t = re.sub(r"[ \t 　]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _result(text: str, status="ok", note=""):
    return {"text": text, "status": status, "note": note}


# ── TXT ──
def read_txt(path: Path):
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr", "utf-16"):
        try:
            return _result(_clean(raw.decode(enc)))
        except Exception:
            continue
    return _result("", "failed", "텍스트 인코딩을 판별하지 못했습니다.")


# ── DOCX ──
def read_docx(path: Path):
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml")
    root = ET.fromstring(xml)
    lines: list[str] = []
    for p in root.iter():
        if _local(p.tag) != "p":
            continue
        buf = []
        for e in p.iter():
            n = _local(e.tag)
            if n == "t":
                buf.append(e.text or "")
            elif n == "tab":
                buf.append("\t")
            elif n in ("br", "cr"):
                buf.append("\n")
        lines.append("".join(buf))
    return _result(_clean("\n".join(lines)))


# ── HWPX ──
def read_hwpx(path: Path):
    with zipfile.ZipFile(path) as z:
        names = sorted((n for n in z.namelist() if re.match(r"Contents/section\d+\.xml$", n)),
                       key=lambda s: int(re.findall(r"\d+", s)[-1]))
        if not names:
            return _result("", "failed", "HWPX 본문(section) 파일을 찾지 못했습니다.")
        out: list[str] = []
        for n in names:
            root = ET.fromstring(z.read(n))
            stack: list[list[str]] = []

            def walk(e):
                name = _local(e.tag)
                if name == "p":
                    stack.append([])
                if name == "t":
                    (stack[-1] if stack else out_buf).append(e.text or "")
                elif name == "tab":
                    (stack[-1] if stack else out_buf).append("\t")
                elif name == "lineBreak":
                    (stack[-1] if stack else out_buf).append("\n")
                for c in e:
                    walk(c)
                if name == "p":
                    line = "".join(stack.pop())
                    out.append(line)

            out_buf: list[str] = []
            walk(root)
    return _result(_clean("\n".join(out)))


# ── HWP (바이너리) ──
def _hwp_para(rec: bytes) -> str:
    s, i, n = [], 0, len(rec) // 2
    while i < n:
        c = struct.unpack_from("<H", rec, i * 2)[0]
        if c >= 32:
            s.append(chr(c))
        elif c in (13,):
            s.append("\n")
        elif c == 10:
            s.append("\n")
        elif c in (0, 24, 25, 26, 27, 28, 29):
            pass
        elif c in (30, 31):
            s.append(" ")
        elif c == 9:
            s.append("\t")
            i += 7
        else:  # 확장/인라인 컨트롤은 8 wchar
            i += 7
        i += 1
    return "".join(s)


def read_hwp(path: Path):
    import olefile
    if zipfile.is_zipfile(path):
        return read_hwpx(path)
    if not olefile.isOleFile(str(path)):
        return _result("", "failed", "HWP 파일 형식이 아닙니다(손상 또는 구버전).")
    ole = olefile.OleFileIO(str(path))
    try:
        flags = struct.unpack("<I", ole.openstream("FileHeader").read()[36:40])[0]
        compressed, encrypted, dist = flags & 1, flags & 2, flags & 4
        if encrypted:
            return _result("", "manual", "암호가 설정된 HWP 문서입니다. 암호를 해제한 뒤 다시 첨부하세요.")
        if dist:
            return _result("", "manual", "배포용(읽기 전용) HWP 문서입니다. 한글에서 '편집 가능'으로 저장한 파일이 필요합니다.")
        secs = sorted((e for e in ole.listdir() if len(e) == 2 and e[0] == "BodyText" and e[1].startswith("Section")),
                      key=lambda e: int(re.findall(r"\d+", e[1])[0]))
        out = []
        for e in secs:
            data = ole.openstream(e).read()
            if compressed:
                data = zlib.decompress(data, -15)
            pos = 0
            while pos + 4 <= len(data):
                h = struct.unpack_from("<I", data, pos)[0]
                pos += 4
                tag, size = h & 0x3FF, (h >> 20) & 0xFFF
                if size == 0xFFF:
                    size = struct.unpack_from("<I", data, pos)[0]
                    pos += 4
                rec = data[pos:pos + size]
                pos += size
                if tag == 67:  # HWPTAG_PARA_TEXT
                    out.append(_hwp_para(rec))
        return _result(_clean("\n".join(out)))
    finally:
        ole.close()


# ── PDF ──
def read_pdf(path: Path):
    from pypdf import PdfReader
    r = PdfReader(str(path))
    if r.is_encrypted:
        try:
            r.decrypt("")
        except Exception:
            return _result("", "manual", "암호가 설정된 PDF입니다.")
    txt = "\n\n".join((pg.extract_text() or "") for pg in r.pages)
    txt = _clean(txt)
    if len(re.sub(r"\s", "", txt)) < 20:
        return _result(txt, "manual", "텍스트 레이어가 없는 스캔 PDF로 보입니다(OCR 필요). 원본은 보존되었습니다.")
    return _result(txt)


# ── DOC (구형 워드) ──
def read_doc(path: Path):
    for tool, args in (("antiword", [str(path)]), ("catdoc", [str(path)])):
        if shutil.which(tool):
            r = subprocess.run([tool, *args], capture_output=True, timeout=60)
            if r.returncode == 0 and r.stdout.strip():
                return _result(_clean(r.stdout.decode("utf-8", "replace")))
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        with tempfile.TemporaryDirectory() as td:
            subprocess.run([soffice, "--headless", "--convert-to", "txt:Text", "--outdir", td, str(path)],
                           capture_output=True, timeout=120)
            for f in Path(td).glob("*.txt"):
                return read_txt(f)
    return _result("", "manual", "구형 .doc 문서는 이 컴퓨터에서 추출할 수 없습니다(LibreOffice 설치 시 자동 처리). 원본은 보존되었습니다.")


def extract(path: Path) -> dict:
    ext = path.suffix.lower()
    try:
        if ext == ".txt":
            return read_txt(path)
        if ext == ".docx":
            return read_docx(path)
        if ext == ".hwpx":
            return read_hwpx(path)
        if ext == ".hwp":
            return read_hwp(path)
        if ext == ".pdf":
            return read_pdf(path)
        if ext == ".doc":
            return read_doc(path)
        return _result("", "failed", "지원하지 않는 문서 형식입니다.")
    except Exception as e:  # 원본은 항상 보존, 상태만 실패로 기록
        return _result("", "failed", f"추출 오류: {type(e).__name__}: {e}"[:300])
