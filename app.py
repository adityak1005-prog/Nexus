"""
app.py — ResearchCollab Streamlit App
Pages: Upload → Library → Topic Tracker → Summarize & Export → Team Q&A
"""

import streamlit as st
import os
import tempfile
from dotenv import load_dotenv

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.prebuilt import create_react_agent

from ingestion import (
    ingest_pdf, list_ingested_papers, query_papers,
    delete_paper, get_full_text_for_paper, get_topic_coverage
)
from tools import export_summary_to_google_doc

load_dotenv()

st.set_page_config(
    page_title="ResearchCollab",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ── Cached heavy objects — created ONCE per app session, never reloaded ────────
@st.cache_resource
def get_llm():
    return ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        temperature=0,
        google_api_key=os.getenv("GOOGLE_API_KEY")
    )


@st.cache_resource
def get_agent():
    system_prompt = """
    You are an expert AI research assistant for a collaborative team.
    Summarize research papers, answer questions across uploaded literature,
    and export findings to Google Docs.
    Always cite the source paper when referencing specific claims.
    When you export to Google Docs, always give the user the clickable link.
    """
    return create_react_agent(get_llm(), [export_summary_to_google_doc], prompt=system_prompt)


def stream_llm(prompt: str):
    """Stream LLM response token by token — user sees output immediately."""
    llm = get_llm()
    return st.write_stream(
        chunk.content for chunk in llm.stream([HumanMessage(content=prompt)])
    )


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🔬 ResearchCollab")
    st.caption("AI-Powered Team Research Workspace")
    st.divider()
    username = st.text_input("👤 Your name", value="researcher_1")
    st.divider()
    page = st.radio(
        "Navigate",
        ["📤 Upload & Ingest", "📚 Paper Library", "🗺️ Topic Tracker",
         "📝 Summarize & Export", "💬 Team Q&A"],
        label_visibility="collapsed"
    )


# ══════════════════════════════════════════════════════════════════════════════
# MODULE 1 — Upload & Ingest
# ══════════════════════════════════════════════════════════════════════════════
if page == "📤 Upload & Ingest":
    st.title("📤 Upload Research Papers")
    st.markdown(
        "Upload PDFs to the shared knowledge base. "
        "Gemini will **automatically tag each paper with research subtopics** it covers."
    )

    uploaded_files = st.file_uploader(
        "Drop PDF files here", type=["pdf"], accept_multiple_files=True
    )

    if uploaded_files:
        if st.button(f"⚡ Ingest {len(uploaded_files)} paper(s)", type="primary"):
            progress = st.progress(0, text="Starting...")
            results  = []

            for i, f in enumerate(uploaded_files):
                progress.progress(i / len(uploaded_files),
                                  text=f"Processing: {f.name} (extracting subtopics via Gemini)...")
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                    tmp.write(f.read())
                    tmp_path = tmp.name
                try:
                    result = ingest_pdf(tmp_path, uploaded_by=username)
                    results.append(result)
                except Exception as e:
                    results.append({"status": "error", "reason": str(e),
                                    "file_name": f.name, "chunks": 0})
                finally:
                    os.unlink(tmp_path)

            progress.progress(1.0, text="Done!")
            progress.empty()

            for r in results:
                if r["status"] == "success":
                    topics_str = " · ".join(f"`{t}`" for t in r.get("subtopics", []))
                    st.success(
                        f"✅ **{r['file_name']}** — "
                        f"{r['chunks']} chunks | {r['num_pages']} pages\n\n"
                        f"**Subtopics detected:** {topics_str}"
                    )
                elif r["status"] == "skipped":
                    st.warning(f"⚠️ **{r['file_name']}** — Already in database (skipped)")
                else:
                    st.error(f"❌ **{r['file_name']}** — {r['reason']}")


