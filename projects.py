"""
projects.py — Project, collaborator, chat, annotation, feedback, and
              user-preference management.

Storage: Supabase (free tier — 500MB Postgres)

[INCLUSIVITY ADDITIONS]
  • User preferences (language, role, expertise, accessibility) stored
    per collaborator inside the project JSONB.
  • Feedback system: users can rate any AI-generated content (summary,
    reliability, gap analysis, chat message, comparison, diagram).
    Feedback is stored in the project JSONB under `project["feedbacks"]`.

Supabase SQL (run once in SQL Editor):
──────────────────────────────────────
  create table if not exists projects (
    id text primary key,
    data jsonb not null,
    created_at timestamptz default now()
  );

  alter table projects enable row level security;
  create policy "Allow all" on projects for all using (true) with check (true);
──────────────────────────────────────
No extra tables needed — all new fields live in the existing JSONB `data` column.
"""

import os, json, uuid
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ── Supabase client ────────────────────────────────────────────────────────────
_supabase = None

def get_db():
    global _supabase
    if _supabase is not None:
        return _supabase
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set.")
    from supabase import create_client
    _supabase = create_client(url, key)
    return _supabase


# ── Internal helpers ───────────────────────────────────────────────────────────

def _save(proj: dict) -> None:
    """Persist the full project object to Supabase."""
    get_db().table("projects").upsert(
        {"id": proj["id"], "data": proj},
        on_conflict="id"
    ).execute()


def _now() -> str:
    return datetime.now().isoformat()


def _now_display() -> str:
    return datetime.now().strftime("%H:%M")


# ── Project CRUD ───────────────────────────────────────────────────────────────

def load_project(pid: str) -> dict | None:
    res = get_db().table("projects").select("data").eq("id", pid).execute()
    if not res.data:
        return None
    return res.data[0]["data"]


def list_projects() -> list[dict]:
    res = get_db().table("projects").select("data").order("created_at", desc=True).execute()
    return [row["data"] for row in res.data]


def create_project(name: str, problem_statement: str, created_by: str) -> dict:
    proj = {
        "id":                str(uuid.uuid4())[:8],
        "name":              name,
        "problem_statement": problem_statement,
        "created_by":        created_by,
        "created_at":        _now(),
        "collaborators":     {},
        "papers":            {},
        "chat":              [],
        "feedbacks":         [],    # [NEW] feedback entries
        "research_goal":     "",
    }
    _save(proj)
    return proj


def update_project(proj: dict) -> None:
    _save(proj)


def delete_project(pid: str) -> None:
    get_db().table("projects").delete().eq("id", pid).execute()


# ── Collaborators ──────────────────────────────────────────────────────────────

def _pick_color(idx: int) -> str:
    colors = ["#2d9cdb","#27ae60","#e74c3c","#f39c12","#9b59b6",
              "#1abc9c","#e67e22","#e91e63"]
    return colors[idx % len(colors)]


def add_or_update_collaborator(
    proj: dict,
    username: str,
    subdomain: str = "",
    personal_statement: str = "",
) -> dict:
    if username not in proj["collaborators"]:
        proj["collaborators"][username] = {
            "username":           username,
            "subdomain":          subdomain,
            "personal_statement": personal_statement,
            "papers":             [],
            "joined_at":          _now(),
            "color":              _pick_color(len(proj["collaborators"])),
            # [INCLUSIVITY] Per-user preferences stored alongside collaborator data
            "preferences": {
                "language":   "en",
                "role":       "student",
                "expertise":  "intermediate",
                "accessibility": {
                    "dyslexia":       False,
                    "high_contrast":  False,
                    "reduced_motion": False,
                    "font_size":      13,
                }
            },
        }
    else:
        if subdomain:
            proj["collaborators"][username]["subdomain"] = subdomain
        if personal_statement:
            proj["collaborators"][username]["personal_statement"] = personal_statement
        # Ensure preferences block exists on legacy records
        if "preferences" not in proj["collaborators"][username]:
            proj["collaborators"][username]["preferences"] = {
                "language":  "en",
                "role":      "student",
                "expertise": "intermediate",
                "accessibility": {
                    "dyslexia": False, "high_contrast": False,
                    "reduced_motion": False, "font_size": 13,
                }
            }

    _save(proj)
    return proj


