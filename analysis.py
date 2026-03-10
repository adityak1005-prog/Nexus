"""
analysis.py — AI functions (Gemini 2.5 Flash + optional Tavily web search)
"""
import os, re
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage

# ── LLM ────────────────────────────────────────────────────────────────────────
_llm = None
def get_llm():
    global _llm
    if _llm is None:
        _llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            temperature=0,
            google_api_key=os.getenv("GOOGLE_API_KEY"),
        )
    return _llm

def call_llm(prompt: str) -> str:
    return get_llm().invoke([HumanMessage(content=prompt)]).content


# ── Tavily ─────────────────────────────────────────────────────────────────────
_tavily = None
def get_tavily_tool():
    global _tavily
    if _tavily is not None:
        return _tavily
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return None
    try:
        from langchain_tavily import TavilySearch
        _tavily = TavilySearch(max_results=5, topic="general", tavily_api_key=api_key)
        return _tavily
    except ImportError:
        try:
            from langchain_community.tools.tavily_search import TavilySearchResults
            os.environ["TAVILY_API_KEY"] = api_key
            _tavily = TavilySearchResults(max_results=5)
            return _tavily
        except ImportError:
            return None

def is_web_search_available() -> bool:
    return get_tavily_tool() is not None

def get_agent_tools():
    tools = []
    t = get_tavily_tool()
    if t:
        tools.append(t)
    return tools


# ── Core analysis ──────────────────────────────────────────────────────────────
def summarize_paper(title: str, full_text: str,
                    problem_statement: str, personal_statement: str = "") -> str:
    ctx = f"\nResearcher focus: {personal_statement}" if personal_statement else ""
    return call_llm(f"""You are an expert research analyst. Analyze this paper for a research team.

Team problem statement: {problem_statement}{ctx}
Paper title: {title}
Paper text (first 10,000 chars): {full_text[:10000]}

Provide a structured analysis:

## 📌 What This Paper Does
One paragraph — core problem it solves and approach.

## 🔬 Domains & Methods
Bullet list of research domains and key technical methods.

## 🏆 Key Results & Achievements
Bullet list of main findings and metrics.

## ⚠️ Limitations
Bullet list of scope limitations or weaknesses.

## 🔗 Relevance to Problem Statement
How this paper connects to the team's research problem.

## 🎯 Relevance Score: X/10
One sentence justification.""")


def check_reliability(title: str, text: str) -> str:
    return call_llm(f"""You are a research credibility analyst.

Paper title: {title}
Content: {text[:1200]}

## 🌐 Publication Venue
Is this from a known conference or journal?

## ✅ Methodology Assessment
Any methodological concerns visible from the content?

## 🔍 Reliability Verdict
Rating: High / Medium / Low — with 2-sentence justification.""")


def compare_papers(papers: list[dict], problem_statement: str) -> str:
    sections = "".join(
        f"\n\n=== PAPER {i+1}: {p['title']} ===\n{p['full_text'][:3000]}"
        for i, p in enumerate(papers)
    )
    return call_llm(f"""You are an expert research analyst. Compare these {len(papers)} papers.

Team problem statement: "{problem_statement}"
{sections}

## 🔄 Common Themes & Overlaps
What do these papers agree on or share?

## ⚔️ Contradictions & Disagreements
Where do they disagree and why does it matter?

## 🧩 Complementary Insights
How can they be combined to address the problem statement?

## 📊 Coverage Matrix
One line per paper: Paper title · Primary focus · Method · Key claim

## 💡 Synthesis Recommendation
How should the team use these papers together?""")


def detect_gaps(problem_statement: str, covered_topics: list[str],
                summaries: list[str]) -> str:
    topics = "\n".join(f"- {t}" for t in covered_topics) or "None yet."
    sums   = "\n\n---\n\n".join(summaries[:5]) if summaries else "No papers yet."
    return call_llm(f"""You are a senior research advisor identifying gaps in a literature review.

Team problem statement: "{problem_statement}"

Subtopics currently covered:
{topics}

Paper summaries:
{sums[:5000]}

## ✅ What's Well Covered
Topics adequately addressed.

## 🚨 Critical Gaps
Important subtopics MISSING. Explain why each gap matters.

## ⚔️ Contradictions Detected
Any inconsistencies found across papers.

## 📚 Recommended Papers to Find
4–6 specific paper types or search queries to fill the gaps.

## 🗺️ Suggested Research Roadmap
Priority order for the team given current coverage.""")