# ══════════════════════════════════════════════════════════════════════════════
# MODULE 2 — Paper Library
# ══════════════════════════════════════════════════════════════════════════════
elif page == "📚 Paper Library":
    st.title("📚 Paper Library")
    st.markdown("All papers in the shared knowledge base with their subtopic tags.")

    papers = list_ingested_papers()
    if not papers:
        st.info("No papers yet. Go to **Upload & Ingest** to add some.")
    else:
        st.metric("Total Papers", len(papers))
        st.divider()

        for paper in papers:
            with st.expander(f"📄 {paper['title'] or paper['file_name']}"):
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown(f"**File:** `{paper['file_name']}`")
                    st.markdown(f"**Author:** {paper['author']}")
                    st.markdown(f"**Pages:** {paper['num_pages']}")
                with col2:
                    st.markdown(f"**Uploaded by:** `{paper['uploaded_by']}`")
                    st.markdown(f"**Uploaded at:** {paper['uploaded_at'][:19].replace('T', ' ')}")

                # Subtopic tags
                subtopics = [t for t in paper.get("subtopics", []) if t.strip()]
                if subtopics:
                    st.markdown("**Subtopics:** " + "  ".join(f"`{t}`" for t in subtopics))

                if st.button("🗑️ Remove from DB", key=f"del_{paper['doc_hash']}"):
                    n = delete_paper(paper["doc_hash"])
                    st.success(f"Removed {n} chunks for '{paper['file_name']}'")
                    st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# MODULE 3 — Topic Tracker
# ══════════════════════════════════════════════════════════════════════════════
elif page == "🗺️ Topic Tracker":
    st.title("🗺️ Research Topic Tracker")
    st.markdown(
        "See which subtopics are **covered** by uploaded papers "
        "and identify **gaps** your team still needs to research."
    )

    papers   = list_ingested_papers()
    coverage = get_topic_coverage()

    if not papers:
        st.info("No papers yet. Upload some to start tracking topics.")
    else:
        col1, col2 = st.columns(2)
        col1.metric("Papers uploaded", len(papers))
        col2.metric("Subtopics identified", len(coverage))
        st.divider()

        # ── Covered topics ─────────────────────────────────────────────────
        st.subheader("✅ Topics Covered")
        st.caption("Each tag shows how many papers cover that subtopic.")

        for topic, covering_papers in sorted(coverage.items(), key=lambda x: -len(x[1])):
            with st.expander(f"**{topic}** — {len(covering_papers)} paper(s)"):
                for p in covering_papers:
                    st.markdown(f"- {p}")

        st.divider()

        # ── Gap detector ───────────────────────────────────────────────────
        st.subheader("🔍 Find Research Gaps")
        st.markdown(
            "Describe your overall research goal and Gemini will identify "
            "subtopics you're likely **missing** from your current paper set."
        )

        research_goal = st.text_area(
            "What is your team researching?",
            placeholder="e.g. We are building an AI system for collaborative literature review using RAG and LLMs.",
            height=100
        )

        if st.button("🤖 Identify Gaps", type="primary") and research_goal.strip():
            with st.spinner("Analysing coverage gaps..."):
                covered_list = "\n".join(f"- {t}" for t in coverage.keys())

                gap_prompt = f"""
                A research team is working on the following goal:
                "{research_goal}"

                They have already uploaded papers covering these subtopics:
                {covered_list if covered_list else "None yet."}

                Based on the research goal, what important subtopics or research areas are they MISSING?
                List 4-8 specific gaps with a one-line explanation of why each is important.
                Format as a markdown list.
                """
                st.markdown("### 🚨 Identified Gaps")
                stream_llm(gap_prompt)


