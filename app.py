"""
Nexus Research Platform — FastAPI Backend
Run: uvicorn app:app --reload --port 8000

[INCLUSIVITY ADDITIONS in this file]
  1. User context (language, role, expertise) is extracted from every
     request and forwarded to all analysis functions so responses are
     personalised and multilingual.

  2. /api/projects/{pid}/feedback          — POST, GET
     /api/projects/{pid}/feedback/{fid}    — DELETE
     /api/projects/{pid}/feedback/stats    — GET
     /api/projects/{pid}/feedback/summary  — POST (AI synthesis of feedback)

  3. /api/projects/{pid}/users/{username}/preferences  — GET, PATCH
     (persist language, role, expertise, accessibility settings)

  4. /api/projects/{pid}/analyze/report    — POST
     Full synthesis report endpoint (was missing from original).

  5. /api/projects/{pid}/deconstruct       — POST
     Concept Deconstructor endpoint (new feature from frontend).
"""

import os, tempfile, json
from fastapi import FastAPI, File, UploadFile, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.requests import Request
from pydantic import BaseModel, Field, validator
from typing import Optional, List
from dotenv import load_dotenv

load_dotenv(override=True)

app = FastAPI(title="Nexus Research Platform", version="3.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

templates = Jinja2Templates(directory="templates")


# ── Pydantic helpers ───────────────────────────────────────────────────────────

class UserContextBody(BaseModel):
    """
    [INCLUSIVITY] Reusable context block included in any request body
    that triggers AI generation. All fields are optional — defaults ensure
    backward compatibility with existing integrations.
    """
    language:           str  = "en"
    role:               str  = "student"       # "student" | "supervisor"
    expertise:          str  = "intermediate"  # "beginner" | "intermediate" | "advanced"
    personal_statement: str  = ""
    username:           str  = "researcher"


def _ctx_from_body(body) -> "UserContext":  # type: ignore[name-defined]
    """Extract a UserContext from any Pydantic model that carries context fields."""
    from analysis import UserContext
    return UserContext(
        language           = getattr(body, "language", "en"),
        role               = getattr(body, "role", "student"),
        expertise          = getattr(body, "expertise", "intermediate"),
        personal_statement = getattr(body, "personal_statement", ""),
        username           = getattr(body, "username", "researcher"),
    )


# ── Serve frontend ─────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ── Health / config check ──────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    google_key = os.getenv("GOOGLE_API_KEY", "")
    return {
        "status":                 "ok",
        "google_api_key_set":     bool(google_key),
        "google_api_key_preview": (google_key[:8] + "…") if google_key else "NOT SET",
        "tavily_key_set":         bool(os.getenv("TAVILY_API_KEY")),
        "version":                "3.0",
    }


# ── Projects ───────────────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name:              str
    problem_statement: str
    created_by:        str = "team"


@app.get("/api/projects")
async def get_projects():
    from projects import list_projects
    return list_projects()


@app.post("/api/projects")
async def create_project_api(data: ProjectCreate):
    from projects import create_project
    return create_project(data.name, data.problem_statement, data.created_by)


@app.get("/api/projects/{pid}")
async def get_project(pid: str):
    from projects import load_project
    proj = load_project(pid)
    if not proj:
        raise HTTPException(404, "Project not found")
    return proj


@app.delete("/api/projects/{pid}")
async def delete_project_api(pid: str):
    from projects import delete_project
    delete_project(pid)
    return {"ok": True}


@app.patch("/api/projects/{pid}")
async def update_project_api(pid: str, data: dict):
    from projects import load_project, update_project
    proj = load_project(pid)
    if not proj:
        raise HTTPException(404)
    if "research_goal" in data:
        proj["research_goal"] = data["research_goal"]
    update_project(proj)
    return proj


# ── [INCLUSIVITY] User Preferences ────────────────────────────────────────────

class PreferencesBody(BaseModel):
    """
    Stores per-user language, role, expertise, and accessibility settings.
    PATCH merges — only the fields you send are updated.
    """
    language:  Optional[str]  = None   # "en" | "ar" | "hi" | "zh" | "fr" | "de" | "es" | "ja"
    role:      Optional[str]  = None   # "student" | "supervisor"
    expertise: Optional[str]  = None   # "beginner" | "intermediate" | "advanced"
    accessibility: Optional[dict] = None  # {dyslexia, high_contrast, reduced_motion, font_size}


@app.get("/api/projects/{pid}/users/{username}/preferences")
async def get_preferences(pid: str, username: str):
    """Return the stored UI + AI preferences for a collaborator."""
    from projects import load_project, get_user_preferences
    proj = load_project(pid)
    if not proj:
        raise HTTPException(404, "Project not found")
    return get_user_preferences(proj, username)


@app.patch("/api/projects/{pid}/users/{username}/preferences")
async def update_preferences(pid: str, username: str, data: PreferencesBody):
    """
    Persist UI and AI preferences for a collaborator.
    These preferences are automatically applied to all subsequent AI calls
    made by this user in this project.
    """
    from projects import load_project, update_user_preferences, add_or_update_collaborator
    proj = load_project(pid)
    if not proj:
        raise HTTPException(404, "Project not found")

    # Build the patch dict from non-None fields only
    patch = {k: v for k, v in data.dict().items() if v is not None}
    updated = update_user_preferences(proj, username, patch)
    return {"preferences": updated, "username": username}


# ── Collaborators ──────────────────────────────────────────────────────────────

class CollabData(BaseModel):
    username:           str
    subdomain:          str  = ""
    personal_statement: str  = ""


@app.post("/api/projects/{pid}/collaborators")
async def add_collab(pid: str, data: CollabData):
    from projects import load_project, add_or_update_collaborator
    proj = load_project(pid)
    if not proj:
        raise HTTPException(404)
    proj = add_or_update_collaborator(proj, data.username, data.subdomain, data.personal_statement)
    return proj["collaborators"]


# ── Papers ─────────────────────────────────────────────────────────────────────

@app.post("/api/projects/{pid}/papers/upload")
async def upload_paper(
    pid:      str,
    file:     UploadFile = File(...),
    username: str        = Query("researcher"),
):
    from projects import (load_project, register_paper,
                          add_paper_to_collaborator, add_or_update_collaborator)
    from ingestion import ingest_pdf

    proj = load_project(pid)
    if not proj:
        raise HTTPException(404, "Project not found")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        result = ingest_pdf(tmp_path, pid, uploaded_by=username)
        if result["status"] in ("success", "skipped"):
            proj = load_project(pid)
            add_or_update_collaborator(proj, username)
            proj = load_project(pid)
            register_paper(proj, result["doc_hash"], result)
            proj = load_project(pid)
            add_paper_to_collaborator(proj, username, result["doc_hash"])
        return result
    finally:
        os.unlink(tmp_path)


@app.get("/api/projects/{pid}/papers")
async def list_papers(pid: str):
    from ingestion import list_ingested_papers
    return list_ingested_papers(pid)


@app.post("/api/projects/{pid}/papers/{doc_hash}/summarize")
def summarize_paper_api(
    pid:      str,
    doc_hash: str,
    # [INCLUSIVITY] Optional context from the requesting user
    username: str = Query("researcher"),
    language: str = Query("en"),
    role:     str = Query("student"),
    expertise:str = Query("intermediate"),
):
    """
    Summarise a paper.
    Pass ?language=ar&role=supervisor&expertise=advanced etc. to get a
    response tailored to that user's language and level.
    """
    from projects import (load_project, update_paper_status, update_project,
                          get_user_preferences)
    from ingestion import get_full_text, extract_subtopics
    from analysis import summarize_paper, check_reliability, UserContext

    proj = load_project(pid)
    if not proj:
        raise HTTPException(404)
    paper = proj["papers"].get(doc_hash)
    if not paper:
        raise HTTPException(404, "Paper not found")

    # [INCLUSIVITY] Merge stored preferences with query params
    stored_prefs = get_user_preferences(proj, username)
    ctx = UserContext(
        language           = language or stored_prefs.get("language", "en"),
        role               = role     or stored_prefs.get("role", "student"),
        expertise          = expertise or stored_prefs.get("expertise", "intermediate"),
        personal_statement = stored_prefs.get("personal_statement", ""),
        username           = username,
    )

    try:
        ft          = get_full_text(doc_hash, pid)
        summary     = summarize_paper(
            paper["title"], ft,
            proj["problem_statement"],
            ctx=ctx,
        )
        reliability = check_reliability(paper["title"], ft[:1200], ctx=ctx)
        subtopics   = extract_subtopics(paper["title"], ft)
        update_paper_status(proj, doc_hash, "summarized", summary=summary, reliability=reliability)

        proj = load_project(pid)
        if proj and doc_hash in proj["papers"]:
            proj["papers"][doc_hash]["subtopics"] = subtopics
            update_project(proj)

        return {"summary": summary, "reliability": reliability, "subtopics": subtopics}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/projects/{pid}/papers/{doc_hash}")
async def delete_paper_api(pid: str, doc_hash: str):
    from projects import load_project, update_project
    from ingestion import delete_paper
    proj = load_project(pid)
    if proj and doc_hash in proj.get("papers", {}):
        del proj["papers"][doc_hash]
        update_project(proj)
    n = delete_paper(doc_hash, pid)
    return {"deleted_chunks": n}


# ── Annotations ────────────────────────────────────────────────────────────────

class AnnotationData(BaseModel):
    username: str
    text:     str


@app.post("/api/projects/{pid}/papers/{doc_hash}/annotations")
async def add_annotation_api(pid: str, doc_hash: str, data: AnnotationData):
    from projects import load_project, add_annotation
    proj = load_project(pid)
    if not proj:
        raise HTTPException(404)
    add_annotation(proj, doc_hash, data.username, data.text)
    return {"ok": True}


@app.delete("/api/projects/{pid}/papers/{doc_hash}/annotations/{ann_id}")
async def del_annotation_api(pid: str, doc_hash: str, ann_id: str):
    from projects import load_project, delete_annotation
    proj = load_project(pid)
    if not proj:
        raise HTTPException(404)
    delete_annotation(proj, doc_hash, ann_id)
    return {"ok": True}


# ── Chat ───────────────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    message:  str
    username: str  = "researcher"
    use_web:  bool = False
    # [INCLUSIVITY] Per-message user context — allows language switching mid-conversation
    language:  str = "en"
    role:      str = "student"
    expertise: str = "intermediate"
    personal_statement: str = ""


@app.post("/api/projects/{pid}/chat")
def chat(pid: str, data: ChatMessage):
    from projects import (load_project, add_chat_message,
                          get_user_preferences)
    from ingestion import query_papers
    from analysis import (answer_with_rag, answer_with_agent,
                          is_web_search_available, UserContext)

    proj = load_project(pid)
    if not proj:
        raise HTTPException(404)

    try:
        add_chat_message(proj, data.username, data.message, msg_type="user")
        proj = load_project(pid)

        # [INCLUSIVITY] Build UserContext from stored prefs + request body
        stored = get_user_preferences(proj, data.username)
        ctx = UserContext(
            language           = data.language  or stored.get("language", "en"),
            role               = data.role      or stored.get("role", "student"),
            expertise          = data.expertise or stored.get("expertise", "intermediate"),
            personal_statement = data.personal_statement or stored.get("personal_statement", ""),
            username           = data.username,
        )

        hits    = query_papers(data.message, pid, n_results=5)
        use_web = data.use_web and is_web_search_available()

        if use_web:
            answer, web_sources = answer_with_agent(
                data.message, hits, proj["problem_statement"], ctx=ctx
            )
            citations = web_sources
        else:
            answer    = answer_with_rag(
                data.message, hits, proj["problem_statement"], ctx=ctx
            )
            citations = [h["title"] or h["file_name"] for h in hits[:3]]

        add_chat_message(proj, "Nexus AI", answer,
                         citations=citations, msg_type="ai")

        return {
            "answer":    answer,
            "citations": citations,
            "sources":   hits[:3],
            "web_used":  use_web,
            "language":  ctx.language,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Analysis ───────────────────────────────────────────────────────────────────

class GapAnalysisRequest(BaseModel):
    # [INCLUSIVITY] User context embedded in analysis requests
    username:  str = "researcher"
    language:  str = "en"
    role:      str = "student"
    expertise: str = "intermediate"
    personal_statement: str = ""


@app.post("/api/projects/{pid}/analyze/gaps")
def analyze_gaps(pid: str, data: GapAnalysisRequest = None):
    from projects import load_project, get_user_preferences
    from analysis import detect_gaps, UserContext

    proj = load_project(pid)
    if not proj:
        raise HTTPException(404)

    ctx = DEFAULT_CTX_FROM_REQUEST(proj, data)

    try:
        papers_db = proj.get("papers", {})
        covered   = list({t for p in papers_db.values() for t in p.get("subtopics", [])})
        summaries = [p["summary"] for p in papers_db.values() if p.get("summary")]
        result    = detect_gaps(proj["problem_statement"], covered, summaries, ctx=ctx)
        return {"analysis": result, "language": ctx.language}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class CompareRequest(BaseModel):
    doc_hashes: List[str]
    # [INCLUSIVITY] User context
    username:  str = "researcher"
    language:  str = "en"
    role:      str = "student"
    expertise: str = "intermediate"
    personal_statement: str = ""


@app.post("/api/projects/{pid}/analyze/compare")
def compare_api(pid: str, data: CompareRequest):
    from projects import load_project, get_user_preferences
    from ingestion import get_full_text
    from analysis import compare_papers, UserContext

    proj = load_project(pid)
    if not proj:
        raise HTTPException(404)
    if len(data.doc_hashes) < 2:
        raise HTTPException(400, "Need at least 2 papers")

    ctx = DEFAULT_CTX_FROM_REQUEST(proj, data)

    try:
        papers = []
        for dh in data.doc_hashes:
            p = proj["papers"].get(dh)
            if p:
                papers.append({"title": p["title"], "full_text": get_full_text(dh, pid)})
        result = compare_papers(papers, proj["problem_statement"], ctx=ctx)
        return {"comparison": result, "language": ctx.language}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# [NEW] Research report generation
class ReportRequest(BaseModel):
    username:  str = "researcher"
    language:  str = "en"
    role:      str = "student"
    expertise: str = "intermediate"
    personal_statement: str = ""


@app.post("/api/projects/{pid}/analyze/report")
def generate_report_api(pid: str, data: ReportRequest):
    """
    Generate a full research synthesis report for the project.
    Response language and depth match the requesting user's preferences.
    """
    from projects import load_project, get_user_preferences
    from analysis import generate_research_report, UserContext

    proj = load_project(pid)
    if not proj:
        raise HTTPException(404)

    papers = list(proj.get("papers", {}).values())
    if not papers:
        raise HTTPException(400, "No papers in project")

    ctx = DEFAULT_CTX_FROM_REQUEST(proj, data)

    try:
        report = generate_research_report(papers, proj["problem_statement"], ctx=ctx)
        return {"report": report, "language": ctx.language}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Diagrams ───────────────────────────────────────────────────────────────────

class DiagramRequest(BaseModel):
    doc_hash:     Optional[str] = None
    diagram_type: str           = "flowchart"
    # [INCLUSIVITY] User context — diagram labels rendered in user's language
    username:  str = "researcher"
    language:  str = "en"
    role:      str = "student"
    expertise: str = "intermediate"
    personal_statement: str = ""


@app.post("/api/projects/{pid}/generate/diagram")
def generate_diagram_api(pid: str, data: DiagramRequest):
    from projects import load_project, get_user_preferences
    from ingestion import get_full_text
    from analysis import generate_mermaid_diagram, UserContext

    proj = load_project(pid)
    if not proj:
        raise HTTPException(404)

    ctx = DEFAULT_CTX_FROM_REQUEST(proj, data)

    try:
        if data.doc_hash and data.doc_hash in proj.get("papers", {}):
            paper = proj["papers"][data.doc_hash]
            text  = get_full_text(data.doc_hash, pid)
            title = paper.get("title", "Paper")
        else:
            summaries = [p.get("summary", "") for p in proj.get("papers", {}).values() if p.get("summary")]
            text  = "\n\n".join(summaries[:3])
            title = proj["name"]

        diagram = generate_mermaid_diagram(title, text[:4000], data.diagram_type, ctx=ctx)
        return {"diagram": diagram, "type": data.diagram_type, "language": ctx.language}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── [NEW] Concept Deconstructor ───────────────────────────────────────────────

class DeconstructRequest(BaseModel):
    concept:  str
    username: str = "researcher"
    language: str = "en"
    role:     str = "student"
    expertise:str = "intermediate"
    personal_statement: str = ""


@app.post("/api/projects/{pid}/deconstruct")
def deconstruct_api(pid: str, data: DeconstructRequest):
    """
    [RUBRIC B-A — Concept Deconstructor]
    Break a dense equation or concept into scaffolded learning modules.
    Output language and depth adapt to the user's context.
    """
    from projects import load_project, get_user_preferences
    from analysis import deconstruct_concept, UserContext

    proj = load_project(pid)
    if not proj:
        raise HTTPException(404)

    ctx = DEFAULT_CTX_FROM_REQUEST(proj, data)

    if not data.concept.strip():
        raise HTTPException(400, "concept cannot be empty")

    try:
        result = deconstruct_concept(data.concept.strip(), ctx=ctx)
        return {"result": result, "language": ctx.language, "expertise": ctx.expertise}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Knowledge Graph ────────────────────────────────────────────────────────────

@app.get("/api/projects/{pid}/knowledge-graph")
async def knowledge_graph(pid: str):
    from projects import load_project

    proj = load_project(pid)
    if not proj:
        raise HTTPException(404)

    nodes, edges, seen_topics = [], [], {}
    papers_db = proj.get("papers", {})

    for paper in papers_db.values():
        pid_node = f"paper_{paper['doc_hash']}"
        label    = (paper.get("title") or paper.get("file_name", ""))[:35]
        nodes.append({
            "id":     pid_node,
            "label":  label,
            "group":  "paper",
            "title":  paper.get("title") or paper.get("file_name", ""),
            "status": paper.get("status", "pending"),
        })
        for topic in paper.get("subtopics", []):
            t   = topic.strip().lower()
            if not t:
                continue
            tid = f"topic_{t.replace(' ', '_').replace('/', '_')}"
            if tid not in seen_topics:
                seen_topics[tid] = True
                nodes.append({"id": tid, "label": t, "group": "topic"})
            edges.append({"from": pid_node, "to": tid})

    return {"nodes": nodes, "edges": edges}


# ── Stats ──────────────────────────────────────────────────────────────────────

@app.get("/api/projects/{pid}/stats")
async def get_stats(pid: str):
    from projects import load_project, get_feedback_stats

    proj = load_project(pid)
    if not proj:
        raise HTTPException(404)

    papers    = proj.get("papers", {})
    summaries = sum(1 for p in papers.values() if p.get("status") == "summarized")
    all_topics = list({t for p in papers.values() for t in p.get("subtopics", [])})
    chat_count = len(proj.get("chat", []))

    # [NEW] Include feedback stats in project stats
    feedback_stats = get_feedback_stats(proj)

    return {
        "total_papers":    len(papers),
        "summarized":      summaries,
        "topics":          len(all_topics),
        "chat_messages":   chat_count,
        "collaborators":   len(proj.get("collaborators", {})),
        "coverage_topics": all_topics[:20],
        "feedback":        feedback_stats,
    }


# ── [NEW] Feedback endpoints ───────────────────────────────────────────────────

class FeedbackCreate(BaseModel):
    """
    [INCLUSIVITY — FEEDBACK LOOP]
    Users rate any piece of AI-generated content. This data is used to
    improve response quality and flag underperforming content types.
    """
    username:     str  = "researcher"
    content_type: str  = Field(..., description=(
        "One of: summary | reliability | gap_analysis | chat | "
        "comparison | diagram | report | deconstructor"
    ))
    content_ref:  str  = ""       # doc_hash or message id
    rating:       int  = Field(..., ge=1, le=5, description="1–5 star rating")
    helpful:      bool = True     # quick thumbs up/down
    comment:      str  = ""       # optional free text
    language:     str  = "en"     # language the user was viewing in

    @validator("rating")
    def validate_rating(cls, v):
        if not 1 <= v <= 5:
            raise ValueError("Rating must be between 1 and 5")
        return v


@app.post("/api/projects/{pid}/feedback", status_code=201)
async def create_feedback(pid: str, data: FeedbackCreate):
    """Submit feedback for any AI-generated content in a project."""
    from projects import load_project, add_feedback

    proj = load_project(pid)
    if not proj:
        raise HTTPException(404, "Project not found")

    entry = add_feedback(
        proj         = proj,
        username     = data.username,
        content_type = data.content_type,
        rating       = data.rating,
        helpful      = data.helpful,
        comment      = data.comment,
        content_ref  = data.content_ref,
        language     = data.language,
    )
    return {"feedback": entry, "ok": True}


@app.get("/api/projects/{pid}/feedback")
async def get_feedback(
    pid:          str,
    content_type: Optional[str] = Query(None),
    content_ref:  Optional[str] = Query(None),
    username:     Optional[str] = Query(None),
    limit:        int           = Query(100, le=500),
):
    """
    List feedback entries with optional filters.
    Supervisors can use this to review all team feedback.
    """
    from projects import load_project, list_feedback

    proj = load_project(pid)
    if not proj:
        raise HTTPException(404, "Project not found")

    entries = list_feedback(proj, content_type=content_type,
                            content_ref=content_ref, username=username, limit=limit)
    return {"feedback": entries, "count": len(entries)}


@app.delete("/api/projects/{pid}/feedback/{feedback_id}")
async def remove_feedback(
    pid:         str,
    feedback_id: str,
    username:    str = Query(..., description="Must match the feedback author"),
):
    """Users may delete their own feedback entries."""
    from projects import load_project, delete_feedback

    proj = load_project(pid)
    if not proj:
        raise HTTPException(404, "Project not found")

    deleted = delete_feedback(proj, feedback_id, username)
    if not deleted:
        raise HTTPException(404, "Feedback not found or not owned by this user")
    return {"ok": True}


@app.get("/api/projects/{pid}/feedback/stats")
async def feedback_stats_api(pid: str):
    """
    Aggregate feedback statistics per content type.
    Designed for the supervisor dashboard.
    """
    from projects import load_project, get_feedback_stats

    proj = load_project(pid)
    if not proj:
        raise HTTPException(404, "Project not found")

    return get_feedback_stats(proj)


class FeedbackSummaryRequest(BaseModel):
    content_type: Optional[str] = None
    username:     str = "researcher"
    language:     str = "en"
    role:         str = "supervisor"
    expertise:    str = "intermediate"


@app.post("/api/projects/{pid}/feedback/summary")
def feedback_summary_api(pid: str, data: FeedbackSummaryRequest):
    """
    [AI-POWERED] Synthesise user feedback into actionable insights.
    Produced in the requesting user's language.
    Intended for supervisors reviewing platform quality.
    """
    from projects import load_project, list_feedback, get_user_preferences
    from analysis import summarise_feedback_batch, UserContext

    proj = load_project(pid)
    if not proj:
        raise HTTPException(404, "Project not found")

    entries = list_feedback(proj, content_type=data.content_type, limit=100)
    if not entries:
        return {"summary": "No feedback data available yet.", "count": 0}

    ctx = UserContext(
        language  = data.language,
        role      = data.role,
        expertise = data.expertise,
        username  = data.username,
    )

    try:
        summary = summarise_feedback_batch(
            entries,
            data.content_type or "all content types",
            ctx=ctx,
        )
        return {
            "summary":      summary,
            "count":        len(entries),
            "content_type": data.content_type,
            "language":     ctx.language,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Internal helper ───────────────────────────────────────────────────────────

def DEFAULT_CTX_FROM_REQUEST(proj: dict, data) -> "UserContext":  # type: ignore
    """
    Build a UserContext by merging:
      1. The user's stored preferences (language, role, expertise)
      2. Any explicit values sent in the request body (override stored)
    This ensures language / role changes take effect immediately without
    requiring a separate preferences PATCH call.
    """
    from projects import get_user_preferences
    from analysis import UserContext

    username = getattr(data, "username", "researcher") or "researcher"
    stored   = get_user_preferences(proj, username)

    return UserContext(
        language           = getattr(data, "language",  None) or stored.get("language",  "en"),
        role               = getattr(data, "role",      None) or stored.get("role",      "student"),
        expertise          = getattr(data, "expertise", None) or stored.get("expertise", "intermediate"),
        personal_statement = (
            getattr(data, "personal_statement", "")
            or stored.get("personal_statement", "")
        ),
        username           = username,
    )


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
