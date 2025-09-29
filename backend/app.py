from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from flask import Flask, jsonify, request, send_file, send_from_directory
from jinja2 import Template
from markdown import Markdown
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
)
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
import xml.etree.ElementTree as ET

from .config_manager import load_config, update_config
from .llm_client import LLMConfig, TutorLLMClient, list_available_models
from . import storage


logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

app = Flask(
    __name__,
    static_folder=str(FRONTEND_DIR),
    static_url_path="/static"
)

_AVAILABLE_MODELS: List[dict] = []
PDF_FONT_NAME = "ExportSans"
PDF_FONT_VARIANTS = (
    ("ExportSans", "LiberationSans-Regular.ttf"),
    ("ExportSans-Bold", "LiberationSans-Bold.ttf"),
    ("ExportSans-Italic", "LiberationSans-Italic.ttf"),
    ("ExportSans-BoldItalic", "LiberationSans-BoldItalic.ttf"),
)
PDF_FONT_SEARCH_DIRS = (
    Path("/usr/share/fonts/liberation-fonts"),
    Path("/usr/share/fonts/truetype/liberation"),
    Path("/usr/share/fonts"),
)
MD_EXTENSIONS = [
    "fenced_code",
    "sane_lists",
    "tables",
]


def _ensure_pdf_font() -> str:
    registered = set(pdfmetrics.getRegisteredFontNames())
    if PDF_FONT_NAME in registered:
        return PDF_FONT_NAME

    for font_name, filename in PDF_FONT_VARIANTS:
        if font_name in registered:
            continue
        for directory in PDF_FONT_SEARCH_DIRS:
            candidate = directory / filename
            if candidate.exists():
                try:
                    pdfmetrics.registerFont(TTFont(font_name, str(candidate)))
                    registered.add(font_name)
                    break
                except Exception as exc:  # pragma: no cover
                    LOGGER.warning("Failed to register font %s: %s", candidate, exc)

    if PDF_FONT_NAME in pdfmetrics.getRegisteredFontNames():
        return PDF_FONT_NAME

    LOGGER.warning("No Liberation font found; falling back to Helvetica (may lack Cyrillic support)")
    return "Helvetica"


def _escape_xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _build_pdf_styles(font_name: str) -> dict[str, ParagraphStyle]:
    base_styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "Body",
        parent=base_styles["BodyText"],
        fontName=font_name,
        fontSize=11,
        leading=14,
        spaceAfter=6,
    )
    heading1 = ParagraphStyle(
        "Heading1",
        parent=base_styles["Heading1"],
        fontName=font_name,
        fontSize=18,
        leading=22,
        spaceAfter=12,
    )
    heading2 = ParagraphStyle(
        "Heading2",
        parent=base_styles["Heading2"],
        fontName=font_name,
        fontSize=14,
        leading=18,
        spaceAfter=8,
    )
    heading3 = ParagraphStyle(
        "Heading3",
        parent=base_styles["Heading3"],
        fontName=font_name,
        fontSize=12,
        leading=16,
        spaceAfter=6,
    )
    meta = ParagraphStyle(
        "Meta",
        parent=body,
        textColor=colors.grey,
        spaceAfter=4,
    )
    list_body = ParagraphStyle(
        "ListBody",
        parent=body,
        leftIndent=0,
        firstLineIndent=0,
        spaceAfter=2,
    )
    blockquote = ParagraphStyle(
        "BlockQuote",
        parent=body,
        leftIndent=12,
        textColor=colors.darkgray,
        spaceBefore=4,
        spaceAfter=6,
    )
    code = ParagraphStyle(
        "Code",
        parent=body,
        fontName="Courier",
        fontSize=10,
        leading=12,
        backColor=colors.whitesmoke,
        leftIndent=6,
        rightIndent=6,
        spaceBefore=4,
        spaceAfter=8,
    )
    return {
        "Body": body,
        "Heading1": heading1,
        "Heading2": heading2,
        "Heading3": heading3,
        "Meta": meta,
        "ListBody": list_body,
        "BlockQuote": blockquote,
        "Code": code,
    }


def _inline_markup(node: ET.Element) -> str:
    parts: List[str] = []
    if node.text:
        parts.append(_escape_xml(node.text))
    for child in node:
        parts.append(_wrap_inline(child))
        if child.tail:
            parts.append(_escape_xml(child.tail))
    return "".join(parts)


