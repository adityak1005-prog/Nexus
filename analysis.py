"""
analysis.py — AI functions (Gemini 2.5 Flash + optional Tavily web search)

[INCLUSIVITY] Every public function accepts a `user_context` dict with:
  - language      : ISO-639-1 code ("en", "ar", "hi", "zh", "fr", "de", "es", "ja")
  - role          : "student" | "supervisor"
  - expertise     : "beginner" | "intermediate" | "advanced"
  - personal_statement : user's individual research focus
  - username      : display name for personalisation

All AI outputs are produced in the requested language.
Depth and vocabulary are adapted to the user's expertise level and role.
"""

import os, re
from dataclasses import dataclass, field
from typing import Optional
from dotenv import load_dotenv

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage

load_dotenv()

# ── Language display names (for prompt instructions) ───────────────────────────
LANGUAGE_NAMES = {
    "en": "English",
    "ar": "Arabic (العربية)",
    "hi": "Hindi (हिंदी)",
    "zh": "Simplified Chinese (简体中文)",
    "fr": "French (Français)",
    "de": "German (Deutsch)",
    "es": "Spanish (Español)",
    "ja": "Japanese (日本語)",
    "pt": "Portuguese (Português)",
    "ko": "Korean (한국어)",
    "ru": "Russian (Русский)",
    "it": "Italian (Italiano)",
}

# ── User context dataclass ──────────────────────────────────────────────────────
@dataclass
class UserContext:
    """
    Structured representation of the requesting user.
    Passed to every AI function so prompts are personalised, inclusive,
    and produced in the user's preferred language.
    """
    language:           str  = "en"          # ISO-639-1 output language
    role:               str  = "student"     # "student" | "supervisor"
    expertise:          str  = "intermediate"# "beginner" | "intermediate" | "advanced"
    personal_statement: str  = ""            # individual research focus
    username:           str  = "researcher"

    @classmethod
    def from_dict(cls, d: dict) -> "UserContext":
        """Build from a plain dict (e.g., from a FastAPI request body)."""
        if d is None:
            return cls()
        return cls(
            language           = d.get("language", "en"),
            role               = d.get("role", "student"),
            expertise          = d.get("expertise", "intermediate"),
            personal_statement = d.get("personal_statement", ""),
            username           = d.get("username", "researcher"),
        )

    def lang_name(self) -> str:
        return LANGUAGE_NAMES.get(self.language, "English")

    def language_instruction(self) -> str:
        """
        Appended to EVERY prompt so the model always responds in the
        user's language and at the right depth.
        """
        expertise_desc = {
            "beginner":     "Avoid jargon. Use simple analogies and plain language.",
            "intermediate": "Assume undergraduate-level knowledge. Balance clarity with technical accuracy.",
            "advanced":     "Assume PhD-level expertise. Use precise technical terminology and nuanced analysis.",
        }.get(self.expertise, "Assume undergraduate-level knowledge.")

        role_desc = {
            "student":    "The reader is a student. Be encouraging, instructive, and pedagogically clear.",
            "supervisor": "The reader is a research supervisor or PI. Be concise, critical, and highlight methodological rigour.",
        }.get(self.role, "The reader is a student.")

        personal = f"\nThe user's personal research focus: {self.personal_statement}" if self.personal_statement else ""

        return (
            f"\n\n---\n"
            f"LANGUAGE INSTRUCTION: You MUST write your ENTIRE response in {self.lang_name()}. "
            f"All headings, bullets, and text must be in {self.lang_name()}. "
            f"Do NOT use English unless the user's language IS English.\n"
            f"AUDIENCE: {role_desc}\n"
            f"DEPTH: {expertise_desc}"
            f"{personal}"
        )


# ── Default context for backward-compatibility ────────────────────────────────
DEFAULT_CTX = UserContext()


# ── LLM singleton ──────────────────────────────────────────────────────────────
_llm = None
_llm_key = None

