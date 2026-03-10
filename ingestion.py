"""
ingestion.py — PDF pipeline
Embedding:  FastEmbed (ONNX, BAAI/bge-small-en-v1.5)
PDF parse:  pypdf (Unstructured as optional upgrade)
Vector DB:  ChromaDB (cosine similarity)
"""
import os, json, hashlib, time, logging
from datetime import datetime

import chromadb
from chromadb.config import Settings
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_text_splitters import RecursiveCharacterTextSplitter
from projects import get_chroma_collection_name

load_dotenv()
logging.getLogger("langsmith").setLevel(logging.WARNING)

CHROMA_DIR    = "./chroma_store"
EMBED_MODEL   = "BAAI/bge-small-en-v1.5"
CHUNK_SIZE    = 900
CHUNK_OVERLAP = 150

# ── FastEmbed ──────────────────────────────────────────────────────────────────
_embedder = None
def get_embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer("BAAI/bge-small-en-v1.5")
    return _embedder

# NEW (sentence-transformers syntax)
def embed_texts(texts: list[str]) -> list[list[float]]:
    return get_embedder().encode(texts, show_progress_bar=False).tolist()


# ── ChromaDB ───────────────────────────────────────────────────────────────────
_chroma_client = None
def get_chroma_client():
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(
            path=CHROMA_DIR,
            settings=Settings(anonymized_telemetry=False)
        )
    return _chroma_client

def get_collection(pid):
    return get_chroma_client().get_or_create_collection(
        name=get_chroma_collection_name(pid),
        metadata={"hnsw:space": "cosine"}
    )


# ── Gemini for subtopic extraction ────────────────────────────────────────────
_llm = None
def get_llm():
    global _llm
    if _llm is None:
        _llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            temperature=0,
            google_api_key=os.getenv("GOOGLE_API_KEY")
        )
    return _llm


# ── PDF extraction ─────────────────────────────────────────────────────────────
def extract_text(pdf_path: str) -> dict:
    file_name = os.path.basename(pdf_path)
    title, author, num_pages = file_name, "Unknown", 0

    # Try Unstructured first
    try:
        from unstructured.partition.pdf import partition_pdf
        elements  = partition_pdf(filename=pdf_path, strategy="fast")
        full_text = "\n\n".join(str(e) for e in elements if str(e).strip())
        try:
            from pypdf import PdfReader
            reader    = PdfReader(pdf_path)
            num_pages = len(reader.pages)
            meta      = reader.metadata or {}
            title     = meta.get("/Title", file_name) or file_name
            author    = meta.get("/Author", "Unknown") or "Unknown"
        except Exception:
            pass
        if full_text.strip():
            return {"title": title, "author": author, "num_pages": num_pages,
                    "full_text": full_text, "file_name": file_name, "parser": "unstructured"}
    except Exception:
        pass

    # Fallback: pypdf
    try:
        from pypdf import PdfReader
        reader    = PdfReader(pdf_path)
        meta      = reader.metadata or {}
        title     = meta.get("/Title", file_name) or file_name
        author    = meta.get("/Author", "Unknown") or "Unknown"
        num_pages = len(reader.pages)
        pages     = [p.extract_text() or "" for p in reader.pages]
        full_text = "\n\n".join(t.strip() for t in pages if t.strip())
        return {"title": title, "author": author, "num_pages": num_pages,
                "full_text": full_text, "file_name": file_name, "parser": "pypdf"}
    except Exception as e:
        return {"title": file_name, "author": "Unknown", "num_pages": 0,
                "full_text": "", "file_name": file_name, "parser": "error", "error": str(e)}


def file_hash(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()

def chunk_text(text: str) -> list[str]:
    return RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " "]
    ).split_text(text)

