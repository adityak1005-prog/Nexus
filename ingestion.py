"""
ingestion.py — PDF parsing + ChromaDB storage
Embeddings: Gemini embedding-001 (free, v1beta compatible)
Auth: GOOGLE_API_KEY from .env
"""

import os
import json
import hashlib
from datetime import datetime

from pypdf import PdfReader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sentence_transformers import SentenceTransformer
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
from chromadb.config import Settings
import chromadb
from dotenv import load_dotenv

load_dotenv()

CHROMA_DIR    = "./chroma_store"
EMBED_MODEL   = "all-MiniLM-L6-v2"   # local, free, no quota, 80MB one-time download
CHUNK_SIZE    = 800
CHUNK_OVERLAP = 150

_embedder   = None
_collection = None
_llm        = None


def get_embedder():
    global _embedder
    if _embedder is None:
        print("⏳ Loading embedding model (one-time)...")
        _embedder = SentenceTransformer(EMBED_MODEL)
        print("✅ Embedding model ready.")
    return _embedder


def get_llm():
    global _llm
    if _llm is None:
        _llm = ChatGoogleGenerativeAI(
            model="gemini-2.0-flash",
            temperature=0,
            google_api_key=os.getenv("GOOGLE_API_KEY")
        )
    return _llm


def get_collection():
    global _collection
    if _collection is None:
        client = chromadb.PersistentClient(
            path=CHROMA_DIR,
            settings=Settings(anonymized_telemetry=False)
        )
        _collection = client.get_or_create_collection(
            name="research_papers",
            metadata={"hnsw:space": "cosine"}
        )
    return _collection


# ── PDF extraction ─────────────────────────────────────────────────────────────

def extract_text_from_pdf(pdf_path: str) -> dict:
    reader = PdfReader(pdf_path)
    meta   = reader.metadata or {}
    page_texts = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if text.strip():
            page_texts.append({"page": i + 1, "text": text.strip()})
    full_text = "\n\n".join(p["text"] for p in page_texts)
    return {
        "title":      meta.get("/Title", os.path.basename(pdf_path)),
        "author":     meta.get("/Author", "Unknown"),
        "num_pages":  len(reader.pages),
        "full_text":  full_text,
        "file_name":  os.path.basename(pdf_path),
    }


def file_hash(pdf_path: str) -> str:
    with open(pdf_path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def chunk_text(text: str) -> list[str]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " "],
    )
    return splitter.split_text(text)


# ── Subtopic extraction ────────────────────────────────────────────────────────

