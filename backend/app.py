from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import List, Optional, Tuple

from flask import Flask, jsonify, request, send_file, send_from_directory
from jinja2 import Template
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
PANDOC_BINARY = os.getenv("PANDOC_PATH", "pandoc")
PANDOC_TEX_ENGINE = os.getenv("PANDOC_TEX_ENGINE", "xelatex")


def _render_markdown_to_pdf(markdown_text: str) -> BytesIO:
    with tempfile.TemporaryDirectory() as tmpdir:
        md_path = Path(tmpdir) / "feedback.md"
        pdf_path = md_path.with_suffix(".pdf")
        md_path.write_text(markdown_text, encoding="utf-8")

        command = [
            PANDOC_BINARY,
            str(md_path),
            "-o",
            str(pdf_path),
            "--from",
            "markdown+tex_math_dollars+tex_math_single_backslash",
            "--pdf-engine",
            PANDOC_TEX_ENGINE,
        ]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0 or not pdf_path.exists():
            LOGGER.error("Pandoc export failed: %s", result.stderr.strip())
            raise RuntimeError("Failed to export PDF via pandoc")

        return BytesIO(pdf_path.read_bytes())


def _build_estimation_markdown(score: Optional[str], feedback: str) -> str:
    timestamp = datetime.utcnow().strftime("%d.%m.%Y %H:%M:%S")
    lines = [
        "# Результат оценки",
        f"*Дата:* {timestamp}",
    ]
    if score:
        lines.append(f"*Оценка:* **{score}**")

    lines.extend([
        "",
        "## Обратная связь",
        feedback.strip() or "_Нет обратной связи._",
    ])

    return "\n".join(lines)


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
    markdown_body = _build_estimation_markdown(score, feedback)
    return _render_markdown_to_pdf(markdown_body)


@app.post("/api/estimation/export")
def export_estimation_result():
    payload = request.get_json(force=True) or {}
    feedback = (payload.get("feedback") or "").strip()
    if not feedback:
        return jsonify({"error": "Feedback is empty"}), 400

    score = payload.get("score")
    score_text = str(score).strip() if score is not None else ""
    try:
        buffer = _create_estimation_pdf(score_text or None, feedback)
    except RuntimeError as err:
        return jsonify({"error": str(err)}), 500
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