def add_paper_to_collaborator(proj: dict, username: str, doc_hash: str) -> dict:
    if username not in proj["collaborators"]:
        add_or_update_collaborator(proj, username)
    if doc_hash not in proj["collaborators"][username].get("papers", []):
        proj["collaborators"][username].setdefault("papers", []).append(doc_hash)
    _save(proj)
    return proj


# ── [INCLUSIVITY] User Preferences ────────────────────────────────────────────

def get_user_preferences(proj: dict, username: str) -> dict:
    """
    Return the stored preferences for a collaborator.
    Returns defaults if the user hasn't been registered yet.
    """
    collab = proj.get("collaborators", {}).get(username)
    if not collab:
        return {
            "language":  "en",
            "role":      "student",
            "expertise": "intermediate",
            "accessibility": {
                "dyslexia": False, "high_contrast": False,
                "reduced_motion": False, "font_size": 13,
            }
        }
    return collab.get("preferences", {
        "language":  "en",
        "role":      "student",
        "expertise": "intermediate",
        "accessibility": {},
    })


def update_user_preferences(proj: dict, username: str, prefs: dict) -> dict:
    """
    Merge new preference values into the existing preferences for a collaborator.
    Creates the collaborator record if needed.
    """
    add_or_update_collaborator(proj, username)   # ensure record exists
    existing = proj["collaborators"][username].get("preferences", {})
    # Deep-merge accessibility sub-dict
    if "accessibility" in prefs and isinstance(prefs["accessibility"], dict):
        existing.setdefault("accessibility", {}).update(prefs["accessibility"])
        prefs = {k: v for k, v in prefs.items() if k != "accessibility"}
    existing.update(prefs)
    proj["collaborators"][username]["preferences"] = existing
    _save(proj)
    return existing


# ── Papers ─────────────────────────────────────────────────────────────────────

def register_paper(proj: dict, doc_hash: str, meta: dict) -> dict:
    if doc_hash not in proj["papers"]:
        proj["papers"][doc_hash] = {
            "doc_hash":    doc_hash,
            "title":       meta.get("title", ""),
            "file_name":   meta.get("file_name", ""),
            "author":      meta.get("author", ""),
            "num_pages":   meta.get("num_pages", 0),
            "subtopics":   meta.get("subtopics", []),
            "status":      "pending",
            "summary":     "",
            "reliability": "",
            "annotations": [],
            "uploaded_by": meta.get("uploaded_by", ""),
            "uploaded_at": _now(),
        }
    else:
        proj["papers"][doc_hash].update(
            {k: v for k, v in meta.items()
             if k in ("subtopics", "status", "summary", "reliability")}
        )
    _save(proj)
    return proj


def update_paper_status(
    proj: dict,
    doc_hash: str,
    status: str,
    summary: str = "",
    reliability: str = "",
) -> dict:
    if doc_hash in proj["papers"]:
        proj["papers"][doc_hash]["status"] = status
        if summary:     proj["papers"][doc_hash]["summary"]     = summary
        if reliability: proj["papers"][doc_hash]["reliability"] = reliability
    _save(proj)
    return proj


# ── Annotations ────────────────────────────────────────────────────────────────

def add_annotation(proj: dict, doc_hash: str, username: str, text: str) -> dict:
    if doc_hash in proj["papers"]:
        proj["papers"][doc_hash].setdefault("annotations", []).append({
            "id":        str(uuid.uuid4())[:6],
            "user":      username,
            "text":      text,
            "timestamp": _now_display(),
        })
    _save(proj)
    return proj


def delete_annotation(proj: dict, doc_hash: str, ann_id: str) -> dict:
    if doc_hash in proj["papers"]:
        proj["papers"][doc_hash]["annotations"] = [
            a for a in proj["papers"][doc_hash].get("annotations", [])
            if a["id"] != ann_id
        ]
    _save(proj)
    return proj


# ── Chat ───────────────────────────────────────────────────────────────────────

def add_chat_message(
    proj: dict,
    user: str,
    content: str,
    citations: list | None = None,
    msg_type: str = "user",
) -> dict:
    proj.setdefault("chat", []).append({
        "id":        str(uuid.uuid4())[:6],
        "user":      user,
        "content":   content,
        "timestamp": _now_display(),
        "citations": citations or [],
        "type":      msg_type,
    })
    _save(proj)
    return proj


# ── [NEW] Feedback system ──────────────────────────────────────────────────────

