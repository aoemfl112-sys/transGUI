"""
NE532 PDF 한글 번역 GUI
Philips Semiconductors NE/SA/SE532 데이터시트 번역 도구
"""

from __future__ import annotations

import json
import re
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
import fitz
from deep_translator import GoogleTranslator
from PIL import Image, ImageTk

from gemini_tts import GeminiSummarizer, TTSEngine

APP_DIR = Path(__file__).resolve().parent
DEFAULT_PDF = APP_DIR / "NE532.PDF"
CACHE_FILE = APP_DIR / "translation_cache.json"
SUMMARY_CACHE_FILE = APP_DIR / "summary_cache.json"
BANNER_IMAGE = APP_DIR / "assets" / "octonauts_banner.png"
CHUNK_SIZE = 4500


class OctoTheme:
    """Octonauts 이미지 기반 컬러 팔레트."""

    BG = "#88C9C1"
    BG_DEEP = "#6BB5AE"
    PANEL = "#FFFFFF"
    PANEL_INNER = "#F0FAF9"
    ACCENT = "#004B50"
    ACCENT_HOVER = "#006870"
    ACCENT_LIGHT = "#2D6A6A"
    CORAL = "#E8873A"
    CORAL_HOVER = "#F5A04A"
    TEXT = "#004B50"
    TEXT_MUTED = "#4A7A7A"
    TEXT_ON_ACCENT = "#FFFFFF"
    RADIUS = 16
    RADIUS_PILL = 22
    BANNER_H = 128


def clean_text(text: str) -> str:
    """PDF 추출 텍스트에서 제어 문자·과도한 공백을 정리한다."""
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def translate_text(text: str, translator: GoogleTranslator) -> str:
    """긴 텍스트를 단락 단위로 나눠 번역한다."""
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

    translated_parts = []
    for chunk in chunks:
        if chunk.strip():
            translated_parts.append(translator.translate(chunk))

    return "\n\n".join(translated_parts)


