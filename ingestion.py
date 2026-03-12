"""
ingestion.py — PDF pipeline
Embedding:  Gemini text-embedding-004 (API, no local model — zero RAM overhead)
PDF parse:  pypdf
Vector DB:  Pinecone (free tier — 1 index, 100K vectors)

Why Gemini embeddings:
- No PyTorch / sentence-transformers → Docker image drops from ~3GB to ~400MB
- No RAM for model weights → app runs comfortably on 512MB free-tier hosts
- text-embedding-004 produces 768-dim vectors (higher quality than bge-small-en 384-dim)
- Included in the same GOOGLE_API_KEY already used for Gemini Flash — no new credentials
- Free tier: 1500 embedding requests/day (each PDF ≈ 10-30 requests for its chunks)
"""
import os, json, hashlib, logging, time
from datetime import datetime

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from projects import get_chroma_collection_name

load_dotenv()
logging.getLogger("langsmith").setLevel(logging.WARNING)

<<<<<<< HEAD
<<<<<<< HEAD
EMBED_MODEL    = "models/text-embedding-001"   # 768-dim, free via Gemini API 
=======
EMBED_MODEL    = "models/text-embedding-004"   # 768-dim, free via Gemini API
>>>>>>> 0fc9370750eacdfca255424a326e799ca2b72131
=======
EMBED_MODEL    = "models/text-embedding-004"   # 768-dim, free via Gemini API 
>>>>>>> 6f8f52bd072ad1dad19e535bf708f098650c29bc
EMBED_DIM      = 768
CHUNK_SIZE     = 900
CHUNK_OVERLAP  = 150
PINECONE_INDEX = os.getenv("PINECONE_INDEX", "nexus-papers")

# ── Gemini Embeddings ──────────────────────────────────────────────────────────
_embedder = None

def get_embedder():
    global _embedder
    if _embedder is None:
        api_key = os.getenv("GOOGLE_API_KEY", "")
        if not api_key:
            raise RuntimeError("GOOGLE_API_KEY not set.")
        _embedder = GoogleGenerativeAIEmbeddings(
            model=EMBED_MODEL,
            google_api_key=api_key,
            task_type="retrieval_document",   # optimised for RAG indexing
        )
    return _embedder

def embed_texts(texts: list[str], task: str = "retrieval_document") -> list[list[float]]:
    """
    Embed a list of texts using Gemini text-embedding-004.
    task = "retrieval_document"  → for indexing chunks
    task = "retrieval_query"     → for query-time embedding (better recall)
    """
    embedder = get_embedder()
    # GoogleGenerativeAIEmbeddings supports task_type override per call
    if task == "retrieval_query":
        embedder = GoogleGenerativeAIEmbeddings(
            model=EMBED_MODEL,
            google_api_key=os.getenv("GOOGLE_API_KEY"),
            task_type="retrieval_query",
        )
    # embed_documents handles batching internally
    return embedder.embed_documents(texts)

def embed_query(query: str) -> list[float]:
    """Single query embedding — uses retrieval_query task type for better recall."""
    embedder = GoogleGenerativeAIEmbeddings(
        model=EMBED_MODEL,
        google_api_key=os.getenv("GOOGLE_API_KEY"),
        task_type="retrieval_query",
    )
    return embedder.embed_query(query)


# ── Pinecone ───────────────────────────────────────────────────────────────────
_pinecone_index = None

def get_pinecone_index():
    global _pinecone_index
    if _pinecone_index is not None:
        return _pinecone_index

    api_key = os.getenv("PINECONE_API_KEY")
    if not api_key:
        raise RuntimeError("PINECONE_API_KEY not set.")

    from pinecone import Pinecone, ServerlessSpec
    pc = Pinecone(api_key=api_key)

    # text-embedding-004 produces 768-dim vectors
    existing = [i.name for i in pc.list_indexes()]
    if PINECONE_INDEX not in existing:
        pc.create_index(
            name=PINECONE_INDEX,
            dimension=EMBED_DIM,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1")
        )
        while not pc.describe_index(PINECONE_INDEX).status["ready"]:
            time.sleep(1)

    _pinecone_index = pc.Index(PINECONE_INDEX)
    return _pinecone_index


def _namespace(pid: str) -> str:
    """Each project gets its own Pinecone namespace — isolates papers per project."""
    return get_chroma_collection_name(pid)


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

    # Try Unstructured first (optional upgrade)
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
    try:
        r   = get_llm().invoke([HumanMessage(content=prompt)])
        raw = r.content.strip().strip("```json").strip("```").strip()
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(x).lower().strip() for x in parsed]
    except Exception as e:
        print(f"[Nexus] Subtopic extraction error: {e}")
    return []


