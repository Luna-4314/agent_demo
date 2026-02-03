from dotenv import load_dotenv
load_dotenv()

import json
from typing import Any, Dict, List, Tuple, Optional

from anthropic import Anthropic

from firestore_tools import create_contact, create_task, create_call_note

from mic_record import record_wav
from stt_gcp import transcribe_wav


# =========================
# Strong-contract SYSTEM PROMPT (facts at top-level, intent in actions)
# =========================
SYSTEM_PROMPT = """
You are an AI assistant for a real-estate sales team.

You will be given a sales call transcript (already transcribed to text).
Your responsibilities are to:
1) Extract structured CRM facts (contact + call_note) from the transcript.
2) Propose the next 1–3 operational actions for a real-estate agent.
3) Output STRICT JSON that software can execute.

CRITICAL OUTPUT CONTRACT (MUST FOLLOW):
- Output MUST be a single valid JSON object and NOTHING ELSE.
- Do NOT include markdown, code fences, comments, or explanations.
- The output MUST conform exactly to the JSON schema below.
- FACTS MUST LIVE ONLY IN TOP-LEVEL FIELDS:
  - Put all contact facts ONLY in top-level "contact".
  - Put all call note facts ONLY in top-level "call_note".
- INTENT MUST LIVE ONLY IN "actions":
  - actions is a list of actions describing what software should do.
- STRICT PAYLOAD RULES:
  - For create_contact and create_call_note actions, payload MUST ALWAYS be {} (empty object).
  - NEVER put contact or call_note objects (or any of their fields) inside any action payload.
  - For create_task, payload MUST include exactly: task_type, description, due.
- If you violate these rules, the software will fail. Follow them exactly.

CRM context:
- The CRM stores customer profiles (contacts), follow-up tasks (tasks), and call records (call_notes).
- Raw transcripts and AI-generated summaries are stored in call_notes only.
- Tasks and call_notes MAY exist without being linked to a contact (e.g., internal agent tasks, missing contact info).

FACT EXTRACTION RULES:
- Use null for missing information. Do NOT guess or invent.
- Do not omit information explicitly present in the transcript (email, phone, budget, timeline).
- Budget MUST be a number only (no "$", no commas, no abbreviations like M). If unclear, use null.
- contact.need must be a short intent phrase, e.g., "Buy a 3-bedroom house in Irvine".
- contact.timeline should be concise natural language, e.g., "within the next 2 months", "next week".

CALL NOTE RULES:
- call_note.rawTranscript MUST contain the full transcript text exactly as provided (verbatim).
- call_note.summary must be 1–3 concise sentences capturing intent/location/budget/timeline/next step.
- If no meaningful call note can be produced, set call_note.summary and call_note.rawTranscript to null and omit create_call_note.

ACTIONS RULES:
- Return between 1 and 3 actions.
- Allowed action types: create_contact, create_task, create_call_note.
- Allowed task types: follow_up, schedule_tour, send_listings.
- You MAY create tasks and/or call_notes even when contact info is insufficient.
- If transcript contains enough contact info (typically a name plus at least one of email/phone), you SHOULD include create_contact.
- If contact info is insufficient, you MAY omit create_contact and leave contact fields as null.
- If a tour is mentioned, prefer task_type="schedule_tour".
- If sending options/listings is implied, use task_type="send_listings".
- If key info is missing but needed (email/phone/budget/timeline), create a follow_up task to collect it.
- Recommended (not required) action ordering: create_contact, create_task (optional), create_call_note.

JSON SCHEMA (MUST MATCH EXACTLY):

{
  "contact": {
    "name": string or null,
    "email": string or null,
    "phone": string or null,
    "need": string or null,
    "budget": number or null,
    "timeline": string or null
  },
  "call_note": {
    "summary": string or null,
    "rawTranscript": string or null
  },
  "actions": [
    { "type": "create_contact", "payload": {} },
    { "type": "create_task", "payload": { "task_type": string, "description": string, "due": string or null } },
    { "type": "create_call_note", "payload": {} }
  ]
}

Now produce the JSON object.
"""

# =========================
# Repair prompt (third safety layer)
# =========================
REPAIR_SYSTEM_PROMPT = """
You are a strict JSON repair assistant.

You will be given:
1) The original transcript.
2) The invalid JSON output produced earlier (may violate rules).
3) A list of validation errors.

Your task:
- Produce a corrected JSON output that follows the contract EXACTLY.
- Output MUST be a single valid JSON object and nothing else.
- Do NOT include markdown or code fences.
- Do NOT add new keys outside the schema.
- Enforce: create_contact.payload == {} and create_call_note.payload == {}.
- Keep all facts in top-level 'contact' and 'call_note'.
"""

client = Anthropic()

ALLOWED_ACTION_TYPES = {"create_contact", "create_task", "create_call_note"}
ALLOWED_TASK_TYPES = {"follow_up", "schedule_tour", "send_listings"}


