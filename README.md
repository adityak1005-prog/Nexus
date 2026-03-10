# ✦ Nexus — Research Intelligence Platform

An AI-assisted collaborative research workspace that transforms how student teams handle academic literature.

## Stack
| Layer | Tech |
|---|---|
| Backend | FastAPI + Uvicorn |
| Frontend | Vanilla SPA (Alpine.js + vis.js + Mermaid.js) |
| LLM | Gemini 2.5 Flash (free tier) |
| Embeddings | FastEmbed / BAAI/bge-small-en (ONNX, no PyTorch) |
| Vector DB | ChromaDB (local) |
| Web Search | Tavily (optional, 1000/month free) |

## Setup

### 1. Clone / copy files
```
nexus/
├── app.py
├── analysis.py
├── ingestion.py
├── projects.py
├── tools.py
├── requirements.txt
├── .env.example
└── templates/
    └── index.html
```

### 2. Create a virtual environment
```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Set up API keys
```bash
cp .env.example .env
# Edit .env and add your GOOGLE_API_KEY
```

Get your free Gemini API key at: https://aistudio.google.com/apikey

### 5. Run
```bash
uvicorn app:app --reload --port 8000
```

Open: http://localhost:8000

---

## Features

### 📚 Paper Library
- Drag & drop PDF upload (multiple files at once)
- Automatic text extraction and chunking
- AI-generated subtopic tags per paper
- One-click AI analysis (summary + reliability check)
- Team annotations per paper

### 💬 Research Chat
- RAG-powered Q&A over uploaded papers
- Citations shown below every AI response
- Optional Tavily web search (toggle with 🌐 button)
- Markdown rendering with code highlighting

### 🕸️ Knowledge Graph
- Interactive vis.js graph
- Papers connected through shared topics
- Drag, zoom, hover for details

### ⚡ Diagram Generator
- Flowchart · Mind Map · Timeline · Concept Map
- AI generates Mermaid syntax from paper content
- Copy Mermaid code for use anywhere

### 🔍 Insights
- Gap analysis across entire literature review
- Paper-to-paper comparison (select 2+ papers)
- Topic coverage visualization

---

## API Keys

| Key | Required | Where to Get | Free Tier |
|---|---|---|---|
| GOOGLE_API_KEY | ✅ Yes | aistudio.google.com/apikey | Generous free tier |
| TAVILY_API_KEY | No | app.tavily.com | 1000 searches/month |

---

## Notes

- ChromaDB and project data persist in `./chroma_store/` and `./projects_data/`
- First run downloads the FastEmbed model (~40MB, cached afterward)
- FastAPI backend runs on port 8000 by default