def extract_subtopics(title: str, full_text: str) -> list[str]:
    snippet = full_text[:800].replace("\n", " ").strip()
    prompt  = (
        f"List 3-5 research subtopics for this paper as a JSON array of short strings. "
        f"No explanation, no markdown fences.\n"
        f"Title: {title}\nAbstract/intro: {snippet}"
    )
    for attempt in range(2):
        try:
            r   = get_llm().invoke([HumanMessage(content=prompt)])
            raw = r.content.strip().strip("```json").strip("```").strip()
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(x).lower().strip() for x in parsed]
        except Exception as e:
            if ("429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)) and attempt == 0:
                time.sleep(35)
                continue
            break
    return ["uncategorized"]


# ── Ingestion pipeline ─────────────────────────────────────────────────────────
def ingest_pdf(pdf_path: str, project_id: str, uploaded_by: str = "anonymous") -> dict:
    col = get_collection(project_id)
    dh  = file_hash(pdf_path)

    if col.get(where={"doc_hash": dh})["ids"]:
        return {"status": "skipped", "file_name": os.path.basename(pdf_path),
                "chunks": 0, "doc_hash": dh}

    paper = extract_text(pdf_path)
    if not paper["full_text"].strip():
        return {"status": "error", "reason": f"No extractable text (parser: {paper.get('parser','?')})",
                "file_name": paper["file_name"], "chunks": 0, "doc_hash": ""}

    subtopics  = extract_subtopics(paper["title"], paper["full_text"])
    chunks     = chunk_text(paper["full_text"])
    embeddings = embed_texts(chunks)

    ids   = [f"{dh}_chunk_{i}" for i in range(len(chunks))]
    metas = [{
        "doc_hash":    dh,
        "file_name":   paper["file_name"],
        "title":       paper["title"],
        "author":      paper["author"],
        "num_pages":   paper["num_pages"],
        "chunk_index": i,
        "uploaded_by": uploaded_by,
        "uploaded_at": datetime.now().isoformat(),
        "subtopics":   ", ".join(subtopics),
        "parser":      paper.get("parser", "unknown"),
    } for i in range(len(chunks))]

    col.add(ids=ids, embeddings=embeddings, documents=chunks, metadatas=metas)

    return {
        "status":    "success",
        "file_name": paper["file_name"],
        "title":     paper["title"],
        "author":    paper["author"],
        "num_pages": paper["num_pages"],
        "chunks":    len(chunks),
        "doc_hash":  dh,
        "subtopics": subtopics,
        "full_text": paper["full_text"],
        "parser":    paper.get("parser"),
    }


# ── Query ─────────────────────────────────────────────────────────────────────
def query_papers(query: str, project_id: str, n_results: int = 5) -> list[dict]:
    col   = get_collection(project_id)
    total = col.count()
    if total == 0:
        return []

    fetch_n = min(n_results * 2, total)
    qe      = embed_texts([query])

    res = col.query(
        query_embeddings=qe,
        n_results=fetch_n,
        include=["documents", "metadatas", "distances"]
    )

    hits = [{
        "chunk":     res["documents"][0][i],
        "score":     round(1 - res["distances"][0][i], 3),
        "file_name": res["metadatas"][0][i]["file_name"],
        "title":     res["metadatas"][0][i]["title"],
        "author":    res["metadatas"][0][i]["author"],
        "chunk_idx": res["metadatas"][0][i]["chunk_index"],
        "doc_hash":  res["metadatas"][0][i]["doc_hash"],
    } for i in range(len(res["ids"][0]))]

    return hits[:n_results]


# ── Helpers ────────────────────────────────────────────────────────────────────
def list_ingested_papers(pid: str) -> list[dict]:
    col  = get_collection(pid)
    data = col.get(include=["metadatas"])
    seen = {}
    for m in data["metadatas"]:
        h = m["doc_hash"]
        if h not in seen:
            seen[h] = {
                "title":       m["title"],
                "author":      m["author"],
                "file_name":   m["file_name"],
                "num_pages":   m["num_pages"],
                "uploaded_by": m["uploaded_by"],
                "uploaded_at": m["uploaded_at"],
                "doc_hash":    h,
                "subtopics":   [t.strip() for t in m.get("subtopics","").split(",") if t.strip()],
                "parser":      m.get("parser","unknown"),
            }
    return list(seen.values())

def get_full_text(doc_hash: str, pid: str) -> str:
    col = get_collection(pid)
    r   = col.get(where={"doc_hash": doc_hash}, include=["documents","metadatas"])
    if not r["ids"]:
        return ""
    paired = sorted(zip(r["metadatas"], r["documents"]), key=lambda x: x[0]["chunk_index"])
    return "\n\n".join(d for _, d in paired)

def delete_paper(doc_hash: str, pid: str) -> int:
    col = get_collection(pid)
    ex  = col.get(where={"doc_hash": doc_hash})
    if ex["ids"]:
        col.delete(ids=ex["ids"])
        return len(ex["ids"])
    return 0

def get_topic_coverage(pid: str) -> dict:
    cov = {}
    for p in list_ingested_papers(pid):
        for t in p["subtopics"]:
            if t:
                cov.setdefault(t, []).append(p["title"] or p["file_name"])
    return cov
