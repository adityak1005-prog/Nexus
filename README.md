# Nexus — AI Research Intelligence Platform

> A collaborative AI-powered workspace for research teams to upload, analyse, and synthesise academic papers — built for the **AI Agents for Collaborative Content Creation & Knowledge Curation** Grand Challenge.

---

## What It Does

Research teams drown in PDFs. Members work in silos, miss contradictions found by others, and waste hours on manual summarisation. Nexus fixes this with a shared AI workspace where every paper is automatically analysed and made searchable across the entire team.

| Feature | Description |
|---------|-------------|
| 📄 **Paper Library** | Upload PDFs — AI extracts summaries, reliability assessments, and research topics automatically |
| 💬 **Research Chat** | Ask questions across your entire library with cited answers from your uploaded papers |
| 🔍 **Gap Analysis** | Identify contradictions, unexplored areas, and methodological gaps across all papers |
| ◈ **Knowledge Graph** | Interactive visual map of how papers connect through shared topics |
| ◇ **Diagram Generator** | Convert any paper into flowcharts, mind maps, timelines, or concept maps |
| 👥 **Team Collaboration** | Shared annotations, collaborator tracking, per-project workspaces |
| 📊 **Paper Comparison** | Select multiple papers and get a structured head-to-head analysis |

---

## Tech Stack

```
Frontend    → Single-page HTML + Alpine.js (zero build step)
Backend     → FastAPI (Python)
LLM         → Gemini 2.5 Flash (summarisation, chat, gap analysis, diagrams)
Embeddings  → Gemini text-embedding-004 (RAG — no local model, no PyTorch)
Vector DB   → Pinecone serverless (free tier)
Storage     → Supabase Postgres (free tier) for project/chat data
PDF Parsing → pypdf
```

---

## Project Structure

```
nexus/
├── app.py              # FastAPI routes
├── analysis.py         # All AI functions (Gemini 2.5 Flash)
├── ingestion.py        # PDF pipeline → Gemini embeddings → Pinecone
├── projects.py         # Project/collaborator/chat/annotation management
├── templates/
│   └── index.html      # Full frontend (Alpine.js, single file)
├── requirements.txt
├── Dockerfile
└── .env.example
```

---

## Local Setup

### Prerequisites
- Python 3.11 or 3.12 (not 3.13+)
- API keys — see [Getting API Keys](#getting-api-keys)

### Install & Run

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/nexus.git
cd nexus

# Create virtual environment (must use Python 3.11 or 3.12)
py -3.11 -m venv .venv

# Activate (Windows)
.venv\Scripts\activate
# Activate (Mac/Linux)
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy and fill in your environment variables
cp .env.example .env
# Edit .env with your API keys

# Run
uvicorn app:app --reload --port 8000
```

Open http://localhost:8000

---

## Getting API Keys

All services have free tiers sufficient for a team demo.

### 1. Google AI Studio — LLM + Embeddings
- Go to https://aistudio.google.com/app/apikey
- Click **Create API key**
- Free tier: 1500 requests/day for both Gemini Flash and text-embedding-004

### 2. Pinecone — Vector Database
- Go to https://app.pinecone.io → Create account
- Go to **Indexes → Create Index** with these exact settings:
  - Name: `nexus-papers`
  - Dimensions: **768**
  - Metric: **Cosine**
  - Configuration: **Serverless** → AWS → us-east-1
- Go to **API Keys** → copy your key
- Free tier: 1 index, 100K vectors

### 3. Supabase — Project Storage
- Go to https://supabase.com → New project
- Go to **SQL Editor** → run this once:
  ```sql
  create table projects (
    id text primary key,
    data jsonb not null,
    created_at timestamptz default now()
  );

  alter table projects enable row level security;
  create policy "Allow all" on projects for all using (true) with check (true);
  ```
- Go to **Settings → API** → copy Project URL and anon key
- Free tier: 500MB Postgres

---

## Environment Variables

Create a `.env` file in the project root:

```env
# Required
GOOGLE_API_KEY=your_google_api_key_here

# Required — Pinecone
PINECONE_API_KEY=your_pinecone_api_key_here
PINECONE_INDEX=nexus-papers

# Required — Supabase
SUPABASE_URL=https://xxxxxxxxxxxx.supabase.co
SUPABASE_KEY=your_supabase_anon_key_here

# Optional — enables web search in Research Chat
TAVILY_API_KEY=your_tavily_api_key_here
```

---

## Deployment (Free)

Deployed on **Hugging Face Spaces** (free, always-on, 16GB RAM CPU).

### Steps

1. **Push to GitHub**
   ```bash
   git init && git add . && git commit -m "Initial commit"
   git remote add origin https://github.com/YOUR_USERNAME/nexus.git
   git push -u origin main
   ```

2. **Create a Hugging Face Space**
   - Go to https://huggingface.co → New Space
   - SDK: **Docker** | Hardware: **CPU basic** (free)

3. **Add secrets** in Space Settings → Secrets:
   - `GOOGLE_API_KEY`
   - `PINECONE_API_KEY`, `PINECONE_INDEX`
   - `SUPABASE_URL`, `SUPABASE_KEY`

4. **Push code to HF**
   ```bash
   git remote add hf https://huggingface.co/spaces/YOUR_HF_USERNAME/nexus
   git push hf main
   ```

Your app will be live at `https://YOUR_HF_USERNAME-nexus.hf.space`

### Verify deployment
```
GET /api/health
```
```json
{
  "status": "ok",
  "google_api_key_set": true,
  "tavily_key_set": false
}
```

---

## How It Works

### PDF Upload Pipeline
```
PDF upload
  → pypdf extracts full text
  → text split into ~900 char chunks (150 char overlap)
  → Gemini text-embedding-004 embeds each chunk (768-dim vectors)
  → vectors upserted into Pinecone under project namespace
  → paper metadata saved to Supabase
```

### Research Chat (RAG)
```
User question
  → embedded with Gemini text-embedding-004 (retrieval_query task)
  → top-5 chunks retrieved from Pinecone by cosine similarity
  → chunks + question sent to Gemini 2.5 Flash
  → answer returned with citations [Source N: Paper Title]
```

### Paper Analysis
```
Click "Analyse"
  → full text retrieved from Pinecone chunks
  → Gemini generates: summary, reliability assessment, research topics
  → results saved to Supabase project record
```

---

## Target Users

- Undergraduate & postgraduate students doing thesis or course projects
- Research beginners exploring new domains
- Interdisciplinary teams conducting literature surveys
- Educators supervising student research groups

---

## Grand Challenge Context

Built for the **AI Agents for Collaborative Content Creation & Knowledge Curation** challenge. Addresses the core problem: research is a disconnected single-player experience. Teams drown in papers, develop knowledge silos, and duplicate work.

Reference tools this improves on:
- [Elicit.org](https://elicit.org) — AI for literature review
- [Semantic Scholar](https://www.semanticscholar.org) — AI-powered academic search

Nexus adds the **collaborative layer** both tools lack: shared workspaces, team annotations, cross-paper chat, and visual knowledge mapping — all in one deployable app.

---

## License

MIT