# ══════════════════════════════════════════════════════════════════════════════
# MODULE 4 — Summarize & Export
# ══════════════════════════════════════════════════════════════════════════════
elif page == "📝 Summarize & Export":
    st.title("📝 Summarize & Export to Google Docs")
    st.markdown(
        "Select a paper. The agent will write a structured summary "
        "and export an editable copy to your Google Drive."
    )

    papers = list_ingested_papers()
    if not papers:
        st.info("No papers in database yet. Upload some first.")
    else:
        paper_options = {
            f"{p['title'] or p['file_name']} (by {p['author']})": p
            for p in papers
        }
        selected_label = st.selectbox("Choose a paper", list(paper_options.keys()))
        selected_paper = paper_options[selected_label]

        # Show subtopics of selected paper
        subtopics = [t for t in selected_paper.get("subtopics", []) if t.strip()]
        if subtopics:
            st.markdown("**Subtopics:** " + "  ".join(f"`{t}`" for t in subtopics))

        col1, col2 = st.columns(2)
        with col1:
            export_to_drive = st.checkbox("📤 Export to Google Docs", value=True)
        with col2:
            doc_title = st.text_input(
                "Google Doc title",
                value=f"{selected_paper['file_name']} — Summary"
            )

        if st.button("🤖 Summarize Now", type="primary"):
            with st.spinner("Reading paper..."):
                full_text = get_full_text_for_paper(selected_paper["doc_hash"])

            if not full_text:
                st.error("Could not retrieve paper text from database.")
            else:
                export_instruction = (
                    f"After writing the summary, MUST use 'export_summary_to_google_doc' "
                    f"tool with title='{doc_title}'. Then provide the clickable link."
                    if export_to_drive else
                    "Do NOT export to Google Docs."
                )
                prompt = f"""
                Summarize this research paper for a team starting a new project.
                Structure the summary with:
                1. Problem being solved
                2. Key methods / approach
                3. Main findings / results
                4. Limitations
                5. Relevance to the team

                Be clear but keep technical details.

                Paper text:
                {full_text[:12000]}

                {export_instruction}
                """
                st.markdown("### 📋 Summary")
                if export_to_drive:
                    # Need agent for tool use — can't stream here
                    with st.spinner("Generating summary and exporting to Drive..."):
                        agent    = get_agent()
                        response = agent.invoke({"messages": [HumanMessage(content=prompt)]})
                        st.markdown(response["messages"][-1].content)
                else:
                    # No tool use needed — stream directly
                    stream_llm(prompt)


# ══════════════════════════════════════════════════════════════════════════════
# MODULE 5 — Team Q&A
# ══════════════════════════════════════════════════════════════════════════════
elif page == "💬 Team Q&A":
    st.title("💬 Team Q&A — Ask Across All Papers")
    st.markdown(
        "Ask any question. The agent searches the knowledge base "
        "and answers with citations from the relevant papers."
    )

    if "qa_history" not in st.session_state:
        st.session_state.qa_history = [
            AIMessage(content=(
                "Hi! Ask me anything about your uploaded papers. "
                "Try: *'What datasets are commonly used?'* or *'What methods are used for X?'*"
            ))
        ]

    for msg in st.session_state.qa_history:
        role = "assistant" if isinstance(msg, AIMessage) else "user"
        with st.chat_message(role):
            st.markdown(msg.content)

    user_query = st.chat_input("Ask something about your papers...")

    if user_query:
        st.session_state.qa_history.append(HumanMessage(content=user_query))
        with st.chat_message("user"):
            st.markdown(user_query)

        with st.chat_message("assistant"):
            with st.spinner("Searching papers..."):
                hits = query_papers(user_query, n_results=5)

                if not hits:
                    answer = "No relevant content found. Upload some PDFs first."
                    st.markdown(answer)
                    st.session_state.qa_history.append(AIMessage(content=answer))
                else:
                    context_parts = [
                        f"[Source {i+1}: {h['title'] or h['file_name']}]\n{h['chunk']}"
                        for i, h in enumerate(hits)
                    ]
                    context = "\n\n---\n\n".join(context_parts)

                    rag_prompt = f"""
                    Answer using ONLY the context below.
                    Cite sources as [Source N: Paper Title].
                    If the context doesn't contain the answer, say so.

                    Context:
                    {context}

                    Question: {user_query}
                    """
                    # Stream directly — no tool use needed for Q&A
                    with st.chat_message("assistant"):
                        answer = stream_llm(rag_prompt)

                    with st.expander("📎 Sources used"):
                        for i, hit in enumerate(hits):
                            st.markdown(
                                f"**[{i+1}] {hit['title'] or hit['file_name']}** "
                                f"— chunk {hit['chunk_idx']} | score: {hit['score']}"
                            )
                            st.caption(hit["chunk"][:300] + "...")

                    st.session_state.qa_history.append(AIMessage(content=answer))

    if st.button("🗑️ Clear chat"):
        st.session_state.qa_history = [
            AIMessage(content="Chat cleared! Ask me anything about your papers.")
        ]
        st.rerun()
