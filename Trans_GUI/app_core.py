"""PDF 추출·번역 공통 로직 (GUI / Streamlit 공용)."""

from __future__ import annotations

import io
import re

import fitz
from deep_translator import GoogleTranslator
from PIL import Image

CHUNK_SIZE = 4500


def clean_text(text: str) -> str:
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def translate_text(text: str, translator: GoogleTranslator) -> str:
    text = clean_text(text)
    if not text:
        return ""

    paragraphs = text.split("\n")
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para) + 1
        if current_len + para_len > CHUNK_SIZE and current:
            chunks.append("\n".join(current))
            current = [para]
            current_len = para_len
        else:
            current.append(para)
            current_len += para_len

    if current:
        chunks.append("\n".join(current))

    return "\n\n".join(
        translator.translate(chunk) for chunk in chunks if chunk.strip()
    )


def open_pdf(source: bytes | str) -> fitz.Document:
    if isinstance(source, bytes):
        return fitz.open(stream=source, filetype="pdf")
    return fitz.open(source)


def get_page_text(doc: fitz.Document, page_index: int) -> str:
    return clean_text(doc[page_index].get_text())


def render_page_image(doc: fitz.Document, page_index: int, zoom: float = 1.5) -> Image.Image:
    page = doc[page_index]
    matrix = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def text_to_speech_bytes(text: str) -> io.BytesIO:
    from gtts import gTTS

    tts = gTTS(text=text.replace("\n", " "), lang="ko")
    buf = io.BytesIO()
    tts.write_to_fp(buf)
    buf.seek(0)
    return buf