def extract_subtopics(title: str, full_text: str) -> list[str]:
    """
    Asks Gemini to identify research subtopics from title + abstract only.
    Retries once on quota (429) errors with a 35s wait.
    Falls back to ["uncategorized"] silently so ingestion never fails.
    """
    import time
    llm = get_llm()
    snippet = full_text[:800].replace("\n", " ").strip()
    prompt = (
        f"List 3-5 research subtopics covered by this paper as a JSON array of short strings. "
        f"No explanation. No markdown. Example: [\"topic a\", \"topic b\"]\n\n"
        f"Title: {title}\nAbstract: {snippet}"
    )
    for attempt in range(2):
        try:
            response = llm.invoke([HumanMessage(content=prompt)])
            raw = response.content.strip().strip("```json").strip("```").strip()
            subtopics = json.loads(raw)
            if isinstance(subtopics, list):
                return [str(s).lower().strip() for s in subtopics]
        except Exception as e:
            if ("429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)) and attempt == 0:
                time.sleep(35)  # wait out per-minute quota window then retry
                continue
            break  # non-quota error or second failure → fall through
    return ["uncategorized"]


# ── Main ingest pipeline ───────────────────────────────────────────────────────

def ingest_pdf(pdf_path: str, uploaded_by: str = "anonymous") -> dict:
    """
    Full pipeline: PDF → extract → subtopics → chunk → embed → ChromaDB
    Deduplicates by MD5. Returns status dict.
    """
    collection = get_collection()
    embedder   = get_embedder()

    doc_hash = file_hash(pdf_path)
    existing = collection.get(where={"doc_hash": doc_hash})
    if existing["ids"]:
        return {"status": "skipped", "reason": "Already ingested",
                "file_name": os.path.basename(pdf_path), "chunks": 0}

    paper = extract_text_from_pdf(pdf_path)
    if not paper["full_text"].strip():
        return {"status": "error", "reason": "No extractable text (scanned PDF?)",
                "file_name": paper["file_name"], "chunks": 0}

    # Extract subtopics via Gemini
    subtopics = extract_subtopics(paper["title"], paper["full_text"])

    chunks     = chunk_text(paper["full_text"])
    embeddings = embedder.encode(chunks, show_progress_bar=False).tolist()

    ids       = [f"{doc_hash}_chunk_{i}" for i in range(len(chunks))]
    # Store subtopics as comma-separated string (ChromaDB metadata must be str/int/float)
    subtopics_str = ", ".join(subtopics)

    metadatas = [{
        "doc_hash":    doc_hash,
        "file_name":   paper["file_name"],
        "title":       paper["title"],
        "author":      paper["author"],
        "num_pages":   paper["num_pages"],
        "chunk_index": i,
        "uploaded_by": uploaded_by,
        "uploaded_at": datetime.now().isoformat(),
        "subtopics":   subtopics_str,
    } for i in range(len(chunks))]

    collection.add(ids=ids, embeddings=embeddings, documents=chunks, metadatas=metadatas)

    return {
        "status":    "success",
        "file_name": paper["file_name"],
        "title":     paper["title"],
        "author":    paper["author"],
        "num_pages": paper["num_pages"],
        "chunks":    len(chunks),
        "doc_hash":  doc_hash,
        "subtopics": subtopics,
        "full_text": paper["full_text"],
    }


# ── Query ──────────────────────────────────────────────────────────────────────

def query_papers(query: str, n_results: int = 5) -> list[dict]:
    """Semantic search across all papers. Returns top-n scored chunks."""
    collection      = get_collection()
    embedder        = get_embedder()
    query_embedding = embedder.encode([query]).tolist()

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
    )

    hits = []
    for i in range(len(results["ids"][0])):
        m = results["metadatas"][0][i]
        hits.append({
            "chunk":     results["documents"][0][i],
            "score":     round(1 - results["distances"][0][i], 3),
            "file_name": m["file_name"],
            "title":     m["title"],
            "author":    m["author"],
            "chunk_idx": m["chunk_index"],
            "doc_hash":  m["doc_hash"],
            "subtopics": m.get("subtopics", ""),
        })
    return hits


# ── Library helpers ────────────────────────────────────────────────────────────

def list_ingested_papers() -> list[dict]:
    """One record per unique paper."""
    collection = get_collection()
    all_items  = collection.get(include=["metadatas"])
    seen = {}
    for meta in all_items["metadatas"]:
        h = meta["doc_hash"]
        if h not in seen:
            seen[h] = {
                "title":       meta["title"],
                "author":      meta["author"],
                "file_name":   meta["file_name"],
                "num_pages":   meta["num_pages"],
                "uploaded_by": meta["uploaded_by"],
                "uploaded_at": meta["uploaded_at"],
                "doc_hash":    h,
                "subtopics":   meta.get("subtopics", "").split(", "),
            }
    return list(seen.values())


def get_topic_coverage() -> dict:
    """
    Returns a dict mapping each subtopic → list of papers covering it.
    Used by the subtopic tracker to show gaps.
    """
    papers = list_ingested_papers()
    coverage = {}
    for paper in papers:
        for topic in paper["subtopics"]:
            topic = topic.strip()
            if not topic:
                continue
            if topic not in coverage:
                coverage[topic] = []
            coverage[topic].append(paper["title"] or paper["file_name"])
    return coverage


def delete_paper(doc_hash: str) -> int:
    collection = get_collection()
    existing   = collection.get(where={"doc_hash": doc_hash})
    if existing["ids"]:
        collection.delete(ids=existing["ids"])
        return len(existing["ids"])
    return 0


def get_full_text_for_paper(doc_hash: str) -> str:
    """Reconstructs full paper text from stored chunks in correct order."""
    collection = get_collection()
    result = collection.get(
        where={"doc_hash": doc_hash},
        include=["documents", "metadatas"]
    )
    if not result["ids"]:
        return ""
    paired = sorted(zip(result["metadatas"], result["documents"]), key=lambda x: x[0]["chunk_index"])
    return "\n\n".join(doc for _, doc in paired)
