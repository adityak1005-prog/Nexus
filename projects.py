"""
projects.py — Project, collaborator, chat, annotation management
Storage: ./projects_data/{project_id}.json
"""

import os, json, uuid
from datetime import datetime

PROJECTS_DIR = "./projects_data"
os.makedirs(PROJECTS_DIR, exist_ok=True)


def _path(pid): return os.path.join(PROJECTS_DIR, f"{pid}.json")

def _save(proj):
    with open(_path(proj["id"]), "w") as f:
        json.dump(proj, f, indent=2)

def load_project(pid):
    p = _path(pid)
    if not os.path.exists(p): return None
    with open(p) as f: return json.load(f)

def list_projects():
    out = []
    for fn in os.listdir(PROJECTS_DIR):
        if fn.endswith(".json"):
            with open(os.path.join(PROJECTS_DIR, fn)) as f:
                out.append(json.load(f))
    return sorted(out, key=lambda x: x["created_at"], reverse=True)

def create_project(name, problem_statement, created_by):
    proj = {
        "id": str(uuid.uuid4())[:8],
        "name": name,
        "problem_statement": problem_statement,
        "created_by": created_by,
        "created_at": datetime.now().isoformat(),
        "collaborators": {},
        "papers": {},        # doc_hash → {title, file_name, author, pages, subtopics, status, summary, annotations[]}
        "chat": [],          # [{id, user, content, timestamp, citations[]}]
        "research_goal": "",
    }
    _save(proj)
    return proj

def update_project(proj): _save(proj)
def delete_project(pid):
    p = _path(pid)
    if os.path.exists(p): os.remove(p)


# ── Collaborators ──────────────────────────────────────────────────────────────
def add_or_update_collaborator(proj, username, subdomain="", personal_statement=""):
    if username not in proj["collaborators"]:
        proj["collaborators"][username] = {
            "username": username, "subdomain": subdomain,
            "personal_statement": personal_statement,
            "papers": [], "joined_at": datetime.now().isoformat(),
            "color": _pick_color(len(proj["collaborators"]))
        }
    else:
        if subdomain: proj["collaborators"][username]["subdomain"] = subdomain
        if personal_statement: proj["collaborators"][username]["personal_statement"] = personal_statement
    _save(proj); return proj

def _pick_color(idx):
    colors = ["#2d9cdb","#27ae60","#e74c3c","#f39c12","#9b59b6","#1abc9c","#e67e22","#e91e63"]
    return colors[idx % len(colors)]

def add_paper_to_collaborator(proj, username, doc_hash):
    if username not in proj["collaborators"]:
        add_or_update_collaborator(proj, username)
    if doc_hash not in proj["collaborators"][username].get("papers", []):
        proj["collaborators"][username].setdefault("papers", []).append(doc_hash)
    _save(proj); return proj

def register_paper(proj, doc_hash, meta: dict):
    """Add/update paper metadata at project level."""
    if doc_hash not in proj["papers"]:
        proj["papers"][doc_hash] = {
            "doc_hash": doc_hash,
            "title": meta.get("title",""),
            "file_name": meta.get("file_name",""),
            "author": meta.get("author",""),
            "num_pages": meta.get("num_pages", 0),
            "subtopics": meta.get("subtopics", []),
            "status": "pending",     # pending → processing → summarized
            "summary": "",
            "reliability": "",
            "annotations": [],
            "uploaded_by": meta.get("uploaded_by",""),
            "uploaded_at": datetime.now().isoformat(),
        }
    else:
        proj["papers"][doc_hash].update({k: v for k, v in meta.items() if k in ("subtopics","status","summary","reliability")})
    _save(proj); return proj

def update_paper_status(proj, doc_hash, status, summary="", reliability=""):
    if doc_hash in proj["papers"]:
        proj["papers"][doc_hash]["status"] = status
        if summary:     proj["papers"][doc_hash]["summary"] = summary
        if reliability: proj["papers"][doc_hash]["reliability"] = reliability
    _save(proj); return proj

def add_annotation(proj, doc_hash, username, text):
    if doc_hash in proj["papers"]:
        proj["papers"][doc_hash].setdefault("annotations", []).append({
            "id": str(uuid.uuid4())[:6],
            "user": username, "text": text,
            "timestamp": datetime.now().strftime("%H:%M"),
        })
    _save(proj); return proj

def delete_annotation(proj, doc_hash, ann_id):
    if doc_hash in proj["papers"]:
        proj["papers"][doc_hash]["annotations"] = [
            a for a in proj["papers"][doc_hash].get("annotations", []) if a["id"] != ann_id
        ]
    _save(proj); return proj


# ── Chat ───────────────────────────────────────────────────────────────────────
def add_chat_message(proj, user, content, citations=None, msg_type="user"):
    msg = {
        "id": str(uuid.uuid4())[:6],
        "user": user, "content": content,
        "timestamp": datetime.now().strftime("%H:%M"),
        "citations": citations or [],
        "type": msg_type,   # "user" | "ai"
    }
    proj.setdefault("chat", []).append(msg)
    _save(proj); return proj

def get_chroma_collection_name(pid): return f"project_{pid}"
