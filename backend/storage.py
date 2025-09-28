import json
import uuid
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Dict, List


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CONVERSATIONS_DIR = DATA_DIR / "conversations"
UPLOADS_DIR = DATA_DIR / "uploads"
LOG_PATH = DATA_DIR / "conversations.log"

CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH.touch(exist_ok=True)

_log_lock = Lock()
_store_lock = Lock()


class ConversationNotFound(Exception):
    pass


def _conversation_path(conversation_id: str) -> Path:
    return CONVERSATIONS_DIR / f"{conversation_id}.json"


def create_conversation(prompt_template: str, task_text: str | None = None,
                        task_image: str | None = None, solution_image: str | None = None,
                        conversation_id: str | None = None) -> Dict:
    conversation_id = conversation_id or uuid.uuid4().hex
    conversation = {
        "id": conversation_id,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "prompt_template": prompt_template,
        "task": task_text or "",
        "task_image": task_image,
        "solution_image": solution_image,
        "messages": []
    }

    save_conversation(conversation)
    _append_log_entry({
        "event": "conversation_created",
        "conversation_id": conversation_id,
        "timestamp": conversation["created_at"],
        "prompt_template": prompt_template,
        "task": task_text,
        "task_image": task_image,
        "solution_image": solution_image
    })

    return conversation


def save_conversation(conversation: Dict) -> None:
    path = _conversation_path(conversation["id"])
    with _store_lock:
        with path.open("w", encoding="utf-8") as fp:
            json.dump(conversation, fp, ensure_ascii=False, indent=2)


def load_conversation(conversation_id: str) -> Dict:
    path = _conversation_path(conversation_id)
    if not path.exists():
        raise ConversationNotFound(conversation_id)

    with path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def append_message(conversation_id: str, role: str, content: str) -> Dict:
    conversation = load_conversation(conversation_id)
    turn = {
        "role": role,
        "content": content,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }
    conversation.setdefault("messages", []).append(turn)
    save_conversation(conversation)
    _append_log_entry({
        "event": "message_appended",
        "conversation_id": conversation_id,
        "role": role,
        "content": content,
        "timestamp": turn["timestamp"]
    })
    return turn


def list_messages(conversation_id: str) -> List[Dict]:
    return load_conversation(conversation_id).get("messages", [])


def _append_log_entry(entry: Dict) -> None:
    with _log_lock:
        with LOG_PATH.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(entry, ensure_ascii=False) + "\n")