def get_llm():
    global _llm, _llm_key
    current_key = os.getenv("GOOGLE_API_KEY", "")
    if not current_key:
        raise RuntimeError("GOOGLE_API_KEY is not set. Check your .env file.")
    if _llm is None or _llm_key != current_key:
        _llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            temperature=0,
            google_api_key=current_key,
        )
        _llm_key = current_key
    return _llm

def call_llm(prompt: str) -> str:
    try:
        return get_llm().invoke([HumanMessage(content=prompt)]).content
    except Exception as e:
        err = str(e)
        if "API_KEY_INVALID" in err or "api key not valid" in err.lower():
            raise RuntimeError(f"Invalid Google API key — check your .env file. Detail: {err}")
        raise RuntimeError(f"Gemini API error: {err}")


# ── Tavily (web search) ────────────────────────────────────────────────────────
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


# ── Core analysis functions (all multilingual + user-context-aware) ────────────

def summarize_paper(
    title: str,
    full_text: str,
    problem_statement: str,
    personal_statement: str = "",
    ctx: UserContext = DEFAULT_CTX,
) -> str:
    """
    [MULTILINGUAL] Summarise a paper in the user's language, adapted to
    their role (student/supervisor) and expertise level.
    """
    # Merge personal statement from user context if not explicitly passed
    ps = personal_statement or ctx.personal_statement
    ctx_line = f"\nResearcher focus: {ps}" if ps else ""

    return call_llm(f"""You are an expert research analyst. Analyse this paper for a research team member.

Team problem statement: {problem_statement}{ctx_line}
Paper title: {title}
Paper text (first 10,000 chars): {full_text[:10000]}

Provide a structured analysis with the following sections:

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
One sentence justification.
{ctx.language_instruction()}""")


def check_reliability(
    title: str,
    text: str,
    ctx: UserContext = DEFAULT_CTX,
) -> str:
    """
    [MULTILINGUAL] Assess a paper's credibility in the user's language.
    """
    return call_llm(f"""You are a research credibility analyst.

Paper title: {title}
Content: {text[:1200]}

## 🌐 Publication Venue
Is this from a known conference or journal?

## ✅ Methodology Assessment
Any methodological concerns visible from the content?

## 🔍 Reliability Verdict
Rating: High / Medium / Low — with 2-sentence justification.
{ctx.language_instruction()}""")


def compare_papers(
    papers: list[dict],
    problem_statement: str,
    ctx: UserContext = DEFAULT_CTX,
) -> str:
    """
    [MULTILINGUAL] Compare multiple papers in the user's language and role context.
    Supervisors get a more critical methodological lens; students get pedagogical framing.
    """
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
How should the team use these papers together?
{ctx.language_instruction()}""")


def detect_gaps(
    problem_statement: str,
    covered_topics: list[str],
    summaries: list[str],
    ctx: UserContext = DEFAULT_CTX,
) -> str:
    """
    [MULTILINGUAL] Identify research gaps. For supervisors, include critical
    assessment of methodological coverage; for students, frame as learning opportunities.
    """
    topics = "\n".join(f"- {t}" for t in covered_topics) or "None yet."
    sums   = "\n\n---\n\n".join(summaries[:5]) if summaries else "No papers yet."

    role_lens = (
        "Critically assess methodological rigour, publication recency, and citation breadth."
        if ctx.role == "supervisor"
        else "Frame gaps as concrete next steps the student can take to strengthen their literature review."
    )

    return call_llm(f"""You are a senior research advisor identifying gaps in a literature review.

Team problem statement: "{problem_statement}"
{role_lens}

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
Priority order for the team given current coverage.
{ctx.language_instruction()}""")


def answer_with_rag(
    query: str,
    hits: list[dict],
    problem_statement: str,
    ctx: UserContext = DEFAULT_CTX,
) -> str:
    """
    [MULTILINGUAL] Answer a RAG query. Response language, depth, and framing
    are adapted to the user's language, role, and expertise.
    """
    if not hits:
        return call_llm(f"""You are a research assistant for a team working on: "{problem_statement}"