def _wrap_inline(node: ET.Element) -> str:
    tag = node.tag.lower()
    if tag in {"strong", "b"}:
        return f"<b>{_inline_markup(node)}</b>"
    if tag in {"em", "i"}:
        return f"<i>{_inline_markup(node)}</i>"
    if tag == "code":
        code_text = "".join(node.itertext())
        return f"<font name='Courier'>{_escape_xml(code_text)}</font>"
    if tag == "br":
        return "<br/>"
    if tag == "a":
        inner = _inline_markup(node)
        href = node.attrib.get("href")
        if href:
            return f"{inner} ({_escape_xml(href)})"
        return inner
    if tag == "sub":
        return f"<sub>{_inline_markup(node)}</sub>"
    if tag == "sup":
        return f"<sup>{_inline_markup(node)}</sup>"
    return _inline_markup(node)


def _list_items_from_elements(elements: Iterable[ET.Element], styles: dict) -> List[ListItem]:
    items: List[ListItem] = []
    for li in elements:
        text = _inline_markup(li).strip()
        if not text:
            continue
        items.append(ListItem(Paragraph(text, styles["ListBody"])))
    return items


def _element_to_flowables(element: ET.Element, styles: dict, font_name: str) -> List:
    tag = element.tag.lower()
    flowables: List = []

    if tag in {"p", "span", "div"}:
        raw_text = "".join(element.itertext()).strip()
        markup = _inline_markup(element).strip()
        if not markup:
            return [Spacer(1, 6)]
        if raw_text.startswith("$$") and raw_text.endswith("$$") and raw_text.count("$$") >= 2:
            flowables.append(Preformatted(raw_text, styles["Code"]))
        else:
            flowables.append(Paragraph(markup, styles["Body"]))
        return flowables

    if tag in {"h1", "h2", "h3"}:
        heading_style = {
            "h1": styles["Heading1"],
            "h2": styles["Heading2"],
            "h3": styles.get("Heading3", styles["Heading2"]),
        }[tag]
        flowables.append(Paragraph(_inline_markup(element), heading_style))
        return flowables

    if tag in {"ul", "ol"}:
        items = _list_items_from_elements(element.findall("li"), styles)
        if not items:
            return []
        bullet_type = "bullet" if tag == "ul" else "1"
        start = element.attrib.get("start") or "1"
        try:
            start_value: Optional[int] = int(start) if tag == "ol" else None
        except ValueError:
            start_value = 1
        flowables.append(
            ListFlowable(
                items,
                bulletType=bullet_type,
                bulletFontName=font_name,
                bulletFontSize=11,
                bulletChar="•" if tag == "ul" else None,
                leftIndent=12,
                start=start_value,
            )
        )
        flowables.append(Spacer(1, 6))
        return flowables

    if tag == "pre":
        code_text = "\n".join(line.rstrip() for line in element.itertext()).strip("\n")
        flowables.append(Preformatted(code_text or " ", styles["Code"]))
        return flowables

    if tag == "code":
        code_text = "".join(element.itertext())
        flowables.append(Preformatted(code_text, styles["Code"]))
        return flowables

    if tag == "blockquote":
        markup = _inline_markup(element).strip()
        if markup:
            flowables.append(Paragraph(markup, styles["BlockQuote"]))
            flowables.append(Spacer(1, 4))
        return flowables

    if tag == "table":
        rows: List[str] = []
        for tr in element.findall("tr"):
            cells = [" ".join(td.itertext()).strip() for td in tr]
            rows.append(" | ".join(cell for cell in cells if cell))
        for row in rows:
            if row:
                flowables.append(Paragraph(_escape_xml(row), styles["Body"]))
        if rows:
            flowables.append(Spacer(1, 6))
        return flowables

    # Fallback: treat unknown element as paragraph
    markup = _inline_markup(element).strip()
    if markup:
        flowables.append(Paragraph(markup, styles["Body"]))
    else:
        flowables.append(Spacer(1, 4))
    return flowables


def _markdown_to_flowables(feedback: str, styles: dict, font_name: str) -> List:
    md = Markdown(extensions=MD_EXTENSIONS, output_format="xhtml1")
    html = md.convert(feedback or "")
    md.reset()

    if not html.strip():
        return []

    try:
        root = ET.fromstring(f"<root>{html}</root>")
    except ET.ParseError:
        return [Paragraph(_escape_xml(feedback), styles["Body"])]

    flowables: List = []
    for child in root:
        flowables.extend(_element_to_flowables(child, styles, font_name))
    return flowables


def _refresh_models() -> None:
    global _AVAILABLE_MODELS
    _AVAILABLE_MODELS = list_available_models()


_refresh_models()


def _build_llm_client() -> TutorLLMClient:
    config = load_config()
    model_cfg = config.get("model", {})
    llm_config = LLMConfig(
        model=model_cfg.get("name", "gemini-pro"),
    )
    return TutorLLMClient(llm_config)