# Valid content types that users can provide feedback on
FEEDBACK_CONTENT_TYPES = frozenset({
    "summary",       # paper AI summary
    "reliability",   # paper reliability assessment
    "gap_analysis",  # project gap analysis
    "chat",          # individual chat message
    "comparison",    # paper comparison
    "diagram",       # generated diagram
    "report",        # research synthesis report
    "deconstructor", # concept deconstructor output
})

def add_feedback(
    proj: dict,
    username: str,
    content_type: str,
    rating: int,
    helpful: bool,
    comment: str = "",
    content_ref: str = "",     # doc_hash or message_id
    language: str = "en",
) -> dict:
    """
    Store a feedback entry for any piece of AI-generated content.

    Parameters
    ----------
    content_type : one of FEEDBACK_CONTENT_TYPES
    rating       : 1–5 stars
    helpful      : quick thumbs up / down
    comment      : optional free-text
    content_ref  : doc_hash or message id (links the feedback to a specific item)
    language     : the language the user was using when they gave feedback
    """
    if content_type not in FEEDBACK_CONTENT_TYPES:
        content_type = "other"

    rating = max(1, min(5, int(rating)))   # clamp to 1–5

    entry = {
        "id":           str(uuid.uuid4())[:8],
        "project_id":   proj["id"],
        "username":     username,
        "content_type": content_type,
        "content_ref":  content_ref,
        "rating":       rating,
        "helpful":      bool(helpful),
        "comment":      (comment or "").strip()[:1000],   # cap at 1000 chars
        "language":     language,
        "created_at":   _now(),
    }

    proj.setdefault("feedbacks", []).append(entry)
    _save(proj)
    return entry


def list_feedback(
    proj: dict,
    content_type: str | None = None,
    content_ref: str | None = None,
    username: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """
    Retrieve feedback entries with optional filters.
    Results are sorted newest-first.
    """
    feedbacks = proj.get("feedbacks", [])

    if content_type:
        feedbacks = [f for f in feedbacks if f.get("content_type") == content_type]
    if content_ref:
        feedbacks = [f for f in feedbacks if f.get("content_ref") == content_ref]
    if username:
        feedbacks = [f for f in feedbacks if f.get("username") == username]

    # Newest first
    feedbacks = sorted(feedbacks, key=lambda f: f.get("created_at", ""), reverse=True)
    return feedbacks[:limit]


def delete_feedback(proj: dict, feedback_id: str, username: str) -> bool:
    """
    Delete a feedback entry. Users may only delete their own entries.
    Returns True if an entry was deleted.
    """
    original_len = len(proj.get("feedbacks", []))
    proj["feedbacks"] = [
        f for f in proj.get("feedbacks", [])
        if not (f["id"] == feedback_id and f["username"] == username)
    ]
    changed = len(proj["feedbacks"]) < original_len
    if changed:
        _save(proj)
    return changed


def get_feedback_stats(proj: dict) -> dict:
    """
    Aggregate feedback statistics per content type.
    Used by the supervisor dashboard.
    """
    feedbacks = proj.get("feedbacks", [])
    if not feedbacks:
        return {"total": 0, "by_type": {}, "overall_avg": None}

    by_type: dict = {}
    for f in feedbacks:
        ct = f.get("content_type", "other")
        if ct not in by_type:
            by_type[ct] = {"count": 0, "ratings": [], "helpful_count": 0, "comments": []}
        entry = by_type[ct]
        entry["count"] += 1
        if f.get("rating"):
            entry["ratings"].append(f["rating"])
        if f.get("helpful"):
            entry["helpful_count"] += 1
        if f.get("comment"):
            entry["comments"].append(f["comment"])

    # Compute averages
    result = {}
    all_ratings = []
    for ct, data in by_type.items():
        avg = round(sum(data["ratings"]) / len(data["ratings"]), 2) if data["ratings"] else None
        all_ratings.extend(data["ratings"])
        result[ct] = {
            "count":          data["count"],
            "avg_rating":     avg,
            "helpful_rate":   round(data["helpful_count"] / data["count"], 2),
            "has_comments":   len(data["comments"]),
            "recent_comments": data["comments"][-5:],   # last 5 comments
        }

    overall = round(sum(all_ratings) / len(all_ratings), 2) if all_ratings else None

    return {
        "total":       len(feedbacks),
        "by_type":     result,
        "overall_avg": overall,
    }


# ── Helpers ────────────────────────────────────────────────────────────────────

def get_chroma_collection_name(pid: str) -> str:
    """Kept for backward-compatibility — used in ingestion.py namespace logic."""
    return f"project_{pid}"