def answer_with_rag(query: str, hits: list[dict], problem_statement: str) -> str:
    if not hits:
        return call_llm(f"""You are a research assistant for a team working on: "{problem_statement}"

The team has not uploaded any papers yet. Answer the following question using your general knowledge,
clearly noting that this is general knowledge and not from team's uploaded papers.

Question: {query}""")

    context = "\n\n---\n\n".join(
        f"[Source {i+1}: {h['title'] or h['file_name']}]\n{h['chunk']}"
        for i, h in enumerate(hits)
    )
    return call_llm(f"""You are a research assistant for a team working on:
"{problem_statement}"

Answer using ONLY the context provided. Cite sources as [Source N: Title].
If the answer isn't in the context, say so clearly.

Context:
{context}

Question: {query}""")


def answer_with_agent(query: str, hits: list[dict],
                      problem_statement: str) -> tuple[str, list[str]]:
    tools = get_agent_tools()
    if not tools:
        return answer_with_rag(query, hits, problem_statement), []

    from langgraph.prebuilt import create_react_agent

    rag_context = "\n\n---\n\n".join(
        f"[Uploaded Paper {i+1}: {h['title'] or h['file_name']}]\n{h['chunk']}"
        for i, h in enumerate(hits)
    ) if hits else "No papers uploaded yet."

    system = f"""You are Nexus AI, a research assistant for a team working on:
"{problem_statement}"

You have two knowledge sources:
1. Team's uploaded papers (in the prompt)
2. Web search via Tavily (for new papers, definitions, recent work)

Always cite uploaded papers as [Paper N: Title] and web sources as [Web: URL/title]."""

    agent = create_react_agent(get_llm(), tools, prompt=system)
    full_prompt = f"""Uploaded paper context:
{rag_context}

Team question: {query}"""

    try:
        result = agent.invoke({"messages": [HumanMessage(content=full_prompt)]})
        final_msg = result["messages"][-1].content
        web_sources = []
        for msg in result["messages"]:
            content = str(getattr(msg, "content", ""))
            if "http" in content:
                urls = re.findall(r'https?://[^\s\]"]+', content)
                web_sources.extend(urls[:3])
        return final_msg, list(set(web_sources))
    except Exception as e:
        return answer_with_rag(query, hits, problem_statement) + f"\n\n_(Web search unavailable: {e})_", []


# ── Diagram generation ─────────────────────────────────────────────────────────
def generate_mermaid_diagram(title: str, text: str, diagram_type: str = "flowchart") -> str:
    """Generate Mermaid diagram syntax from paper content."""
    type_instructions = {
        "flowchart": """Create a Mermaid flowchart (use 'flowchart TD') showing the methodology or pipeline of this research.
Use nodes for steps/components and arrows for data/process flow. Max 12 nodes.""",

        "mindmap": """Create a Mermaid mindmap showing the key concepts and their relationships.
Start with: mindmap
  root((Paper Title))
    Branch1
      Leaf1
    Branch2
Max depth 3, max 15 nodes.""",

        "timeline": """Create a Mermaid timeline diagram showing the chronological development or experimental stages.
Use format:
timeline
  title Research Timeline
  Section1 : Event1 : Event2
  Section2 : Event3""",

        "concept": """Create a Mermaid flowchart (use 'flowchart LR') showing how key concepts relate to each other.
Use rounded boxes for concepts, arrows labeled with relationships. Max 10 nodes.""",
    }

    instructions = type_instructions.get(diagram_type, type_instructions["flowchart"])

    result = call_llm(f"""You are an expert at creating Mermaid diagrams from academic papers.

{instructions}

Paper title: {title}
Content: {text[:3500]}

RULES:
- Return ONLY valid Mermaid syntax, nothing else
- No markdown code fences (no ```)
- No explanation before or after the diagram
- Keep labels short (under 40 chars)
- Ensure it compiles without errors
- For flowchart/concept: use A[label], A-->B, A-->|label|B syntax
- For mindmap: use proper indentation

Start with the diagram type declaration on the first line.""")

    # Strip any accidental fences
    result = result.strip()
    for fence in ["```mermaid", "```"]:
        if result.startswith(fence):
            result = result[len(fence):]
    if result.endswith("```"):
        result = result[:-3]
    return result.strip()


# ── Research report ────────────────────────────────────────────────────────────
def generate_research_report(papers: list[dict], problem_statement: str) -> str:
    summaries = "\n\n---\n\n".join(
        f"### {p.get('title', p.get('file_name', 'Untitled'))}\n{p.get('summary', 'No summary yet.')}"
        for p in papers[:8]
    )
    return call_llm(f"""You are a senior research analyst. Generate a comprehensive research report.

Team Problem Statement: {problem_statement}

Paper Summaries:
{summaries}

Generate a formal research synthesis report with these sections:

# Research Synthesis Report

## Executive Summary
2-3 paragraphs summarizing the state of the field.

## Methodology Landscape
What methods dominate? What's emerging?

## Key Findings Across Papers
Synthesized insights, not paper-by-paper.

## Contradictions & Open Questions
Where does the field disagree?

## Recommendations
What should this team focus on next?

## Conclusion
Brief closing paragraph.""")