The team has not uploaded any papers yet. Answer the following question using your general knowledge,
clearly noting that this is general knowledge and not from the team's uploaded papers.

Question: {query}
{ctx.language_instruction()}""")

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

Question: {query}
{ctx.language_instruction()}""")


def answer_with_agent(
    query: str,
    hits: list[dict],
    problem_statement: str,
    ctx: UserContext = DEFAULT_CTX,
) -> tuple[str, list[str]]:
    """
    [MULTILINGUAL] Agent-mode answer with optional Tavily web search.
    All responses honour the user's language and role context.
    """
    tools = get_agent_tools()
    if not tools:
        return answer_with_rag(query, hits, problem_statement, ctx), []

    from langgraph.prebuilt import create_react_agent

    rag_context = "\n\n---\n\n".join(
        f"[Uploaded Paper {i+1}: {h['title'] or h['file_name']}]\n{h['chunk']}"
        for i, h in enumerate(hits)
    ) if hits else "No papers uploaded yet."

    lang_instruction = ctx.language_instruction()

    system = f"""You are Nexus AI, a research assistant for a team working on:
"{problem_statement}"

You have two knowledge sources:
1. Team's uploaded papers (in the prompt)
2. Web search via Tavily (for new papers, definitions, recent work)

Always cite uploaded papers as [Paper N: Title] and web sources as [Web: URL/title].
{lang_instruction}"""

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
        return answer_with_rag(query, hits, problem_statement, ctx) + f"\n\n_(Web search unavailable: {e})_", []


# ── Diagram generation ─────────────────────────────────────────────────────────