def _format_dialogue_turns(messages: List[dict]) -> str:
    formatted = []
    for msg in messages:
        label = "Ученик" if msg.get("role") == "user" else "Учитель"
        formatted.append(f"{label}: {msg.get('content', '')}")
    return "\n\n".join(formatted)


def _resolve_image_path(path_str: Optional[str]) -> Optional[Path]:
    if not path_str:
        return None
    path = Path(path_str)
    if not path.is_absolute():
        path = BASE_DIR / path_str
    return path


def _conversation_images(conversation: dict) -> List[Path]:
    images: List[Path] = []
    for key in ("task_image", "solution_image"):
        resolved = _resolve_image_path(conversation.get(key))
        if resolved:
            images.append(resolved)
    return images


def _estimation_images(task_image: Optional[str], student_image: Optional[str]) -> List[Path]:
    images: List[Path] = []
    for img in (task_image, student_image):
        resolved = _resolve_image_path(img)
        if resolved:
            images.append(resolved)
    return images


def _extract_score(text: str) -> Optional[str]:
    match = re.search(r"score\s*[:\-]?\s*([\w.]+)", text, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1)


@app.get("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.get("/api/config")
def get_config():
    return jsonify(load_config())


@app.get("/api/models")
def get_models():
    if not _AVAILABLE_MODELS:
        _refresh_models()
    return jsonify({"models": _AVAILABLE_MODELS})


@app.get("/api/conversations")
def list_conversations():
    return jsonify({"conversations": storage.list_conversations_metadata()})


@app.get("/api/conversations/<conversation_id>/export")
def export_conversation(conversation_id: str):
    try:
        conversation = storage.load_conversation(conversation_id)
    except storage.ConversationNotFound:
        return jsonify({"error": "Conversation not found"}), 404

    return jsonify({
        "conversation": conversation,
    })


@app.get("/api/export/all")
def export_all_conversations():
    buffer = storage.export_log_to_workbook()
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"conversation_export_{timestamp}.xlsx"
    return send_file(
        buffer,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _create_estimation_pdf(score: Optional[str], feedback: str) -> BytesIO:
    font_name = _ensure_pdf_font()
    styles = _build_pdf_styles(font_name)
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=25 * mm,
        bottomMargin=25 * mm,
    )

    story: List = []
    story.append(Paragraph("Результат оценки", styles["Heading1"]))
    story.append(Spacer(1, 10))

    timestamp = datetime.utcnow().strftime("%d.%m.%Y %H:%M:%S")
    story.append(Paragraph(f"Дата: {timestamp}", styles["Meta"]))
    if score:
        story.append(Paragraph(f"Оценка: <b>{_escape_xml(score)}</b>", styles["Meta"]))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Обратная связь:", styles["Heading2"]))
    story.append(Spacer(1, 6))

    flowables = _markdown_to_flowables(feedback or "", styles, font_name)
    if flowables:
        story.extend(flowables)
    else:
        story.append(Paragraph("Нет обратной связи.", styles["Body"]))

    doc.build(story)
    buffer.seek(0)
    return buffer


@app.post("/api/estimation/export")
def export_estimation_result():
    payload = request.get_json(force=True) or {}
    feedback = (payload.get("feedback") or "").strip()
    if not feedback:
        return jsonify({"error": "Feedback is empty"}), 400

    score = payload.get("score")
    score_text = str(score).strip() if score is not None else ""
    buffer = _create_estimation_pdf(score_text, feedback)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"estimation_{timestamp}.pdf"
    return send_file(
        buffer,
        as_attachment=True,
        download_name=filename,
        mimetype="application/pdf",
    )


@app.put("/api/config")
def put_config():
    data = request.get_json(force=True)
    config = load_config()
    updated = update_config(data)
    LOGGER.info("Configuration updated")
    return jsonify(updated)


@app.post("/api/dialogs")
def create_dialog():
    config = load_config()
    prompt_template = config.get("prompt_template", "")

    task_text = request.form.get("task") or ""

    conversation_id = uuid.uuid4().hex
    conversation_upload_dir = storage.UPLOADS_DIR / conversation_id

    task_image_path: Path | None = None
    task_image_original: str | None = None
    solution_image_path: Path | None = None
    solution_image_original: str | None = None

    if "task_image" in request.files:
        task_image_path, task_image_original = _save_uploaded_file(
            request.files["task_image"], conversation_upload_dir, "task"
        )
    if "solution_image" in request.files:
        solution_image_path, solution_image_original = _save_uploaded_file(
            request.files["solution_image"], conversation_upload_dir, "solution"
        )

    conversation = storage.create_conversation(
        prompt_template=prompt_template,
        task_text=task_text,
        task_image=str(task_image_path) if task_image_path else None,
        task_image_original=task_image_original,
        solution_image=str(solution_image_path) if solution_image_path else None,
        solution_image_original=solution_image_original,
        conversation_id=conversation_id,
    )

    return jsonify({"conversation_id": conversation["id"], "conversation": conversation})


@app.get("/api/dialogs/<conversation_id>")
def get_dialog(conversation_id: str):
    try:
        conversation = storage.load_conversation(conversation_id)
    except storage.ConversationNotFound:
        return jsonify({"error": "Conversation not found"}), 404
    return jsonify(conversation)


@app.get("/api/dialogs/<conversation_id>/messages")
def get_messages(conversation_id: str):
    try:
        messages = storage.list_messages(conversation_id)
    except storage.ConversationNotFound:
        return jsonify({"error": "Conversation not found"}), 404
    return jsonify({"messages": messages})


@app.post("/api/dialogs/<conversation_id>/messages")
def post_message(conversation_id: str):
    payload = request.get_json(force=True)
    content = (payload or {}).get("message", "").strip()
    role = (payload or {}).get("role", "user")

    if not content:
        return jsonify({"error": "Message cannot be empty"}), 400

    try:
        storage.append_message(conversation_id, role, content)
        conversation = storage.load_conversation(conversation_id)
    except storage.ConversationNotFound:
        return jsonify({"error": "Conversation not found"}), 404

    messages = conversation.get("messages", [])
    dialogue_turns = _format_dialogue_turns(messages)

    template = Template(conversation.get("prompt_template", ""))
    rendered_prompt = template.render(
        task=conversation.get("task"),
        task_image=conversation.get("task_image"),
        solution_image=conversation.get("solution_image"),
        dialogue_turns=dialogue_turns,
    )

    llm_client = _build_llm_client()
    assistant_reply = llm_client.generate_reply(
        rendered_prompt,
        images=_conversation_images(conversation)
    )

    assistant_turn = storage.append_message(conversation_id, "assistant", assistant_reply)

    return jsonify({
        "user_message": {"role": role, "content": content},
        "assistant_message": assistant_turn,
    })

@app.post("/api/estimation")
def estimate_student_work():
    config = load_config()
    estimation_template = config.get("estimation_template")
    if not estimation_template:
        return jsonify({"error": "Estimation template is not configured."}), 400

    estimation_id = uuid.uuid4().hex
    estimation_upload_dir = storage.ESTIMATION_UPLOADS_DIR / estimation_id

    task_text = request.form.get("task") or ""
    student_work = request.form.get("student_work") or ""

    task_image_path: Path | None = None
    task_image_original: str | None = None
    student_image_path: Path | None = None
    student_image_original: str | None = None

    if "task_image" in request.files:
        task_image_path, task_image_original = _save_uploaded_file(
            request.files["task_image"], estimation_upload_dir, "task"
        )
    if "student_work_image" in request.files:
        student_image_path, student_image_original = _save_uploaded_file(
            request.files["student_work_image"], estimation_upload_dir, "student"
        )

    template = Template(estimation_template)
    context = {
        "task": task_text,
        "task_image": str(task_image_path) if task_image_path else None,
        "student_work": student_work,
        "student_work_image": str(student_image_path) if student_image_path else None,
    }
    rendered_prompt = template.render(**context)

    llm_client = _build_llm_client()
    assistant_reply = llm_client.generate_reply(
        rendered_prompt,
        images=_estimation_images(context["task_image"], context["student_work_image"])
    )

    score = _extract_score(assistant_reply)
    timestamp = datetime.utcnow().isoformat() + "Z"

    storage.log_estimation(
        estimation_id,
        {
            "timestamp": timestamp,
            "prompt_template": estimation_template,
            "prompt": rendered_prompt,
            "task": task_text,
            "task_image": context["task_image"],
            "task_image_original_name": task_image_original,
            "student_work": student_work,
            "student_work_image": context["student_work_image"],
            "student_work_image_original_name": student_image_original,
            "response": assistant_reply,
            "score": score,
        }
    )

    return jsonify({
        "estimation_id": estimation_id,
        "score": score,
        "feedback": assistant_reply,
    })



def _save_uploaded_file(file_storage, upload_dir: Path, prefix: str) -> Tuple[Path | None, str | None]:
    if not file_storage or not file_storage.filename:
        return None, None

    upload_dir.mkdir(parents=True, exist_ok=True)
    original_name = Path(file_storage.filename).name
    suffix = Path(original_name).suffix or ".png"
    target_path = upload_dir / f"{prefix}{suffix}"
    file_storage.save(target_path)
    return target_path.relative_to(BASE_DIR), original_name


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