# ── Ingestion pipeline ─────────────────────────────────────────────────────────
def ingest_pdf(pdf_path: str, project_id: str, uploaded_by: str = "anonymous") -> dict:
    idx = get_pinecone_index()
    ns  = _namespace(project_id)
    dh  = file_hash(pdf_path)

    # Check if already ingested (query by doc_hash metadata)
    existing = idx.query(
        vector=[0.0] * 384, top_k=1, namespace=ns,
        filter={"doc_hash": {"$eq": dh}}, include_metadata=False
    )
    if existing["matches"]:
        return {"status": "skipped", "file_name": os.path.basename(pdf_path),
                "chunks": 0, "doc_hash": dh}

    paper = extract_text(pdf_path)
    if not paper["full_text"].strip():
        return {"status": "error", "reason": f"No extractable text (parser: {paper.get('parser','?')})",
                "file_name": paper["file_name"], "chunks": 0, "doc_hash": ""}

    chunks     = chunk_text(paper["full_text"])
    embeddings = embed_texts(chunks)
    now        = datetime.now().isoformat()

    # Pinecone upsert in batches of 100
    vectors = []
    for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
        vectors.append({
            "id": f"{dh}_chunk_{i}",
            "values": emb,
            "metadata": {
                "doc_hash":    dh,
                "file_name":   paper["file_name"],
                "title":       paper["title"],
                "author":      paper["author"],
                "num_pages":   paper["num_pages"],
                "chunk_index": i,
                "chunk_text":  chunk[:500],   # store first 500 chars for retrieval
                "uploaded_by": uploaded_by,
                "uploaded_at": now,
            }
        })

    # Upsert in batches (Pinecone limit = 100 vectors per call)
    for i in range(0, len(vectors), 100):
        idx.upsert(vectors=vectors[i:i+100], namespace=ns)

    return {
        "status":    "success",
        "file_name": paper["file_name"],
        "title":     paper["title"],
        "author":    paper["author"],
        "num_pages": paper["num_pages"],
        "chunks":    len(chunks),
        "doc_hash":  dh,
        "subtopics": [],
        "full_text": paper["full_text"],
        "parser":    paper.get("parser"),
    }


# ── Query ──────────────────────────────────────────────────────────────────────
def query_papers(query: str, project_id: str, n_results: int = 5) -> list[dict]:
    idx = get_pinecone_index()
    ns  = _namespace(project_id)

    stats = idx.describe_index_stats()
    ns_count = stats.get("namespaces", {}).get(ns, {}).get("vector_count", 0)
    if ns_count == 0:
        return []

    # Use retrieval_query task type — semantically different from retrieval_document
    # This gives meaningfully better recall than using the same embedding for both
    qe  = embed_query(query)
    res = idx.query(
        vector=qe,
        top_k=n_results * 2,
        namespace=ns,
        include_metadata=True
    )

    hits = []
    for match in res["matches"][:n_results]:
        m = match["metadata"]
        hits.append({
            "chunk":     m.get("chunk_text", ""),
            "score":     round(match["score"], 3),
            "file_name": m["file_name"],
            "title":     m["title"],
            "author":    m["author"],
            "chunk_idx": m["chunk_index"],
            "doc_hash":  m["doc_hash"],
        })
    return hits


# ── Helpers ────────────────────────────────────────────────────────────────────
def list_ingested_papers(pid: str) -> list[dict]:
    """List unique papers in a project namespace."""
    idx = get_pinecone_index()
    ns  = _namespace(pid)

    stats = idx.describe_index_stats()
    ns_count = stats.get("namespaces", {}).get(ns, {}).get("vector_count", 0)
    if ns_count == 0:
        return []

    res = idx.query(
        vector=[0.0] * EMBED_DIM, top_k=min(ns_count, 200),
        namespace=ns, include_metadata=True
    )
    seen = {}
    for match in res["matches"]:
        m = match["metadata"]
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
                "subtopics":   [],
                "parser":      "pypdf",
            }
    return list(seen.values())

def get_full_text(doc_hash: str, pid: str) -> str:
    """Reconstruct full text by fetching all chunks for a doc_hash."""
    idx = get_pinecone_index()
    ns  = _namespace(pid)

    res = idx.query(
        vector=[0.0] * EMBED_DIM, top_k=500, namespace=ns,
        filter={"doc_hash": {"$eq": doc_hash}},
        include_metadata=True
    )
    if not res["matches"]:
        return ""
    chunks = sorted(res["matches"], key=lambda x: x["metadata"]["chunk_index"])
    return "\n\n".join(c["metadata"].get("chunk_text", "") for c in chunks)

def delete_paper(doc_hash: str, pid: str) -> int:
    """Delete all vectors for a doc_hash from a project namespace."""
    idx = get_pinecone_index()
    ns  = _namespace(pid)

    res = idx.query(
        vector=[0.0] * EMBED_DIM, top_k=500, namespace=ns,
        filter={"doc_hash": {"$eq": doc_hash}},
        include_metadata=False
    )
    ids = [m["id"] for m in res["matches"]]
    if ids:
        idx.delete(ids=ids, namespace=ns)
    return len(ids)

def get_topic_coverage(pid: str) -> dict:
    cov = {}
    for p in list_ingested_papers(pid):
        for t in p["subtopics"]:
            if t:
                cov.setdefault(t, []).append(p["title"] or p["file_name"])
    return cov