def generate_mermaid_diagram(
    title: str,
    text: str,
    diagram_type: str = "flowchart",
    ctx: UserContext = DEFAULT_CTX,
) -> str:
    """
    Generate Mermaid diagram syntax. Node labels honour the user's language
    so non-English teams see their terminology.
    """
    type_instructions = {
        "flowchart": """Create a Mermaid flowchart (use 'flowchart TD') showing the methodology or pipeline.
Use nodes for steps/components and arrows for data/process flow. Max 12 nodes.""",

        "mindmap": """Create a Mermaid mindmap showing the key concepts and their relationships.
Start with: mindmap
  root((Paper Title))
    Branch1
      Leaf1
    Branch2
Max depth 3, max 15 nodes.""",

        "timeline": """Create a Mermaid timeline diagram showing chronological development or experimental stages.
Use format:
timeline
  title Research Timeline
  Section1 : Event1 : Event2
  Section2 : Event3""",

        "concept": """Create a Mermaid flowchart (use 'flowchart LR') showing how key concepts relate.
Use rounded boxes for concepts, arrows labeled with relationships. Max 10 nodes.""",
    }

    instructions = type_instructions.get(diagram_type, type_instructions["flowchart"])
    lang_note = (
        f"\nIMPORTANT: Write all node labels and text in {ctx.lang_name()}."
        if ctx.language != "en" else ""
    )

    result = call_llm(f"""You are an expert at creating Mermaid diagrams from academic papers.

{instructions}

Paper title: {title}
Content: {text[:3500]}
{lang_note}

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

def generate_research_report(
    papers: list[dict],
    problem_statement: str,
    ctx: UserContext = DEFAULT_CTX,
) -> str:
    """
    [MULTILINGUAL] Generate a full synthesis report. Supervisors receive
    a journal-style critical synthesis; students receive a guided survey.
    """
    summaries = "\n\n---\n\n".join(
        f"### {p.get('title', p.get('file_name', 'Untitled'))}\n{p.get('summary', 'No summary yet.')}"
        for p in papers[:8]
    )

    style_note = (
        "Write as a formal academic synthesis suitable for a research supervisor to review."
        if ctx.role == "supervisor"
        else "Write as an accessible survey that helps a student understand the state of the field."
    )

    return call_llm(f"""You are a senior research analyst. Generate a comprehensive research report.

Team Problem Statement: {problem_statement}
{style_note}

Paper Summaries:
{summaries}

Generate a formal research synthesis report with these sections:

# Research Synthesis Report

## Executive Summary
2-3 paragraphs summarising the state of the field.

## Methodology Landscape
What methods dominate? What's emerging?

## Key Findings Across Papers
Synthesised insights, not paper-by-paper.

## Contradictions & Open Questions
Where does the field disagree?

## Recommendations
What should this team focus on next?

## Conclusion
Brief closing paragraph.
{ctx.language_instruction()}""")


# ── Concept deconstructor (scaffolded learning) ───────────────────────────────

def deconstruct_concept(
    concept: str,
    ctx: UserContext = DEFAULT_CTX,
) -> dict:
    """
    [INCLUSIVITY — RUBRIC B-A]
    Break a dense equation or concept into 3 scaffolded modules:
      level1 — Plain-language intuition
      level2 — Technical breakdown
      level3 — Advanced implications
      analogy — Real-world analogy

    All modules produced in the user's language at their expertise level.
    """
    expertise_map = {
        "beginner":     "a curious high-school student with no domain knowledge",
        "intermediate": "an undergraduate student who knows basic calculus and linear algebra",
        "advanced":     "a PhD student who wants edge cases and implementation nuances",
    }
    audience = expertise_map.get(ctx.expertise, expertise_map["intermediate"])

    raw = call_llm(f"""You are an expert pedagogy specialist and research communicator.

Deconstruct this concept into 3 scaffolded learning modules for {audience}.
Concept/Equation: {concept}

Respond with a JSON object ONLY — no markdown fences, no extra text:
{{
  "level1": "## Intuition\\n[2-3 paragraph plain-language explanation with no jargon]",
  "level2": "## Technical Breakdown\\n[Detailed explanation with notation, components, step-by-step derivation]",
  "level3": "## Advanced Implications\\n[Edge cases, limitations, why it matters, connections to related fields]",
  "analogy": "[1-2 paragraph real-world analogy that makes this concept click intuitively]"
}}
{ctx.language_instruction()}""")

    import json as _json
    try:
        cleaned = raw.strip().replace("```json", "").replace("```", "").strip()
        match = re.search(r'\{[\s\S]*\}', cleaned)
        if match:
            return _json.loads(match.group(0))
    except Exception:
        pass

    # Graceful fallback — return the raw text structured as level1
    return {
        "level1": raw[:1500],
        "level2": raw[1500:3000] if len(raw) > 1500 else "",
        "level3": raw[3000:] if len(raw) > 3000 else "",
        "analogy": ""
    }


# ── AI feedback summarisation ─────────────────────────────────────────────────

def summarise_feedback_batch(
    feedbacks: list[dict],
    content_type: str,
    ctx: UserContext = DEFAULT_CTX,
) -> str:
    """
    [FEEDBACK LOOP] Synthesise a batch of user feedback entries into
    actionable insights for the research team or platform administrators.
    Produced in the requesting user's language.
    """
    if not feedbacks:
        return "No feedback data available to summarise."

    entries = "\n".join(
        f"- [{f.get('content_type','?')}] Rating: {f.get('rating',0)}/5 | "
        f"Helpful: {f.get('helpful',False)} | "
        f"User: {f.get('username','anon')} | "
        f"Comment: {f.get('comment','') or '(none)'}"
        for f in feedbacks[:50]
    )

    avg_rating = (
        sum(f.get('rating', 0) for f in feedbacks if f.get('rating'))
        / max(1, sum(1 for f in feedbacks if f.get('rating')))
    )

    return call_llm(f"""You are a product quality analyst reviewing user feedback on AI-generated research content.

Content type being reviewed: {content_type}
Total feedback entries: {len(feedbacks)}
Average rating: {avg_rating:.1f}/5

Raw feedback entries:
{entries}

Provide a brief synthesis:

## Overall Quality Signal
1-2 sentences on the general reception.

## What's Working
Specific things users found valuable.

## What Needs Improvement
Recurring complaints or suggestions.

## Recommended Actions
2-3 concrete steps to improve this content type.
{ctx.language_instruction()}""")
