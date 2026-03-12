---
title: Nexus
emoji: 💻
colorFrom: gray
colorTo: yellow
sdk: docker
pinned: false
---

Check out the configuration reference at https://huggingface.co/docs/hub/spaces-config-reference


# Nexus — AI Research Intelligence Platform

> **IIT Delhi × Imperial College London AI Hackathon** — Grand Challenge 1: AI Agents for Collaborative Content Creation & Knowledge Curation

Nexus is a full-stack AI research assistant that lets teams upload academic PDFs, extract structured knowledge with Gemini, chat with their papers via RAG, detect contradictions between studies, generate Mermaid diagrams, and deconstruct complex equations — all in a single collaborative workspace.

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [File Structure](#file-structure)
- [Local Setup](#local-setup)
- [Environment Variables](#environment-variables)
- [Running Locally](#running-locally)
- [API Reference](#api-reference)
- [Deployment](#deployment)

---

## Features

| Feature | Description |
|---|---|
| **Paper Library** | Upload PDFs → auto-extracted text, chunked & embedded into Pinecone |
| **AI Analysis** | Per-paper summary, reliability assessment, and topic extraction via Gemini |
| **Research Chat** | RAG-powered Q&A across all uploaded papers with source citations |
| **Web Search** | Optional Tavily web search augmentation in chat via LangGraph agent |
| **Gap Analysis** | AI identifies unexplored areas and methodological gaps across the project |
| **Paper Comparison** | Side-by-side AI comparison of 2+ selected papers |
| **Collision Engine** | Semantic contradiction detection between paper findings |
| **Diagram Generator** | Mermaid flowcharts, mind maps, timelines, and concept maps from papers |
| **Concept Deconstructor** | 3-level scaffolded breakdowns of equations/concepts (Beginner → Advanced) |
| **Collaboration Hub** | Multi-user projects, annotations, GitHub-style contribution heatmap |
| **Feedback System** | 1–5 star ratings on every AI output; supervisor analytics dashboard |
| **Multilingual** | UI + AI responses in 8 languages (EN/AR/HI/ZH/FR/DE/ES/JA) with RTL support |
| **Accessibility** | Dyslexia font, high contrast (WCAG AAA), reduced motion, font size control |
| **Dual Theme** | OLED dark mode and crisp light mode, correctly scoped per component |

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Browser (Alpine.js SPA — index.html)                    │
│  Marked.js · KaTeX · Mermaid 11                         │
└───────────────────┬─────────────────────────────────────┘
                    │ HTTP / REST
┌───────────────────▼─────────────────────────────────────┐
│  FastAPI Backend (app.py)                                │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │ analysis.py │  │ ingestion.py │  │  projects.py   │  │
│  │ Gemini 2.5  │  │ PDF→chunks→  │  │ Supabase CRUD  │  │
│  │ Flash + RAG │  │ Pinecone     │  │ feedback/prefs │  │
│  └──────┬──────┘  └──────┬───────┘  └───────┬────────┘  │
└─────────┼────────────────┼──────────────────┼───────────┘
          │                │                  │
    ┌─────▼──────┐  ┌──────▼──────┐  ┌───────▼────────┐
    │ Google AI  │  │  Pinecone   │  │   Supabase     │
    │ Gemini 2.5 │  │ Serverless  │  │  PostgreSQL    │
    │ Flash +    │  │ (100K vecs) │  │  (JSONB store) │
    │ Embedding  │  │ cosine sim  │  │                │
    └────────────┘  └─────────────┘  └────────────────┘
```

**Data flow for a PDF upload:**
1. `POST /api/projects/{pid}/papers/upload` → `ingest_pdf()` in `ingestion.py`
2. `pypdf` extracts full text → split into 900-char chunks (150 overlap)
3. Each chunk embedded via `gemini-embedding-001` (3072 dimensions)
4. Vectors upserted to Pinecone under namespace `{project_id}`
5. Paper metadata saved to Supabase project JSONB

**Data flow for a chat message:**
1. User query embedded → top-5 Pinecone cosine matches retrieved
2. Retrieved chunks + query passed to Gemini with `language_instruction()`
3. Gemini returns answer with inline citations
4. Optional: LangGraph agent routes to Tavily web search if `use_web=true`

---

## File Structure

```
nexus/
│
├── app.py              # FastAPI routes — all HTTP endpoints
├── analysis.py         # All AI logic (Gemini calls, RAG, prompts, deconstructor)
├── ingestion.py        # PDF parsing, chunking, Pinecone upsert/query
├── projects.py         # Supabase CRUD — projects, papers, annotations, feedback
│
├── templates/
│   └── index.html      # Single-file Alpine.js SPA (all HTML + CSS + JS)
│
├── requirements.txt    # Python dependencies
├── Dockerfile          # Container config for Render / HF Spaces
├── .env.example        # Template for environment variables
└── README.md           # This file
```

### `app.py` — Route map

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Serves `index.html` |
| `GET` | `/api/health` | Health check + env var status |
| `GET` | `/api/projects` | List all projects |
| `POST` | `/api/projects` | Create project |
| `GET` | `/api/projects/{pid}` | Get project (papers, chat, collaborators) |
| `POST` | `/api/projects/{pid}/papers/upload` | Upload + ingest PDF |
| `DELETE` | `/api/projects/{pid}/papers/{hash}` | Delete paper + Pinecone vectors |
| `POST` | `/api/projects/{pid}/papers/{hash}/summarize` | AI analysis (summary + reliability + topics) |
| `POST` | `/api/projects/{pid}/papers/{hash}/annotations` | Add team annotation |
| `DELETE` | `/api/projects/{pid}/papers/{hash}/annotations/{id}` | Delete annotation |
| `POST` | `/api/projects/{pid}/chat` | Send chat message (RAG ± web search) |
| `POST` | `/api/projects/{pid}/analyze/gaps` | Run gap analysis |
| `POST` | `/api/projects/{pid}/analyze/compare` | Compare selected papers |
| `POST` | `/api/projects/{pid}/generate/diagram` | Generate Mermaid diagram |
| `POST` | `/api/projects/{pid}/deconstruct` | Run Concept Deconstructor |
| `POST` | `/api/projects/{pid}/feedback` | Submit AI output rating |
| `GET` | `/api/projects/{pid}/feedback/stats` | Feedback analytics |
| `POST` | `/api/projects/{pid}/feedback/summary` | AI synthesis of feedback |
| `GET/PATCH` | `/api/projects/{pid}/users/{username}/preferences` | Per-user language/role/a11y prefs |
| `GET` | `/api/projects/{pid}/stats` | Project statistics |

### `analysis.py` — Key functions

| Function | Purpose |
|---|---|
| `UserContext` | Dataclass carrying `language`, `role`, `expertise` — appended to every prompt via `language_instruction()` |
| `summarize_paper()` | Full AI analysis: summary + reliability + subtopic extraction |
| `answer_with_rag()` | RAG chat: embed query → Pinecone search → Gemini answer with citations |
| `answer_with_web_search()` | LangGraph agent with Tavily tool for live web search |
| `run_gap_analysis()` | Identifies unexplored areas and contradictions across all papers |
| `compare_papers()` | Structured comparison of 2+ papers |
| `generate_diagram()` | Produces Mermaid syntax (flowchart / mindmap / timeline / concept map) |
| `deconstruct_concept()` | 3-level scaffolded explanation: intuition → technical → advanced |
| `generate_feedback_summary()` | Supervisor-facing AI synthesis of collected ratings |

### `ingestion.py` — Key functions

| Function | Purpose |
|---|---|
| `ingest_pdf()` | Full pipeline: parse → chunk → embed → upsert to Pinecone |
| `query_papers()` | Embed query → cosine search Pinecone → return top-k chunks |
| `delete_paper_vectors()` | Remove all Pinecone vectors for a given doc hash |
| `get_full_text()` | Retrieve all stored chunks for a paper (uses Pinecone list API) |

---

## Local Setup

### Prerequisites

- Python 3.11+
- A Google AI Studio API key (free — covers both Gemini Flash and embeddings)
- A Pinecone account (free tier: 1 index, 100K vectors)
- A Supabase account (free tier: 500MB Postgres)
- _(Optional)_ A Tavily API key for web search in chat

### 1. Clone the repo

```bash
git clone https://github.com/YOUR_USERNAME/nexus.git
cd nexus
```

### 2. Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate        # macOS/Linux
# or
.venv\Scripts\activate           # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Set up external services

**Supabase** (project storage):
1. Create a free project at [supabase.com](https://supabase.com)
2. Open **SQL Editor** and run:
```sql
create table projects (
  id text primary key,
  data jsonb not null,
  created_at timestamptz default now()
);
```
3. Copy your **Project URL** and **anon public key** from Settings → API

**Pinecone** (vector database):
1. Create a free account at [app.pinecone.io](https://app.pinecone.io)
2. Create an index:
   - Name: `nexus-papers`
   - **Dimensions: `3072`** (required for `gemini-embedding-001`)
   - Metric: `Cosine`
   - Type: Serverless → AWS → `us-east-1`
3. Copy your API key

**Google AI Studio** (LLM + embeddings):
1. Go to [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)
2. Create an API key — one key covers both Gemini Flash and embedding models

---

## Environment Variables

Create a `.env` file in the project root:

```env
# Required
GOOGLE_API_KEY=AIzaSy...
PINECONE_API_KEY=pcsk_...
PINECONE_INDEX=nexus-papers
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_KEY=eyJhbGci...

# Optional — enables web search in Research Chat
TAVILY_API_KEY=tvly-...
```

> **Never commit `.env` to git.** Add it to `.gitignore`.

---

## Running Locally

```bash
uvicorn app:app --reload --port 8000
```

Open [http://localhost:8000](http://localhost:8000)

Verify the backend is healthy:
```bash
curl http://localhost:8000/api/health
```

Expected response:
```json
{
  "status": "ok",
  "google_api_key_set": true,
  "tavily_key_set": false
}
```

### First run walkthrough

1. Click **Create your first project** — enter a name and research problem statement
2. Go to **Library** → drag & drop a PDF (or click to browse)
3. Wait for upload confirmation — chunks are embedded automatically
4. Click the paper card → click **Analyse** — AI generates summary, reliability, and topics (~10–30s)
5. Go to **Research Chat** → ask a question about your paper
6. Try **Diagrams** → select Timeline or Flowchart → Generate
7. Try **Deconstructor** → paste an equation like `∇·E = ρ/ε₀`

---

## API Reference

All endpoints accept and return JSON. Papers are identified by their SHA-256 content hash (`doc_hash`). Projects are identified by a UUID (`pid`).

### Create a project

```bash
curl -X POST http://localhost:8000/api/projects \
  -H "Content-Type: application/json" \
  -d '{"name": "Transformer Survey", "problem_statement": "How do attention mechanisms scale?", "created_by": "alice"}'
```

### Upload a PDF

```bash
curl -X POST "http://localhost:8000/api/projects/{pid}/papers/upload?username=alice" \
  -F "file=@attention_is_all_you_need.pdf"
```

### Analyse a paper

```bash
curl -X POST "http://localhost:8000/api/projects/{pid}/papers/{hash}/summarize?username=alice&language=en&role=student&expertise=intermediate"
```

### Chat with papers

```bash
curl -X POST http://localhost:8000/api/projects/{pid}/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is the main contribution?", "username": "alice", "use_web": false, "language": "en", "role": "student", "expertise": "intermediate"}'
```

### Generate a diagram

```bash
curl -X POST http://localhost:8000/api/projects/{pid}/generate/diagram \
  -H "Content-Type: application/json" \
  -d '{"doc_hash": null, "diagram_type": "flowchart", "username": "alice", "language": "en"}'
```

---

## Deployment

See [`DEPLOY.md`](./DEPLOY.md) for full instructions on deploying to:
- **Render** (free tier, Docker, sleeps after 15 min inactivity)
- **Hugging Face Spaces** (free tier, Docker, always-on, 16GB RAM)

Quick summary of required env vars for both platforms:

| Variable | Where to get it |
|---|---|
| `GOOGLE_API_KEY` | [aistudio.google.com](https://aistudio.google.com/app/apikey) |
| `PINECONE_API_KEY` | [app.pinecone.io](https://app.pinecone.io) → API Keys |
| `PINECONE_INDEX` | Name of your index (e.g. `nexus-papers`) |
| `SUPABASE_URL` | Supabase project → Settings → API → Project URL |
| `SUPABASE_KEY` | Supabase project → Settings → API → anon public key |
| `TAVILY_API_KEY` | [tavily.com](https://tavily.com) _(optional)_ |

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Frontend** | Alpine.js 3 · Marked.js · KaTeX · Mermaid 11 · Syne + DM Sans fonts |
| **Backend** | FastAPI · Uvicorn · Python 3.11 |
| **AI / LLM** | Gemini 2.5 Flash (chat, analysis, diagrams) |
| **Embeddings** | `gemini-embedding-001` — 3072 dimensions |
| **Vector DB** | Pinecone Serverless (cosine similarity, RAG retrieval) |
| **Project Storage** | Supabase PostgreSQL (JSONB document store) |
| **AI Framework** | LangChain · LangGraph (web search agent) |
| **PDF Parsing** | pypdf |
| **Web Search** | Tavily (optional) |
| **Containerisation** | Docker |
| **Hosting** | Render / Hugging Face Spaces |