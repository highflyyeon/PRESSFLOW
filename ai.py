"""선택 기능: Claude API를 이용한 정밀 교정. 사용자가 설정에서 켠 경우에만 동작하며,
결과는 반드시 proofread.verify()를 통과해야 채택된다."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

import core

SYSTEM = """당신은 한국 신문사의 교열 기자입니다. 주어진 보도자료 본문에서 한글 맞춤법, 띄어쓰기, 단순 오탈자, 중복 문자, 잘못된 문장부호, 명백한 조사 오류만 바로잡습니다.
절대 규칙:
- 사람 이름, 기관·단체의 공식 명칭, 지명, 직책, 날짜·시간, 금액, 통계·수치, 장소, 법령명, 따옴표 안의 인용문, 사업명은 한 글자도 바꾸지 않습니다. 의심스러워도 그대로 둡니다.
- 문장을 요약하거나 추가하거나 삭제하지 않습니다. 문단 구분(빈 줄)을 유지합니다.
- 새로운 사실, 발언, 수식어를 만들지 않습니다.
- 설명·머리말·코드블록 없이 교정된 본문만 출력합니다."""


def configured() -> bool:
    return bool(core.get("ai_enabled", False)) and core.has_secret("anthropic_key")


def call(system: str, user: str, max_tokens: int = 8000, timeout: int = 120) -> str:
    key = core.get_secret("anthropic_key")
    model = core.get("ai_model", "claude-sonnet-5-5")
    body = json.dumps({"model": model, "max_tokens": max_tokens, "system": system,
                       "messages": [{"role": "user", "content": user}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, method="POST", headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"AI 서비스 오류 {e.code}: {e.read()[:200].decode('utf-8', 'replace')}")
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()


def proofread(text: str) -> str:
    return call(SYSTEM, text)


def test() -> str:
    return call("한 단어로만 답하세요.", "OK라고 답하세요.", max_tokens=20, timeout=30)