# =========================
# IO helpers
# =========================
def read_multiline_input() -> str:
    print("\nPaste call transcript (press Enter twice to finish):\n")
    lines: List[str] = []
    empty_count = 0
    while True:
        line = input()
        if line.strip() == "":
            empty_count += 1
            if empty_count >= 2:
                break
            continue
        empty_count = 0
        lines.append(line)
    return "\n".join(lines)


# =========================
# Robust JSON parsing (second safety layer)
# =========================
def parse_json_robust(text: str) -> Tuple[Dict[str, Any], str]:
    """
    Parse JSON from LLM output:
    - strips code fences if present
    - extracts substring from first '{' to last '}'
    Returns (parsed_json, extracted_json_text).
    """
    raw = text.strip()

    if raw.startswith("```"):
        lines = raw.splitlines()
        if len(lines) >= 2 and lines[0].startswith("```"):
            lines = lines[1:]
        if len(lines) >= 1 and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()

    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        raw = raw[start:end + 1].strip()

    parsed = json.loads(raw)
    return parsed, raw


# =========================
# Validation (third safety layer part 1)
# =========================
def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def validate_output(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    errors: List[str] = []

    if not isinstance(data, dict):
        return False, ["Output is not a JSON object."]

    # Top-level keys
    for key in ["contact", "call_note", "actions"]:
        if key not in data:
            errors.append(f"Missing top-level key: '{key}'")

    contact = data.get("contact")
    call_note = data.get("call_note")
    actions = data.get("actions")

    # contact schema
    if not isinstance(contact, dict):
        errors.append("Top-level 'contact' must be an object.")
    else:
        required_contact_keys = ["name", "email", "phone", "need", "budget", "timeline"]
        for k in required_contact_keys:
            if k not in contact:
                errors.append(f"contact missing key: '{k}'")

        b = contact.get("budget")
        if b is not None and not _is_number(b):
            errors.append("contact.budget must be a number or null (no $, commas, or abbreviations like '1.2M').")

    # call_note schema
    if not isinstance(call_note, dict):
        errors.append("Top-level 'call_note' must be an object.")
    else:
        required_note_keys = ["summary", "rawTranscript"]
        for k in required_note_keys:
            if k not in call_note:
                errors.append(f"call_note missing key: '{k}'")

        s = call_note.get("summary")
        rt = call_note.get("rawTranscript")
        if s is not None and not isinstance(s, str):
            errors.append("call_note.summary must be string or null.")
        if rt is not None and not isinstance(rt, str):
            errors.append("call_note.rawTranscript must be string or null.")

    # actions schema
    if not isinstance(actions, list) or len(actions) == 0:
        errors.append("'actions' must be a non-empty array.")
    else:
        if len(actions) > 3:
            errors.append("actions must contain 1 to 3 items.")

        for i, act in enumerate(actions):
            if not isinstance(act, dict):
                errors.append(f"actions[{i}] must be an object.")
                continue

            t = act.get("type")
            payload = act.get("payload")

            if t not in ALLOWED_ACTION_TYPES:
                errors.append(f"actions[{i}].type must be one of {sorted(ALLOWED_ACTION_TYPES)}")

            if payload is None or not isinstance(payload, dict):
                errors.append(f"actions[{i}].payload must be an object ({{}} allowed).")
                continue

            if t == "create_contact":
                if payload != {}:
                    errors.append("create_contact.payload MUST be {} (facts must live in top-level contact).")

            elif t == "create_call_note":
                if payload != {}:
                    errors.append("create_call_note.payload MUST be {} (facts must live in top-level call_note).")

            elif t == "create_task":
                allowed_keys = {"task_type", "description", "due"}
                keys = set(payload.keys())
                if keys != allowed_keys:
                    errors.append(
                        f"create_task.payload must have exactly keys {sorted(list(allowed_keys))}, got {sorted(list(keys))}"
                    )
                else:
                    if payload["task_type"] not in ALLOWED_TASK_TYPES:
                        errors.append(f"create_task.payload.task_type must be one of {sorted(ALLOWED_TASK_TYPES)}")
                    if not isinstance(payload["description"], str) or not payload["description"].strip():
                        errors.append("create_task.payload.description must be a non-empty string.")
                    if payload["due"] is not None and not isinstance(payload["due"], str):
                        errors.append("create_task.payload.due must be string or null.")

    return (len(errors) == 0), errors


# =========================
# Repair (third safety layer part 2)
# =========================
def repair_with_claude(transcript: str, bad_json_text: str, errors: List[str]) -> Tuple[Dict[str, Any], str]:
    prompt = {
        "transcript": transcript,
        "invalid_output": bad_json_text,
        "validation_errors": errors,
        "required_schema": {
            "contact": {"name": None, "email": None, "phone": None, "need": None, "budget": None, "timeline": None},
            "call_note": {"summary": None, "rawTranscript": None},
            "actions": [
                {"type": "create_contact", "payload": {}},
                {"type": "create_task", "payload": {"task_type": "follow_up", "description": "", "due": None}},
                {"type": "create_call_note", "payload": {}},
            ],
        },
    }

    resp = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=900,
        # temperature=0,  # 如果你 SDK 支持，建议打开；不支持就删掉这一行
        system=REPAIR_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": json.dumps(prompt)}],
    )

    parsed, extracted = parse_json_robust(resp.content[0].text)
    return parsed, extracted


