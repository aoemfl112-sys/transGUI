"""Gemini 3줄 요약 및 TTS 재생 모듈."""

from __future__ import annotations

import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Callable, Optional

from google import genai
from gtts import gTTS

GEMINI_MODEL = "gemini-2.5-flash"
SUMMARY_PROMPT = """다음 텍스트를 한국어로 정확히 3줄로 요약하세요.
규칙:
- 반드시 3줄만 출력
- 각 줄은 하나의 완전한 문장
- 번호, 불릿, 제목 없이 줄바꿈만 사용
- 기술 용어와 수치는 정확하게 유지

텍스트:
{text}"""


def load_api_key() -> str:
    """프로젝트 .env 또는 환경 변수에서 Gemini API 키를 읽는다."""
    for env_name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "API_KEY"):
        value = os.environ.get(env_name, "").strip()
        if value:
            return value

    for env_path in (
        Path(__file__).resolve().parent.parent / ".env",
        Path(__file__).resolve().parent / ".env",
    ):
        if not env_path.exists() or env_path.stat().st_size == 0:
            continue
        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                if key.strip().upper() in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "API_KEY"):
                    return value.strip().strip('"').strip("'")
            elif line.startswith("AIza"):
                return line
    raise ValueError(
        ".env 파일에 API 키가 없습니다.\n"
        "프로젝트 루트(d:\\cursor_pj\\.env)에 키를 저장한 뒤 다시 시도하세요."
    )


def normalize_summary(text: str) -> str:
    """Gemini 응답을 3줄 형식으로 정리한다."""
    lines: list[str] = []
    for raw in text.splitlines():
        line = re.sub(r"^[\d\.\)\-\*•]+\s*", "", raw.strip())
        if line:
            lines.append(line)
    if len(lines) > 3:
        lines = lines[:3]
    while len(lines) < 3 and lines:
        lines.append("")
    return "\n".join(lines[:3])


class GeminiSummarizer:
    def __init__(self) -> None:
        self.client = genai.Client(api_key=load_api_key())

    def summarize(self, text: str) -> str:
        text = text.strip()
        if not text:
            return "요약할 내용이 없습니다.\n-\n-"
        response = self.client.models.generate_content(
            model=GEMINI_MODEL,
            contents=SUMMARY_PROMPT.format(text=text[:8000]),
        )
        return normalize_summary(response.text or "")


class TTSEngine:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._mixer = None

    @property
    def is_playing(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def speak(self, text: str, on_done: Optional[Callable[[], None]] = None) -> None:
        self.stop()
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._play_worker,
            args=(text, on_done),
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._mixer:
            try:
                self._mixer.music.stop()
            except Exception:
                pass

    def _play_worker(self, text: str, on_done: Optional[Callable[[], None]]) -> None:
        temp_path = ""
        try:
            import pygame

            tts = gTTS(text=text.replace("\n", " "), lang="ko")
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
                temp_path = tmp.name
            tts.save(temp_path)

            if self._stop_event.is_set():
                return

            pygame.mixer.init()
            self._mixer = pygame.mixer
            self._mixer.music.load(temp_path)
            self._mixer.music.play()

            while self._mixer.music.get_busy() and not self._stop_event.is_set():
                pygame.time.Clock().tick(10)

            if not self._stop_event.is_set() and on_done:
                on_done()
        except Exception:
            raise
        finally:
            if self._mixer:
                try:
                    self._mixer.music.stop()
                    self._mixer.quit()
                except Exception:
                    pass
                self._mixer = None
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
