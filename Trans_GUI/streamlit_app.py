"""
NE532 PDF 한글 번역 — Streamlit 웹앱
로컬: streamlit run streamlit_app.py
배포: Streamlit Community Cloud
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st
from deep_translator import GoogleTranslator

from app_core import (
    get_page_text,
    open_pdf,
    render_page_image,
    text_to_speech_bytes,
    translate_text,
)
from gemini_tts import GeminiSummarizer

APP_DIR = Path(__file__).resolve().parent
DEFAULT_PDF = APP_DIR / "NE532.PDF"
BANNER_IMAGE = APP_DIR / "assets" / "octonauts_banner.png"

OCTO_CSS = """
<style>
    .stApp { background-color: #88C9C1; }
    .block-container { padding-top: 1.2rem; }
    h1, h2, h3, p, label { color: #004B50 !important; }
    div[data-testid="stMetric"] {
        background: #FFFFFF;
        border: 2px solid #6BB5AE;
        border-radius: 16px;
        padding: 8px 12px;
    }
    .stButton > button {
        background-color: #004B50 !important;
        color: white !important;
        border-radius: 22px !important;
        border: none !important;
        font-weight: 700 !important;
    }
    .stButton > button:hover {
        background-color: #006870 !important;
        color: white !important;
    }
    div[data-testid="stFileUploader"] {
        background: #FFFFFF;
        border-radius: 16px;
        padding: 8px;
        border: 2px solid #6BB5AE;
    }
</style>
"""


def init_session() -> None:
    defaults = {
        "page_index": 0,
        "translations": {},
        "summaries": {},
        "audio_bytes": None,
        "pdf_name": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def load_pdf_bytes() -> tuple[bytes, str] | None:
    uploaded = st.session_state.get("uploaded_pdf")
    if uploaded is not None:
        return uploaded.getvalue(), uploaded.name
    if DEFAULT_PDF.exists():
        return DEFAULT_PDF.read_bytes(), DEFAULT_PDF.name
    return None


def cache_key(pdf_name: str, page_index: int, kind: str) -> str:
    return f"{pdf_name}:{page_index}:{kind}"


def main() -> None:
    st.set_page_config(
        page_title="NE532 번역 탐험대",
        page_icon="⚓",
        layout="wide",
    )
    st.markdown(OCTO_CSS, unsafe_allow_html=True)
    init_session()

    if BANNER_IMAGE.exists():
        st.image(str(BANNER_IMAGE), use_container_width=True)

    st.title("⚓ NE532 / LM258·358 데이터시트 번역")
    st.caption("PDF 번역 · Gemini 3줄 요약 · TTS 음성 재생")

    with st.sidebar:
        st.header("📁 PDF")
        uploaded = st.file_uploader("PDF 업로드", type=["pdf"])
        if uploaded is not None:
            st.session_state.uploaded_pdf = uploaded
            st.session_state.page_index = 0
            st.session_state.translations = {}
            st.session_state.summaries = {}
            st.session_state.audio_bytes = None

        pdf_data = load_pdf_bytes()
        if pdf_data is None:
            st.warning("PDF를 업로드하거나 NE532.PDF를 준비하세요.")
            st.stop()

        pdf_bytes, pdf_name = pdf_data
        doc = open_pdf(pdf_bytes)
        page_count = doc.page_count
        st.session_state.pdf_name = pdf_name
        st.info(f"**{pdf_name}** · {page_count}페이지")

        page_index = st.slider(
            "페이지",
            min_value=1,
            max_value=page_count,
            value=st.session_state.page_index + 1,
        ) - 1
        st.session_state.page_index = page_index

        col1, col2 = st.columns(2)
        with col1:
            if st.button("◀ 이전", use_container_width=True) and page_index > 0:
                st.session_state.page_index -= 1
                st.rerun()
        with col2:
            if st.button("다음 ▶", use_container_width=True) and page_index < page_count - 1:
                st.session_state.page_index += 1
                st.rerun()

        st.divider()
        st.header("🛠 작업")
        do_translate = st.button("현재 페이지 번역", use_container_width=True)
        do_translate_all = st.button("전체 번역", use_container_width=True)
        do_summary = st.button("3줄 요약 + TTS", use_container_width=True)

    page_index = st.session_state.page_index
    original = get_page_text(doc, page_index)
    t_key = cache_key(pdf_name, page_index, "translation")
    s_key = cache_key(pdf_name, page_index, "summary")

    if do_translate:
        with st.spinner("번역 중..."):
            translator = GoogleTranslator(source="en", target="ko")
            st.session_state.translations[t_key] = (
                translate_text(original, translator) if original else "(추출된 텍스트 없음)"
            )

    if do_translate_all:
        bar = st.progress(0)
        translator = GoogleTranslator(source="en", target="ko")
        for i in range(page_count):
            text = get_page_text(doc, i)
            key = cache_key(pdf_name, i, "translation")
            st.session_state.translations[key] = (
                translate_text(text, translator) if text else "(추출된 텍스트 없음)"
            )
            bar.progress((i + 1) / page_count)
        st.success("전체 번역 완료")

    translated = st.session_state.translations.get(t_key, "")
    if not translated:
        translated = "번역 버튼을 눌러 한글 번역을 생성하세요."

    if do_summary:
        with st.spinner("Gemini 3줄 요약 생성 중..."):
            source = (
                st.session_state.translations.get(t_key)
                if st.session_state.translations.get(t_key)
                and not st.session_state.translations[t_key].startswith("번역")
                else original
            )
            summary = GeminiSummarizer().summarize(source)
            st.session_state.summaries[s_key] = summary
            with st.spinner("TTS 음성 생성 중..."):
                st.session_state.audio_bytes = text_to_speech_bytes(summary)

    summary = st.session_state.summaries.get(
        s_key, "「3줄 요약 + TTS」 버튼을 누르면 Gemini가 요약하고 음성을 생성합니다."
    )

    col_pdf, col_en, col_ko = st.columns(3)
    with col_pdf:
        st.subheader("원본 PDF")
        st.image(render_page_image(doc, page_index), use_container_width=True)
    with col_en:
        st.subheader("영문 원문")
        st.text_area("original", original or "(텍스트 없음)", height=420, label_visibility="collapsed")
    with col_ko:
        st.subheader("한글 번역")
        st.text_area("translated", translated, height=420, label_visibility="collapsed")

    st.subheader("📚 3줄 요약 (Gemini 2.5 Flash)")
    st.text_area("summary", summary, height=110, label_visibility="collapsed")

    if st.session_state.audio_bytes is not None:
        st.audio(st.session_state.audio_bytes, format="audio/mp3")

    translated_all = [
        st.session_state.translations.get(cache_key(pdf_name, i, "translation"), "")
        for i in range(page_count)
    ]
    if any(translated_all):
        export_text = "\n\n".join(
            f"--- 페이지 {i + 1} ---\n{t or '(번역 없음)'}"
            for i, t in enumerate(translated_all)
        )
        st.download_button(
            "번역 결과 다운로드 (.txt)",
            data=export_text,
            file_name=f"{Path(pdf_name).stem}_한글번역.txt",
            mime="text/plain",
            use_container_width=True,
        )


if __name__ == "__main__":
    main()