# =========================
# Claude call with tri-layer safety
# =========================
def call_claude_once(transcript: str) -> Tuple[Dict[str, Any], str]:
    resp = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=900,
        # temperature=0,  # 如果你 SDK 支持，建议打开；不支持就删掉这一行
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": transcript}],
    )
    parsed, extracted = parse_json_robust(resp.content[0].text)
    return parsed, extracted

def call_claude_with_retry(transcript: str, max_attempts: int = 3) -> Dict[str, Any]:
    # Attempt 1
    data, extracted = call_claude_once(transcript)
    ok, errs = validate_output(data)
    if ok:
        return data

    last_json_text = extracted
    last_errors = errs

    # Attempts 2..N repair loop
    for attempt in range(2, max_attempts + 1):
        print(f"⚠️ Validation failed (attempt {attempt-1}). Repairing...")
        repaired, repaired_text = repair_with_claude(transcript, last_json_text, last_errors)

        ok, errs = validate_output(repaired)
        if ok:
            print("✅ Repaired output validated.")
            return repaired

        last_json_text = repaired_text
        last_errors = errs

    raise ValueError("Model output failed validation after retries:\n" + "\n".join(last_errors))


# =========================
# Executor (方案1): optional contact association, but facts stay top-level
# =========================
def _is_contact_meaningful(contact: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(contact, dict):
        return False
    name = contact.get("name")
    email = contact.get("email")
    phone = contact.get("phone")
    return bool(name) and (bool(email) or bool(phone))

def execute_actions(data: Dict[str, Any], transcript: str):
    """
    Execute actions:
    - Create contact if action exists and info is meaningful.
    - Create tasks and call_notes regardless of whether a contact was created.
    - Link tasks/notes to contact if contact_id exists; otherwise write unlinked.
    """
    actions = data.get("actions", [])
    top_contact = data.get("contact", {})
    top_note = data.get("call_note", {})

    if not isinstance(actions, list) or len(actions) == 0:
        raise ValueError("Missing or invalid 'actions' list.")

    # Phase 1: create contact if requested AND meaningful
    contact_id: Optional[str] = None
    for action in actions:
        if not isinstance(action, dict):
            continue
        if action.get("type") != "create_contact":
            continue

        if _is_contact_meaningful(top_contact):
            contact_id = create_contact(top_contact)
            print("✅ Created contact:", contact_id)
        else:
            print("ℹ️ Skipped contact creation (insufficient contact info).")
        break  # only one contact creation

    # Phase 2: tasks + call_note
    task_ids: List[str] = []
    call_note_id: Optional[str] = None

    for action in actions:
        if not isinstance(action, dict):
            continue

        t = action.get("type")
        payload = action.get("payload") or {}

        if t == "create_contact":
            continue  # already handled

        if t == "create_task":
            task_id = create_task(payload, contact_id=contact_id)
            task_ids.append(task_id)
            print("✅ Created task (linked)" if contact_id else "✅ Created task (unlinked)", ":", task_id)

        elif t == "create_call_note":
            # If call_note is null/null and action exists, still allow storing transcript fallback if desired
            note_obj = dict(top_note) if isinstance(top_note, dict) else {}
            # Ensure transcript present when action requests note creation
            if note_obj.get("rawTranscript") is None:
                note_obj["rawTranscript"] = transcript
            call_note_id = create_call_note(note_obj, contact_id=contact_id)
            print("✅ Created call_note (linked)" if contact_id else "✅ Created call_note (unlinked)", ":", call_note_id)

        else:
            print("⚠️ Unknown action type:", t)

    return contact_id, task_ids, call_note_id


# =========================
# Main
# =========================
if __name__ == "__main__":
    print("\n=== CRM Agent CLI (text / mic) ===")

    while True:
        mode = input("\nChoose input mode: [1] text  [2] mic  [q] quit : ").strip().lower()
        if mode in ("q", "quit"):
            print("Bye 👋")
            break

        if mode == "1":
            transcript = read_multiline_input().strip()
            if not transcript:
                print("⚠️ Empty transcript.")
                continue

        elif mode == "2":
            secs_str = input("Record how many seconds? (e.g., 10): ").strip()
            seconds = int(secs_str) if secs_str.isdigit() else 10

            wav_path = record_wav(out_path="recording.wav", seconds=seconds, sample_rate=16000, channels=1)
            transcript = transcribe_wav(wav_path, language_code="en-US", sample_rate_hz=16000)

            print("\n--- STT TRANSCRIPT ---")
            print(transcript)

            if not transcript:
                print("⚠️ STT returned empty transcript.")
                continue

        else:
            print("Invalid choice.")
            continue

        # 走你原来的三重兜底 + Firestore 写入
        data = call_claude_with_retry(transcript, max_attempts=3)

        print("\n--- FINAL JSON (validated) ---")
        print(json.dumps(data, indent=2))

        print("\n--- EXECUTION ---")
        execute_actions(data, transcript)