class TranslationCache:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, dict[str, str]] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                with open(self.path, encoding="utf-8") as f:
                    self.data = json.load(f)
            except (json.JSONDecodeError, OSError):
                self.data = {}

    def save(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def get(self, pdf_key: str, page: int) -> str | None:
        return self.data.get(pdf_key, {}).get(str(page))

    def set(self, pdf_key: str, page: int, translation: str) -> None:
        self.data.setdefault(pdf_key, {})[str(page)] = translation
        self.save()


class SummaryCache:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, dict[str, str]] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                with open(self.path, encoding="utf-8") as f:
                    self.data = json.load(f)
            except (json.JSONDecodeError, OSError):
                self.data = {}

    def save(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def get(self, pdf_key: str, page: int) -> str | None:
        return self.data.get(pdf_key, {}).get(str(page))

    def set(self, pdf_key: str, page: int, summary: str) -> None:
        self.data.setdefault(pdf_key, {})[str(page)] = summary
        self.save()


class NE532TranslatorApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()

        self.title("⚓ NE532 번역 탐험대")
        self.geometry("1400x960")
        self.minsize(1100, 760)
        self.configure(fg_color=OctoTheme.BG)

        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")

        self.banner_ref: ImageTk.PhotoImage | None = None
        self.pdf_path: Path | None = None
        self.doc: fitz.Document | None = None
        self.current_page = 0
        self.page_count = 0
        self.pdf_image_ref: ImageTk.PhotoImage | None = None
        self.is_translating = False
        self.is_summarizing = False
        self.cache = TranslationCache(CACHE_FILE)
        self.summary_cache = SummaryCache(SUMMARY_CACHE_FILE)
        self.translator = GoogleTranslator(source="en", target="ko")
        self.summarizer: GeminiSummarizer | None = None
        self.tts = TTSEngine()

        self._build_ui()
        self._load_pdf(DEFAULT_PDF if DEFAULT_PDF.exists() else None)

    def _octo_font(self, size: int = 13, weight: str = "normal") -> ctk.CTkFont:
        return ctk.CTkFont(family="Segoe UI", size=size, weight=weight)

    def _octo_btn(
        self,
        parent,
        text: str,
        command,
        width: int = 100,
        accent: bool = True,
        coral: bool = False,
    ) -> ctk.CTkButton:
        if coral:
            fg, hover = OctoTheme.CORAL, OctoTheme.CORAL_HOVER
        elif accent:
            fg, hover = OctoTheme.ACCENT, OctoTheme.ACCENT_HOVER
        else:
            fg, hover = OctoTheme.ACCENT_LIGHT, OctoTheme.ACCENT
        return ctk.CTkButton(
            parent,
            text=text,
            width=width,
            command=command,
            fg_color=fg,
            hover_color=hover,
            text_color=OctoTheme.TEXT_ON_ACCENT,
            corner_radius=OctoTheme.RADIUS_PILL,
            font=self._octo_font(13, "bold"),
        )

    def _octo_panel(self, parent, **kwargs) -> ctk.CTkFrame:
        return ctk.CTkFrame(
            parent,
            fg_color=OctoTheme.PANEL,
            corner_radius=OctoTheme.RADIUS,
            border_width=2,
            border_color=OctoTheme.BG_DEEP,
            **kwargs,
        )

    def _load_banner(self) -> None:
        if not BANNER_IMAGE.exists():
            return
        img = Image.open(BANNER_IMAGE).convert("RGB")
        ratio = OctoTheme.BANNER_H / img.height
        new_w = max(1, int(img.width * ratio))
        img = img.resize((new_w, OctoTheme.BANNER_H), Image.Resampling.LANCZOS)
        self.banner_ref = ImageTk.PhotoImage(img)
        self.banner_label.configure(image=self.banner_ref, width=new_w)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self.grid_rowconfigure(3, weight=0)

        banner_wrap = ctk.CTkFrame(self, fg_color=OctoTheme.BG_DEEP, corner_radius=0)
        banner_wrap.grid(row=0, column=0, sticky="ew")
        self.banner_label = ctk.CTkLabel(banner_wrap, text="", fg_color=OctoTheme.BG_DEEP)
        self.banner_label.pack(pady=(10, 6))
        self._load_banner()

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=1, column=0, sticky="ew", padx=20, pady=(6, 4))
        header.grid_columnconfigure(1, weight=1)

        title_badge = ctk.CTkFrame(
            header,
            fg_color=OctoTheme.ACCENT,
            corner_radius=OctoTheme.RADIUS_PILL,
        )
        title_badge.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            title_badge,
            text="  ⚓ NE532 / LM258·358 데이터시트 번역  ",
            font=self._octo_font(18, "bold"),
            text_color=OctoTheme.TEXT_ON_ACCENT,
        ).pack(padx=4, pady=6)

        self.file_label = ctk.CTkLabel(
            header,
            text="파일 없음",
            text_color=OctoTheme.TEXT_MUTED,
            font=self._octo_font(13),
        )
        self.file_label.grid(row=0, column=1, sticky="e", padx=12)

        self._octo_btn(header, "PDF 열기", self._open_pdf, width=110).grid(
            row=0, column=2, padx=(8, 0)
        )

        body = self._octo_panel(self)
        body.grid(row=2, column=0, sticky="nsew", padx=20, pady=6)
        body.grid_columnconfigure(0, weight=2)
        body.grid_columnconfigure(1, weight=2)
        body.grid_columnconfigure(2, weight=2)
        body.grid_rowconfigure(0, weight=1)

        self._add_panel(body, 0, "원본 PDF", "pdf")
        self._add_panel(body, 1, "영문 원문", "original")
        self._add_panel(body, 2, "한글 번역", "translated")

        summary_section = self._octo_panel(self)
        summary_section.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 6))
        summary_section.grid_columnconfigure(0, weight=1)

        summary_header = ctk.CTkFrame(summary_section, fg_color="transparent")
        summary_header.grid(row=0, column=0, sticky="ew", pady=(10, 4))
        summary_header.grid_columnconfigure(0, weight=1)

        summary_badge = ctk.CTkFrame(
            summary_header,
            fg_color=OctoTheme.CORAL,
            corner_radius=OctoTheme.RADIUS_PILL,
        )
        summary_badge.grid(row=0, column=0, sticky="w", padx=10)
        ctk.CTkLabel(
            summary_badge,
            text="  📚 3줄 요약 (Gemini 2.5 Flash)  ",
            font=self._octo_font(14, "bold"),
            text_color=OctoTheme.TEXT_ON_ACCENT,
        ).pack(padx=2, pady=5)

        summary_actions = ctk.CTkFrame(summary_header, fg_color="transparent")
        summary_actions.grid(row=0, column=1, sticky="e", padx=8)

        self.summarize_tts_btn = self._octo_btn(
            summary_actions,
            "요약 + 음성 재생",
            self._summarize_and_speak,
            width=150,
            coral=True,
        )
        self.summarize_tts_btn.grid(row=0, column=0, padx=4)

        self.speak_btn = self._octo_btn(
            summary_actions, "▶ 재생", self._speak_summary, width=80
        )
        self.speak_btn.grid(row=0, column=1, padx=4)

        self.stop_btn = self._octo_btn(
            summary_actions,
            "⏹ 정지",
            self._stop_speech,
            width=80,
            accent=False,
        )
        self.stop_btn.grid(row=0, column=2, padx=4)

        self.summary_text = ctk.CTkTextbox(
            summary_section,
            height=90,
            font=ctk.CTkFont(family="Malgun Gothic", size=14),
            wrap="word",
            fg_color=OctoTheme.PANEL_INNER,
            text_color=OctoTheme.TEXT,
            corner_radius=12,
            border_width=1,
            border_color=OctoTheme.BG_DEEP,
        )
        self.summary_text.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 10))
        self.summary_text.insert(
            "1.0", "요약 + 음성 재생 버튼을 누르면 Gemini가 3줄로 요약하고 TTS로 읽어줍니다."
        )
        self.summary_text.configure(state="disabled")

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=4, column=0, sticky="ew", padx=20, pady=(4, 14))
        footer.grid_columnconfigure(1, weight=1)

        nav = ctk.CTkFrame(footer, fg_color="transparent")
        nav.grid(row=0, column=0, sticky="w")

        self.prev_btn = self._octo_btn(nav, "◀ 이전", self._prev_page, width=88)
        self.prev_btn.grid(row=0, column=0, padx=(0, 4))

        self.page_label = ctk.CTkLabel(
            nav,
            text="0 / 0",
            text_color=OctoTheme.TEXT,
            font=self._octo_font(14, "bold"),
        )
        self.page_label.grid(row=0, column=1, padx=8)

        self.next_btn = self._octo_btn(nav, "다음 ▶", self._next_page, width=88)
        self.next_btn.grid(row=0, column=2, padx=(4, 0))

        self.page_slider = ctk.CTkSlider(
            footer,
            from_=1,
            to=1,
            number_of_steps=0,
            command=self._on_slider,
            button_color=OctoTheme.ACCENT,
            button_hover_color=OctoTheme.ACCENT_HOVER,
            progress_color=OctoTheme.CORAL,
            fg_color=OctoTheme.BG_DEEP,
        )
        self.page_slider.grid(row=0, column=1, sticky="ew", padx=16)

        actions = ctk.CTkFrame(footer, fg_color="transparent")
        actions.grid(row=0, column=2, sticky="e")

        self.translate_page_btn = self._octo_btn(
            actions, "현재 페이지 번역", self._translate_current_page, width=140
        )
        self.translate_page_btn.grid(row=0, column=0, padx=4)

        self.translate_all_btn = self._octo_btn(
            actions, "전체 번역", self._translate_all_pages, width=108, accent=False
        )
        self.translate_all_btn.grid(row=0, column=1, padx=4)

        self.export_btn = self._octo_btn(
            actions, "번역 저장", self._export_translation, width=108
        )
        self.export_btn.grid(row=0, column=2, padx=4)

        self.progress = ctk.CTkProgressBar(
            footer,
            width=200,
            progress_color=OctoTheme.CORAL,
            fg_color=OctoTheme.BG_DEEP,
        )
        self.progress.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        self.progress.set(0)

        self.status_label = ctk.CTkLabel(
            footer,
            text="🌊 PDF를 불러오세요.",
            text_color=OctoTheme.TEXT_MUTED,
            font=self._octo_font(12),
        )
        self.status_label.grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))

    def _add_panel(self, parent: ctk.CTkFrame, col: int, title: str, key: str) -> None:
        frame = ctk.CTkFrame(
            parent,
            fg_color=OctoTheme.PANEL_INNER,
            corner_radius=12,
            border_width=1,
            border_color=OctoTheme.BG_DEEP,
        )
        frame.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 8, 0), pady=8)
        frame.grid_rowconfigure(1, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        title_chip = ctk.CTkFrame(
            frame, fg_color=OctoTheme.ACCENT, corner_radius=OctoTheme.RADIUS_PILL
        )
        title_chip.grid(row=0, column=0, sticky="w", padx=10, pady=(10, 6))
        ctk.CTkLabel(
            title_chip,
            text=f"  {title}  ",
            font=self._octo_font(13, "bold"),
            text_color=OctoTheme.TEXT_ON_ACCENT,
        ).pack(padx=2, pady=4)

        if key == "pdf":
            self.pdf_canvas = tk.Canvas(
                frame,
                bg=OctoTheme.PANEL,
                highlightthickness=1,
                highlightbackground=OctoTheme.BG_DEEP,
            )
            self.pdf_canvas.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
            self.pdf_scroll_y = ctk.CTkScrollbar(
                frame,
                command=self.pdf_canvas.yview,
                button_color=OctoTheme.ACCENT,
                button_hover_color=OctoTheme.ACCENT_HOVER,
            )
            self.pdf_scroll_y.grid(row=1, column=1, sticky="ns", pady=(0, 10))
            self.pdf_canvas.configure(yscrollcommand=self.pdf_scroll_y.set)
        else:
            textbox = ctk.CTkTextbox(
                frame,
                font=ctk.CTkFont(family="Malgun Gothic", size=13),
                wrap="word",
                fg_color=OctoTheme.PANEL,
                text_color=OctoTheme.TEXT,
                corner_radius=10,
                border_width=1,
                border_color=OctoTheme.BG_DEEP,
            )
            textbox.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
            if key == "original":
                self.original_text = textbox
            else:
                self.translated_text = textbox

    def _pdf_key(self) -> str:
        if not self.pdf_path:
            return ""
        return self.pdf_path.name

    def _set_status(self, message: str) -> None:
        self.status_label.configure(text=message)

    def _set_buttons_state(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for btn in (
            self.prev_btn,
            self.next_btn,
            self.translate_page_btn,
            self.translate_all_btn,
            self.export_btn,
            self.summarize_tts_btn,
            self.speak_btn,
        ):
            btn.configure(state=state)

    def _open_pdf(self) -> None:
        path = filedialog.askopenfilename(
            title="PDF 파일 선택",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
            initialdir=str(APP_DIR),
        )
        if path:
            self._load_pdf(Path(path))

    def _load_pdf(self, path: Path | None) -> None:
        if path is None or not path.exists():
            self._set_status("PDF 파일을 찾을 수 없습니다.")
            return

        if self.doc:
            self.doc.close()

        try:
            self.doc = fitz.open(path)
        except Exception as exc:
            messagebox.showerror("오류", f"PDF를 열 수 없습니다.\n{exc}")
            return

        self.pdf_path = path
        self.page_count = self.doc.page_count
        self.current_page = 0

        self.file_label.configure(text=path.name)
        self.page_slider.configure(
            from_=1, to=max(1, self.page_count), number_of_steps=max(0, self.page_count - 1)
        )
        self.page_slider.set(1)
        self._show_page(0)
        self._set_status(f"{path.name} — {self.page_count}페이지 로드됨")

    def _show_page(self, page_index: int) -> None:
        if not self.doc or self.page_count == 0:
            return

        page_index = max(0, min(page_index, self.page_count - 1))
        self.current_page = page_index

        self.page_label.configure(text=f"{page_index + 1} / {self.page_count}")
        self.page_slider.set(page_index + 1)

        self._render_pdf_page(page_index)
        self._show_original_text(page_index)
        self._show_cached_translation(page_index)
        self._show_cached_summary(page_index)

    def _render_pdf_page(self, page_index: int) -> None:
        assert self.doc is not None
        page = self.doc[page_index]
        zoom = 1.5
        matrix = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        self.pdf_image_ref = ImageTk.PhotoImage(img)

        self.pdf_canvas.delete("all")
        self.pdf_canvas.create_image(0, 0, anchor="nw", image=self.pdf_image_ref)
        self.pdf_canvas.configure(scrollregion=(0, 0, pix.width, pix.height))

    def _get_page_text(self, page_index: int) -> str:
        assert self.doc is not None
        return clean_text(self.doc[page_index].get_text())

    def _show_original_text(self, page_index: int) -> None:
        self.original_text.configure(state="normal")
        self.original_text.delete("1.0", "end")
        self.original_text.insert("1.0", self._get_page_text(page_index))
        self.original_text.configure(state="disabled")

    def _show_cached_translation(self, page_index: int) -> None:
        cached = self.cache.get(self._pdf_key(), page_index)
        self.translated_text.configure(state="normal")
        self.translated_text.delete("1.0", "end")
        if cached:
            self.translated_text.insert("1.0", cached)
        else:
            self.translated_text.insert(
                "1.0", "번역되지 않았습니다.\n'현재 페이지 번역' 또는 '전체 번역'을 눌러주세요."
            )
        self.translated_text.configure(state="disabled")

    def _show_cached_summary(self, page_index: int) -> None:
        cached = self.summary_cache.get(self._pdf_key(), page_index)
        self.summary_text.configure(state="normal")
        self.summary_text.delete("1.0", "end")
        if cached:
            self.summary_text.insert("1.0", cached)
        else:
            self.summary_text.insert(
                "1.0",
                "요약 + 음성 재생 버튼을 누르면 Gemini가 3줄로 요약하고 TTS로 읽어줍니다.",
            )
        self.summary_text.configure(state="disabled")

    def _get_summarizer(self) -> GeminiSummarizer:
        if self.summarizer is None:
            self.summarizer = GeminiSummarizer()
        return self.summarizer

    def _get_summary_source_text(self, page_index: int) -> str:
        pdf_key = self._pdf_key()
        translated = self.cache.get(pdf_key, page_index)
        if translated and not translated.startswith("("):
            return translated
        return self._get_page_text(page_index)

    def _summarize_and_speak(self) -> None:
        if not self.doc or self.is_summarizing or self.is_translating:
            return
        page_index = self.current_page
        pdf_key = self._pdf_key()
        cached = self.summary_cache.get(pdf_key, page_index)
        if cached:
            self._show_summary(cached)
            self._speak_summary()
            return
        self._run_summarize(page_index, auto_speak=True)

    def _run_summarize(self, page_index: int, auto_speak: bool = False) -> None:
        self.is_summarizing = True
        self._set_buttons_state(False)
        self._set_status(f"페이지 {page_index + 1} Gemini 요약 생성 중...")

        def worker() -> None:
            try:
                source = self._get_summary_source_text(page_index)
                summary = self._get_summarizer().summarize(source)
                self.summary_cache.set(self._pdf_key(), page_index, summary)
                self.after(
                    0,
                    lambda: self._on_summary_done(page_index, summary, auto_speak),
                )
            except Exception as exc:
                self.after(0, lambda: self._on_summary_error(str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _show_summary(self, summary: str) -> None:
        self.summary_text.configure(state="normal")
        self.summary_text.delete("1.0", "end")
        self.summary_text.insert("1.0", summary)
        self.summary_text.configure(state="disabled")

    def _on_summary_done(
        self, page_index: int, summary: str, auto_speak: bool
    ) -> None:
        self.is_summarizing = False
        self._set_buttons_state(True)
        if page_index == self.current_page:
            self._show_summary(summary)
        self._set_status(f"페이지 {page_index + 1} 3줄 요약 완료")
        if auto_speak:
            self._speak_summary()

    def _on_summary_error(self, error: str) -> None:
        self.is_summarizing = False
        self._set_buttons_state(True)
        self._set_status("요약 오류가 발생했습니다.")
        messagebox.showerror("요약 오류", f"Gemini 요약 중 오류가 발생했습니다.\n\n{error}")

    def _speak_summary(self) -> None:
        self.summary_text.configure(state="normal")
        text = self.summary_text.get("1.0", "end").strip()
        self.summary_text.configure(state="disabled")
        if not text or "요약 + 음성 재생" in text:
            messagebox.showwarning("알림", "먼저 요약을 생성하세요.")
            return
        self._set_status("TTS 음성 재생 중...")
        self.tts.speak(text, on_done=lambda: self.after(0, self._on_speech_done))

    def _on_speech_done(self) -> None:
        self._set_status("음성 재생 완료")

    def _stop_speech(self) -> None:
        self.tts.stop()
        self._set_status("음성 재생 정지")

    def _prev_page(self) -> None:
        if self.current_page > 0:
            self._show_page(self.current_page - 1)

    def _next_page(self) -> None:
        if self.current_page < self.page_count - 1:
            self._show_page(self.current_page + 1)

    def _on_slider(self, value: float) -> None:
        if self.is_translating:
            return
        page_index = int(round(value)) - 1
        if page_index != self.current_page:
            self._show_page(page_index)

    def _translate_current_page(self) -> None:
        if not self.doc or self.is_translating:
            return
        self._run_translation([self.current_page])

    def _translate_all_pages(self) -> None:
        if not self.doc or self.is_translating:
            return
        if not messagebox.askyesno(
            "전체 번역",
            f"총 {self.page_count}페이지를 번역합니다.\n"
            "인터넷 연결이 필요하며 시간이 걸릴 수 있습니다.\n계속하시겠습니까?",
        ):
            return
        self._run_translation(list(range(self.page_count)))

    def _run_translation(self, pages: list[int]) -> None:
        self.is_translating = True
        self._set_buttons_state(False)
        self.progress.set(0)
        self._set_status("번역 중...")

        def worker() -> None:
            total = len(pages)
            pdf_key = self._pdf_key()
            try:
                for i, page_index in enumerate(pages):
                    if self.cache.get(pdf_key, page_index):
                        progress = (i + 1) / total
                        self.after(0, lambda p=progress, n=page_index: self._update_progress(p, n, cached=True))
                        continue

                    text = self._get_page_text(page_index)
                    if not text:
                        translation = "(이 페이지에서 추출된 텍스트가 없습니다.)"
                    else:
                        translation = translate_text(text, self.translator)

                    self.cache.set(pdf_key, page_index, translation)
                    progress = (i + 1) / total
                    self.after(
                        0,
                        lambda p=progress, n=page_index, t=translation: self._on_page_translated(p, n, t),
                    )

                self.after(0, self._on_translation_done)
            except Exception as exc:
                self.after(0, lambda: self._on_translation_error(str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _update_progress(self, progress: float, page_index: int, cached: bool = False) -> None:
        self.progress.set(progress)
        suffix = " (캐시)" if cached else ""
        self._set_status(f"페이지 {page_index + 1} 처리 중...{suffix}")

    def _on_page_translated(self, progress: float, page_index: int, translation: str) -> None:
        self.progress.set(progress)
        self._set_status(f"페이지 {page_index + 1} 번역 완료")
        if page_index == self.current_page:
            self.translated_text.configure(state="normal")
            self.translated_text.delete("1.0", "end")
            self.translated_text.insert("1.0", translation)
            self.translated_text.configure(state="disabled")

    def _on_translation_done(self) -> None:
        self.is_translating = False
        self._set_buttons_state(True)
        self.progress.set(1)
        self._show_cached_translation(self.current_page)
        self._set_status("번역이 완료되었습니다.")
        messagebox.showinfo("완료", "번역이 완료되었습니다.")

    def _on_translation_error(self, error: str) -> None:
        self.is_translating = False
        self._set_buttons_state(True)
        self.progress.set(0)
        self._set_status("번역 오류가 발생했습니다.")
        messagebox.showerror("번역 오류", f"번역 중 오류가 발생했습니다.\n\n{error}")

    def _export_translation(self) -> None:
        if not self.doc:
            messagebox.showwarning("알림", "먼저 PDF를 불러오세요.")
            return

        pdf_key = self._pdf_key()
        translated_pages = [
            self.cache.get(pdf_key, i) for i in range(self.page_count)
        ]
        if not any(translated_pages):
            messagebox.showwarning("알림", "저장할 번역이 없습니다. 먼저 번역을 실행하세요.")
            return

        default_name = f"{self.pdf_path.stem}_한글번역.txt"
        save_path = filedialog.asksaveasfilename(
            title="번역 저장",
            defaultextension=".txt",
            initialfile=default_name,
            initialdir=str(APP_DIR),
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not save_path:
            return

        lines = [
            f"원본: {self.pdf_path.name}",
            f"번역: 영문 → 한국어",
            "=" * 60,
            "",
        ]
        for i, translation in enumerate(translated_pages):
            lines.append(f"--- 페이지 {i + 1} ---")
            lines.append("")
            if translation:
                lines.append(translation)
            else:
                lines.append("(번역 없음)")
            lines.append("")
            lines.append("")

        try:
            with open(save_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            self._set_status(f"저장됨: {Path(save_path).name}")
            messagebox.showinfo("저장 완료", f"번역이 저장되었습니다.\n{save_path}")
        except OSError as exc:
            messagebox.showerror("저장 오류", str(exc))

    def on_closing(self) -> None:
        self.tts.stop()
        if self.doc:
            self.doc.close()
        self.destroy()


def main() -> None:
    app = NE532TranslatorApp()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()


if __name__ == "__main__":
    main()
