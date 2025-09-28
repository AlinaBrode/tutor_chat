from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import List

from flask import Flask, jsonify, request, send_from_directory
from jinja2 import Template

from .config_manager import load_config, update_config
from .llm_client import LLMConfig, TutorLLMClient
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


def _conversation_images(conversation: dict) -> List[Path]:
    images: List[Path] = []
    for key in ("task_image", "solution_image"):
        value = conversation.get(key)
        if value:
            path = Path(value)
            if not path.is_absolute():
                path = BASE_DIR / value
            images.append(path)
    return images


@app.get("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.get("/api/config")
def get_config():
    return jsonify(load_config())


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

    task_image_path = None
    solution_image_path = None

    if "task_image" in request.files:
        task_image_path = _save_uploaded_file(request.files["task_image"], conversation_upload_dir, "task")
    if "solution_image" in request.files:
        solution_image_path = _save_uploaded_file(request.files["solution_image"], conversation_upload_dir, "solution")

    conversation = storage.create_conversation(
        prompt_template=prompt_template,
        task_text=task_text,
        task_image=str(task_image_path) if task_image_path else None,
        solution_image=str(solution_image_path) if solution_image_path else None,
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

def _save_uploaded_file(file_storage, upload_dir: Path, prefix: str) -> Path | None:
    if not file_storage or not file_storage.filename:
        return None

    upload_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(file_storage.filename).suffix or ".png"
    target_path = upload_dir / f"{prefix}{suffix}"
    file_storage.save(target_path)
    return target_path.relative_to(BASE_DIR)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
