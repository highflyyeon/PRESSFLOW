#!/usr/bin/env python3
"""배포자 전용 도구 — 새 버전을 서명해서 올릴 묶음으로 만든다. (사용자 컴퓨터에는 필요 없음)

  python make_release.py keygen                 최초 1회: 서명 키 생성(개인키는 release_private.key, 공개키는 update_channel.json)
  python make_release.py build [--bump patch|minor|major] [--notes "변경 내용"]
  python make_release.py add-installer <설치파일.exe>   (CI가 사용) latest.json 에 설치 파일 서명 추가
  python make_release.py url <업데이트 주소>     사용자 프로그램이 확인할 latest.json 주소를 update_channel.json 에 기록

build 결과(dist/): PRESSFLOW-x.y.z.zip + latest.json  → 두 파일을 같은 곳(웹 주소 또는 공유 폴더)에 올리면 끝.
※ release_private.key 는 절대 공유·업로드하지 마세요. 분실하면 기존 설치본에 업데이트를 보낼 수 없습니다.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import sys
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
KEYFILE = ROOT / "release_private.key"
CHANNEL = ROOT / "update_channel.json"
EXCLUDE_TOP = {"installer", ".github", "build", "PRESSFLOW.spec", "venv", ".update", "dist", "release_private.key", "update_channel.json", ".git", "__pycache__", "make_release.py"}


def keygen():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    if KEYFILE.exists():
        sys.exit("이미 키가 있습니다(release_private.key). 덮어쓰지 않습니다.")
    k = Ed25519PrivateKey.generate()
    KEYFILE.write_bytes(base64.b64encode(k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())))
    try:
        KEYFILE.chmod(0o600)
    except Exception:
        pass
    pub = base64.b64encode(k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    ch = json.loads(CHANNEL.read_text(encoding="utf-8")) if CHANNEL.exists() else {}
    ch["public_key"] = pub
    ch.setdefault("manifest_url", "")
    CHANNEL.write_text(json.dumps(ch, indent=2, ensure_ascii=False), encoding="utf-8")
    print("키를 만들었습니다. release_private.key 는 안전한 곳에 따로 백업하세요(공유 금지).")


def set_url(u):
    ch = json.loads(CHANNEL.read_text(encoding="utf-8")) if CHANNEL.exists() else {}
    ch["manifest_url"] = u
    CHANNEL.write_text(json.dumps(ch, indent=2, ensure_ascii=False), encoding="utf-8")
    print("업데이트 주소를 기록했습니다:", u)


def bump(kind):
    p = ROOT / "core.py"
    s = p.read_text(encoding="utf-8")
    m = re.search(r'^VERSION\s*=\s*"(\d+)\.(\d+)\.(\d+)"', s, re.M)
    a, b, c = map(int, m.groups())
    a, b, c = {"major": (a + 1, 0, 0), "minor": (a, b + 1, 0), "patch": (a, b, c + 1)}[kind]
    s = s[:m.start()] + f'VERSION = "{a}.{b}.{c}"' + s[m.end():]
    p.write_text(s, encoding="utf-8")


def add_installer(path, name=None):
    """dist/latest.json 에 윈도우 설치 파일 항목을 서명해서 추가한다."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = KEYFILE.read_bytes() if KEYFILE.exists() else None
    if key is None:
        sys.exit("서명 개인키가 없습니다.")
    f = Path(path)
    lj = ROOT / "dist" / "latest.json"
    m = json.loads(lj.read_text(encoding="utf-8"))
    sha = hashlib.sha256(f.read_bytes()).hexdigest()
    sig = base64.b64encode(Ed25519PrivateKey.from_private_bytes(base64.b64decode(key)).sign(f"{m['version']}:{sha}".encode())).decode()
    m.setdefault("installer", {})["windows"] = {"file": name or f.name, "sha256": sha, "sig": sig}
    lj.write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
    print("설치 파일 항목을 latest.json 에 추가했습니다:", f.name)


def build(kind=None, notes=""):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    if not KEYFILE.exists():
        sys.exit("먼저 `python make_release.py keygen` 을 실행하세요.")
    if kind:
        bump(kind)
    ver = re.search(r'^VERSION\s*=\s*"([^"]+)"', (ROOT / "core.py").read_text(encoding="utf-8"), re.M).group(1)
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    name = f"PRESSFLOW-{ver}.zip"
    with zipfile.ZipFile(dist / name, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(ROOT.rglob("*")):
            rel = p.relative_to(ROOT)
            if not p.is_file() or rel.parts[0] in EXCLUDE_TOP or "__pycache__" in rel.parts or p.suffix == ".pyc":
                continue
            z.write(p, rel.as_posix())
    sha = hashlib.sha256((dist / name).read_bytes()).hexdigest()
    sig = base64.b64encode(Ed25519PrivateKey.from_private_bytes(base64.b64decode(KEYFILE.read_bytes())).sign(f"{ver}:{sha}".encode())).decode()
    (dist / "latest.json").write_text(json.dumps({"version": ver, "file": name, "sha256": sha, "sig": sig, "notes": notes,
                                                  "date": date.today().isoformat(), "min_python": "3.10"}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"만들었습니다: dist/{name}, dist/latest.json  (버전 {ver})\n두 파일을 업데이트 주소가 가리키는 곳에 올리세요.")


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        print(__doc__)
    elif a[0] == "keygen":
        keygen()
    elif a[0] == "url" and len(a) > 1:
        set_url(a[1])
    elif a[0] == "add-installer" and len(a) > 1:
        add_installer(a[1])
    elif a[0] == "build":
        build(a[a.index("--bump") + 1] if "--bump" in a else None, a[a.index("--notes") + 1] if "--notes" in a else "")
    else:
        print(__doc__)
