from google.cloud import firestore
from datetime import datetime, timezone
from typing import Optional, Dict, Any

PROJECT_ID = "project-1f6eb2e4-ff89-4067-874"  # 改成你的 project id（如果不同）

db = firestore.Client(project=PROJECT_ID)

def _now():
    return datetime.now(timezone.utc)

def create_contact(contact: Dict[str, Any]) -> str:
    """Create a contact doc and return its document ID."""
    payload = {
        "name": contact.get("name"),
        "email": contact.get("email"),
        "phone": contact.get("phone"),
        "need": contact.get("need"),
        "budget": contact.get("budget"),
        "timeline": contact.get("timeline"),
        "createdAt": _now(),
    }
    doc_ref = db.collection("contacts").document()
    doc_ref.set(payload)
    return doc_ref.id

def create_task(task_payload: Dict[str, Any], contact_id: Optional[str] = None) -> str:
    """Create a task doc and return its document ID. contact_id is optional."""
    payload = {
        "type": task_payload.get("task_type"),
        "description": task_payload.get("description"),
        "due": task_payload.get("due"),
        "status": task_payload.get("status", "open"),
        "createdAt": _now(),
    }
    if contact_id:
        payload["contactId"] = contact_id

    doc_ref = db.collection("tasks").document()
    doc_ref.set(payload)
    return doc_ref.id

def create_call_note(call_note: Dict[str, Any], contact_id: Optional[str] = None) -> str:
    """Create a call_note doc and return its document ID. contact_id is optional."""
    payload = {
        "summary": call_note.get("summary"),
        "rawTranscript": call_note.get("rawTranscript"),
        "createdAt": _now(),
    }
    if contact_id:
        payload["contactId"] = contact_id

    doc_ref = db.collection("call_notes").document()
    doc_ref.set(payload)
    return doc_ref.id
