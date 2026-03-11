"""
Nexus Research Platform — FastAPI Backend
Run: uvicorn app:app --reload --port 8000
"""
import os, tempfile, json
from fastapi import FastAPI, File, UploadFile, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.requests import Request
from pydantic import BaseModel
from typing import Optional, List
from dotenv import load_dotenv

load_dotenv(override=True)  # override=True ensures .env changes are always picked up

app = FastAPI(title="Nexus Research Platform", version="2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

templates = Jinja2Templates(directory="templates")

# ── Serve frontend ─────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# ── Health / config check ──────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    google_key = os.getenv("GOOGLE_API_KEY", "")
    return {
        "status": "ok",
        "google_api_key_set": bool(google_key),
        "google_api_key_preview": (google_key[:8] + "…") if google_key else "NOT SET",
        "tavily_key_set": bool(os.getenv("TAVILY_API_KEY")),
    }


# ── Projects ───────────────────────────────────────────────────────────────────
class ProjectCreate(BaseModel):
    name: str
    problem_statement: str
    created_by: str = "team"

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


# ── Collaborators ──────────────────────────────────────────────────────────────
class CollabData(BaseModel):
    username: str
    subdomain: str = ""
    personal_statement: str = ""

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
async def upload_paper(pid: str, file: UploadFile = File(...), username: str = Query("researcher")):
    from projects import load_project, register_paper, add_paper_to_collaborator, add_or_update_collaborator
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
def summarize_paper_api(pid: str, doc_hash: str):
    from projects import load_project, update_paper_status, update_project
    from ingestion import get_full_text, extract_subtopics
    from analysis import summarize_paper, check_reliability

    proj = load_project(pid)
    if not proj:
        raise HTTPException(404)
    paper = proj["papers"].get(doc_hash)
    if not paper:
        raise HTTPException(404, "Paper not found")

    try:
        ft          = get_full_text(doc_hash, pid)
        summary     = summarize_paper(paper["title"], ft, proj["problem_statement"])
        reliability = check_reliability(paper["title"], ft[:1200])
        subtopics   = extract_subtopics(paper["title"], ft)
        update_paper_status(proj, doc_hash, "summarized", summary=summary, reliability=reliability)

        # Save subtopics back to the project
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
    text: str

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
    message: str
    username: str = "researcher"
    use_web: bool = False

@app.post("/api/projects/{pid}/chat")
def chat(pid: str, data: ChatMessage):
    from projects import load_project, add_chat_message
    from ingestion import query_papers
    from analysis import answer_with_rag, answer_with_agent, is_web_search_available

    proj = load_project(pid)
    if not proj:
        raise HTTPException(404)

    try:
        add_chat_message(proj, data.username, data.message, msg_type="user")
        proj = load_project(pid)

        hits = query_papers(data.message, pid, n_results=5)
        use_web = data.use_web and is_web_search_available()

        if use_web:
            answer, web_sources = answer_with_agent(data.message, hits, proj["problem_statement"])
            citations = web_sources
        else:
            answer = answer_with_rag(data.message, hits, proj["problem_statement"])
            citations = [h["title"] or h["file_name"] for h in hits[:3]]

        add_chat_message(proj, "Nexus AI", answer, citations=citations, msg_type="ai")
        return {"answer": answer, "citations": citations, "sources": hits[:3], "web_used": use_web}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Analysis ───────────────────────────────────────────────────────────────────
@app.post("/api/projects/{pid}/analyze/gaps")
def analyze_gaps(pid: str):
    from projects import load_project
    from analysis import detect_gaps

    proj = load_project(pid)
    if not proj:
        raise HTTPException(404)
    try:
        papers_db = proj.get("papers", {})
        covered = list({t for p in papers_db.values() for t in p.get("subtopics", [])})
        summaries = [p["summary"] for p in papers_db.values() if p.get("summary")]
        result = detect_gaps(proj["problem_statement"], covered, summaries)
        return {"analysis": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class CompareRequest(BaseModel):
    doc_hashes: List[str]

@app.post("/api/projects/{pid}/analyze/compare")
def compare_api(pid: str, data: CompareRequest):
    from projects import load_project
    from ingestion import get_full_text
    from analysis import compare_papers

    proj = load_project(pid)
    if not proj:
        raise HTTPException(404)
    if len(data.doc_hashes) < 2:
        raise HTTPException(400, "Need at least 2 papers")
    try:
        papers = []
        for dh in data.doc_hashes:
            p = proj["papers"].get(dh)
            if p:
                papers.append({"title": p["title"], "full_text": get_full_text(dh, pid)})
        result = compare_papers(papers, proj["problem_statement"])
        return {"comparison": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Diagrams ───────────────────────────────────────────────────────────────────
class DiagramRequest(BaseModel):
    doc_hash: Optional[str] = None
    diagram_type: str = "flowchart"

@app.post("/api/projects/{pid}/generate/diagram")
def generate_diagram_api(pid: str, data: DiagramRequest):
    from projects import load_project
    from ingestion import get_full_text
    from analysis import generate_mermaid_diagram

    proj = load_project(pid)
    if not proj:
        raise HTTPException(404)
    try:
        if data.doc_hash and data.doc_hash in proj.get("papers", {}):
            paper = proj["papers"][data.doc_hash]
            text = get_full_text(data.doc_hash, pid)
            title = paper.get("title", "Paper")
        else:
            summaries = [p.get("summary", "") for p in proj.get("papers", {}).values() if p.get("summary")]
            text = "\n\n".join(summaries[:3])
            title = proj["name"]

        diagram = generate_mermaid_diagram(title, text[:4000], data.diagram_type)
        return {"diagram": diagram, "type": data.diagram_type}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Knowledge Graph ────────────────────────────────────────────────────────────
@app.get("/api/projects/{pid}/knowledge-graph")
async def knowledge_graph(pid: str):
    from projects import load_project

    proj = load_project(pid)
    if not proj:
        raise HTTPException(404)

    nodes, edges = [], []
    seen_topics = {}
    papers_db = proj.get("papers", {})

    for paper in papers_db.values():
        pid_node = f"paper_{paper['doc_hash']}"
        label = (paper.get("title") or paper.get("file_name", ""))[:35]
        nodes.append({
            "id": pid_node,
            "label": label,
            "group": "paper",
            "title": paper.get("title") or paper.get("file_name", ""),
            "status": paper.get("status", "pending"),
        })
        for topic in paper.get("subtopics", []):
            t = topic.strip().lower()
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
    from projects import load_project

    proj = load_project(pid)
    if not proj:
        raise HTTPException(404)

    papers = proj.get("papers", {})
    summaries = sum(1 for p in papers.values() if p.get("status") == "summarized")
    all_topics = list({t for p in papers.values() for t in p.get("subtopics", [])})
    chat_count = len(proj.get("chat", []))

    return {
        "total_papers": len(papers),
        "summarized": summaries,
        "topics": len(all_topics),
        "chat_messages": chat_count,
        "collaborators": len(proj.get("collaborators", {})),
        "coverage_topics": all_topics[:20],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
