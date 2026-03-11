# Nexus — 100% Free Deployment Guide

## Stack overview

| Layer | Service | Free limits |
|-------|---------|------------|
| **Hosting** | Render or Hugging Face Spaces | Free forever |
| **LLM** | Gemini 2.5 Flash | 1500 req/day free |
| **Embeddings** | Gemini text-embedding-004 | 1500 req/day free |
| **Vector DB** | Pinecone serverless | 1 index, 100K vectors |
| **Project storage** | Supabase | 500MB Postgres, unlimited API |

**Why this works now:** Removing sentence-transformers + PyTorch drops RAM from ~900MB to ~180MB. Render's free tier (512MB) is now comfortably sufficient.

---

## Step 1 — Supabase (project storage)

1. Go to https://supabase.com → **New project** → give it a name (e.g. `nexus`)
2. Wait ~2 mins for provisioning
3. Go to **SQL Editor** → paste and run this once:

```sql
create table projects (
  id text primary key,
  data jsonb not null,
  created_at timestamptz default now()
);
```

4. Go to **Settings → API** → copy:
   - **Project URL** → this is your `SUPABASE_URL`
   - **anon public** key → this is your `SUPABASE_KEY`

---

## Step 2 — Pinecone (vector database)

1. Go to https://app.pinecone.io → **Create account** (free)
2. Go to **Indexes → Create Index**:
   - Name: `nexus-papers`
   - Dimensions: `768`  ← important, must be 768 for Gemini embeddings
   - Metric: `Cosine`
   - Configuration: **Serverless** → Cloud: `AWS` → Region: `us-east-1`
3. Go to **API Keys** → copy your key → this is `PINECONE_API_KEY`

---

## Step 3 — Google AI Studio (LLM + embeddings)

1. Go to https://aistudio.google.com/app/apikey
2. Click **Create API key**
3. Copy the key → this is `GOOGLE_API_KEY`

This single key covers both Gemini Flash (chat/summarization) and text-embedding-004 (RAG).

---

## Step 4 — Push to GitHub

```bash
# In your nexus project folder:
git init
git add .
git commit -m "Nexus initial commit"
# Create new repo at github.com, then:
git remote add origin https://github.com/YOUR_USERNAME/nexus.git
git push -u origin main
```

Make sure your repo has this structure:
```
nexus/
├── app.py
├── analysis.py
├── ingestion.py
├── projects.py
├── templates/
│   └── index.html
├── requirements.txt
├── Dockerfile
└── .gitignore        ← must exclude .env
```

---

## Step 5A — Deploy on Render (recommended)

Render free tier: 512MB RAM, sleeps after 15min inactivity, wakes in ~30s.

1. Go to https://render.com → **New → Web Service**
2. Connect your GitHub repo
3. Settings:
   - **Environment**: Docker
   - **Branch**: main
   - **Instance Type**: Free
4. Click **Advanced → Add Environment Variable** and add all four:

| Key | Value |
|-----|-------|
| `GOOGLE_API_KEY` | your key |
| `PINECONE_API_KEY` | your key |
| `PINECONE_INDEX` | `nexus-papers` |
| `SUPABASE_URL` | `https://xxxx.supabase.co` |
| `SUPABASE_KEY` | your anon key |

5. Click **Create Web Service** → first deploy takes ~4 mins (pip install)

Your URL: `https://nexus-xxxx.onrender.com`

> **Note on sleep:** Free Render services sleep after 15 min of inactivity.
> First request after sleep takes ~30s. For a demo/hackathon this is fine.
> To prevent sleeping: use https://uptimerobot.com (free) to ping `/api/health` every 14 mins.

---

## Step 5B — Deploy on Hugging Face Spaces (alternative)

HF Spaces free tier: 16GB RAM, never sleeps, but public by default.

1. Go to https://huggingface.co → **New Space**
2. Settings:
   - Space name: `nexus`
   - SDK: **Docker**
   - Hardware: **CPU basic** (free, 2 vCPU, 16GB RAM)
   - Visibility: Public (required for free)
3. Go to **Settings → Secrets** and add all env vars (same as above)
4. Push your code — HF Spaces reads from a git repo:

```bash
# Add HF remote alongside GitHub
git remote add hf https://huggingface.co/spaces/YOUR_HF_USERNAME/nexus
git push hf main
```

Your URL: `https://YOUR_HF_USERNAME-nexus.hf.space`

---

## Verify it's working

Visit: `https://your-app-url/api/health`

Expected:
```json
{
  "status": "ok",
  "google_api_key_set": true,
  "google_api_key_preview": "AIzaSyAB...",
  "tavily_key_set": false
}
```

Then create a project, upload a PDF, and click Analyse. First analysis takes ~10s (Gemini API call).

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `GOOGLE_API_KEY not set` | Check env vars in Render/HF dashboard — not from `.env` file |
| `PINECONE_API_KEY not set` | Same as above |
| Pinecone dimension error | Delete and recreate index with dimension=768, not 384 |
| Supabase `table not found` | Run the SQL in Step 1 — table must be created manually |
| Upload succeeds but Analyse fails | Check `/api/health` — usually a missing API key |
| Render sleeps too fast | Add UptimeRobot free monitor pinging `/api/health` every 14 mins |
