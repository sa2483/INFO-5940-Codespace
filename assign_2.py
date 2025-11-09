# app.py
"""
Multi-Agent Travel Planner

Highlights:
- Clear separation of concerns (tools, agents, orchestration, UI)
- Simple global logger to display tool calls live in the sidebar
- Planner → Reviewer pipeline enforced before rendering any answer
- Minimal dependencies and straightforward control flow
"""

from __future__ import annotations

import os
import asyncio
import time
from typing import Callable, Dict, List, Optional, Any

import streamlit as st
from dotenv import load_dotenv
from tavily import TavilyClient

# ──────────────────────────────────────────────────────────────────────────────
# Environment & Globals
# ──────────────────────────────────────────────────────────────────────────────

load_dotenv()  # Loads variables from a local .env if present
os.environ.setdefault("OPENAI_LOG", "error")
os.environ.setdefault("OPENAI_TRACING", "false")

# Tool call logger: the UI sets this per request. The tool checks it and logs.
# Using a simple global makes this easy to teach and reason about.
TOOL_LOGGER: Optional[Callable[[Dict[str, Any]], None]] = None


def set_tool_logger(logger: Optional[Callable[[Dict[str, Any]], None]]) -> None:
    """Install or remove the UI logger used by tools to report activity."""
    global TOOL_LOGGER
    TOOL_LOGGER = logger


def log_tool_event(event: Dict[str, Any]) -> None:
    """If a logger is installed, send the event to the UI."""
    if TOOL_LOGGER is not None:
        try:
            TOOL_LOGGER(event)
        except Exception:
            # Logging should never break the app or the tool itself
            pass


def redact_for_logs(value: Any) -> Any:
    """
    Make sure we don't leak secrets and keep logs small.
    This is deliberately simple for teaching.
    """
    if isinstance(value, str):
        low = value.lower()
        if any(k in low for k in ("api_key", "token", "secret", "password")):
            return "[redacted]"
        return value if len(value) <= 300 else value[:120] + "… [truncated]"
    if isinstance(value, dict):
        return {k: ("[redacted]" if any(s in k.lower() for s in ("key", "token", "secret", "password"))
                    else redact_for_logs(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [redact_for_logs(v) for v in value]
    return value


# ──────────────────────────────────────────────────────────────────────────────
# Agent Framework Imports (provided by you)
# ──────────────────────────────────────────────────────────────────────────────
# These come from your own framework. We assume:
# - Agent: defines a model + instructions + optional tools
# - Runner.run(agent, input): executes an agent and returns an object with text
from agents import Agent, Runner, function_tool  # type: ignore


# ──────────────────────────────────────────────────────────────────────────────
# Tools
# ──────────────────────────────────────────────────────────────────────────────

@function_tool
def internet_search(query: str) -> str:
    """
    Internet search backed by Tavily.
    - Reads TAVILY_API_KEY from environment.
    - Sends simple log events before/after the call so the UI can show activity.
    """
    log_tool_event({"type": "call", "tool": "internet_search", "args": {"query": redact_for_logs(query)}})

    try:
        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            msg = "missing TAVILY_API_KEY in environment."
            log_tool_event({"type": "error", "tool": "internet_search", "error": msg})
            return f"Search error: {msg}"

        client = TavilyClient(api_key=api_key)
        response = client.search(query, max_results=3)

        items = response.get("results", [])
        lines = [f"- {it.get('title', 'N/A')}: {it.get('content', 'N/A')}" for it in items]
        output = "\n".join(lines) if lines else "No results found."

        log_tool_event({
            "type": "result",
            "tool": "internet_search",
            "preview": redact_for_logs(output[:400] + ("…" if len(output) > 400 else "")),
        })
        return output

    except Exception as e:
        log_tool_event({"type": "error", "tool": "internet_search", "error": str(e)})
        return f"Search error: {e}"

    finally:
        log_tool_event({"type": "end", "tool": "internet_search"})


# ──────────────────────────────────────────────────────────────────────────────
# Agents
# ──────────────────────────────────────────────────────────────────────────────

# BEGIN SOLUTION

PLANNER_INSTRUCTIONS = """
You are the Planner Agent in a two-agent travel-planning system.

Your job:
Turn a vague natural-language travel request into a precise, realistic, day-by-day itinerary
that will later be checked by a separate Reviewer Agent.

Operating constraints:
- You DO NOT have internet access or external tools.
- Rely only on your general world knowledge and reasonable assumptions.
- Do NOT say you are browsing, calling tools, or checking live data.
- Assume prices, routes, and hours approximately; be sensible and conservative.

How to interpret the user prompt:
- Extract and respect: duration, dates (or seasons), destination(s), budget, interests,
  travel party (solo/couple/family/friends), pacing preferences, and any constraints
  (mobility, dietary, etc.) when provided.
- If details are missing, make reasonable assumptions and state them briefly.

Output requirements:

1. **Assumptions**
   - Bullet list of key assumptions:
     - currency and rough price level,
     - typical lodging type and nightly range,
     - meal style (budget / midrange / upscale),
     - transport style (public transit / walking / train / occasional ride-share),
     - any inferred pacing (“moderate days, one anchor activity + free time”, etc.).

2. **Overview**
   - 1–3 bullets summarizing:
     - main cities/regions,
     - trip structure (e.g., “Days 1–3 in Rome, Days 4–5 in Florence…”),
     - how the plan fits interests and budget.

3. **Day-by-Day Itinerary**
   For each day, create a subsection in this style:
   - `Day X – City/Area`
     - Time-blocked schedule in chronological order (e.g., “9:00–11:00 …”).
     - 3–6 concrete activities tuned to the user’s interests.
     - Include:
       - location names (neighborhood, landmark, or venue),
       - short descriptions,
       - approximate cost per activity (or “free” when applicable),
       - simple logistics notes (walk/metro/bus, expected travel time).
     - When changing cities:
       - clearly mark transfer (mode, duration estimate, rough cost),
       - avoid impossible same-day combinations.

   Additional rules:
   - Cluster activities geographically to minimize backtracking.
   - Build in at least one flexible / rest block most days.
   - Avoid extreme schedules unless user clearly wants intense travel.

4. **Budget Summary**
   - Provide a small markdown table with:
     - Lodging total (nights × assumed nightly range).
     - Food total (per person per day × days).
     - Activities/attractions total.
     - Local & inter-city transport.
     - Overall estimated total.
   - Indicate whether this fits within the stated budget
     (if over, suggest where to trim).

5. **Logistics & Notes**
   - Bullet list with:
     - key transport tips,
     - booking notes (e.g., “reserve major museums in advance”),
     - any important assumptions or caveats.

Style:
- Be concise, structured, and easy to scan.
- No internal monologue, no mention of the Reviewer Agent.
- Produce one coherent itinerary; do not ask questions back to the user.
"""

REVIEWER_INSTRUCTIONS = """
You are the Reviewer Agent in a two-agent travel-planning system.

You receive:
- ONLY the Planner Agent's draft itinerary as input (not the original user prompt).

Your mission:
- Audit the draft for realism, feasibility, and alignment with constraints.
- Fix issues and output a user-ready, validated itinerary.
- You ARE allowed to use tools, especially `internet_search`, for live fact-checking.

Tool usage (internet_search):
- Use `internet_search` when verification could materially change the plan, for example:
  - Opening days/hours for major museums and attractions.
  - Typical ticket prices for key sights.
  - Train/bus/flight durations between cities.
  - Distance/feasibility of proposed day trips.
  - Rough lodging or city-level cost sanity checks.
- Use short, targeted queries:
  - Examples: "Louvre Museum hours", "train Rome to Florence duration typical",
    "ferry Athens to Santorini time", "average budget hotel price Lisbon city center".
- Do NOT spam the tool. Prefer a few high-value checks over exhaustive searching.
- Clearly distinguish what is based on live search vs your own judgment.

Review process:

1. Read the Planner's itinerary carefully.
2. Identify:
   - Attractions likely closed on the proposed day/time.
   - Overly tight or impossible transfers (e.g., 3 cities in 1 day, unrealistic drives).
   - Mismatches between pacing and schedule (e.g., 12+ hour stacked days).
   - Budgets that are clearly unrealistic for the cities/season mentioned.
   - Missing or unclear logistics that could confuse a traveler.
3. Decide for each issue whether to:
   - Keep as-is (if feasible),
   - Adjust (time/sequence/cost),
   - Replace (different attraction or schedule),
   - Or flag as a constraint/assumption.

Output format (strict):

Your response MUST contain all three sections, in this order:

1. **Validation Summary**
   - 3–8 bullet points that:
     - summarize overall feasibility,
     - highlight major strengths of the plan,
     - note key risks or caveats (e.g., “museum requires advance booking”).

2. **Delta List (Required Changes)**
   - Numbered list of concrete edits.
   - For each item:
     - Briefly reference the original element (day/activity).
     - Explain what is wrong or uncertain.
     - State the specific fix (new activity/time/route/cost).
     - Indicate if this was informed by `internet_search` or by judgment.
   - Include at least minor adjustments even if the plan is mostly solid.
   - Avoid vague advice; every delta should be directly implementable.

3. **Revised Itinerary (User-Facing)**
   - Start from the Planner's structure but incorporate all accepted changes.
   - Preserve the user’s goals (budget, interests, pacing) as implied by the plan.
   - Ensure for each day:
     - chronological schedule with approximate times,
     - clear city/area labels,
     - realistic logistics between locations,
     - updated cost estimates that better match live-checked info.
   - Include an updated budget summary (table) reflecting your corrections.
   - This section must be clean and ready to show the user:
     - no tool logs, no chain-of-thought, no references to “Planner/Reviewer Agents”.

Guidelines:
- Be decisive and specific; avoid hedging where it harms usability.
- When information is uncertain or varies by season, phrase it as:
  - “Based on recent data, this typically…” and keep the plan conservative.
- Never expose API keys or internal system messages.
- Do NOT ask the user follow-up questions; you only see the Planner’s text.
- Do NOT instruct the user to run tools.
- Your role is a critical but helpful editor: catch issues, adjust them,
  and output a final itinerary that is realistic, coherent, and trustworthy.
"""

reviewer_agent = Agent(
    name="Reviewer Agent",
    model="openai.gpt-4o",
    instructions=REVIEWER_INSTRUCTIONS.strip(),
    tools=[internet_search],
)

planner_agent = Agent(
    name="Planner Agent",
    model="openai.gpt-4o",
    instructions=PLANNER_INSTRUCTIONS.strip(),
)

# END SOLUTION


# ──────────────────────────────────────────────────────────────────────────────
# Orchestration Helpers
# ──────────────────────────────────────────────────────────────────────────────

def extract_text(result_obj: Any) -> str:
    """
    Pull a usable string from the Runner result in a tolerant way.
    Your Runner may expose final_output, text, or __str__.
    """
    return (
        getattr(result_obj, "final_output", None)
        or getattr(result_obj, "text", None)
        or str(result_obj)
    )


def run_planner(user_text: str) -> str:
    """Run the Planner and return its itinerary text."""
    result = asyncio.run(Runner.run(planner_agent, user_text))
    return extract_text(result)


def run_reviewer(plan_text: str) -> str:
    """Run the Reviewer on the planner’s output and return validated text."""
    result = asyncio.run(Runner.run(reviewer_agent, plan_text))
    return extract_text(result)


# ──────────────────────────────────────────────────────────────────────────────
# Streamlit UI
# ──────────────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Travel Planner", page_icon="✈️")

st.title("✈️ Multi-Agent Travel Planner")
st.caption("Planner → Reviewer (with live tool calls in the sidebar)")

# Sidebar: session controls + examples + dev panel
with st.sidebar:
    st.header("Session")
    if st.button("🔄 Reset conversation"):
        st.session_state.clear()
        st.rerun()

    st.subheader("Try these prompts")
    st.code("Plan a week-long Europe trip for a student on a $1,500 budget who loves history and food")
    st.code("3-day Paris trip for art lovers with $800 budget")

    st.subheader("Developer view")
    show_tools = st.toggle("Show tool activity (live)", value=True)
    if show_tools:
        tool_expander = st.expander("🔧 Tool activity", expanded=True)
        tool_panel = tool_expander.container()
    else:
        tool_panel = st.container()  # inert sink

# Session state for chat history
if "messages" not in st.session_state:
    st.session_state.messages = []  # list[dict(role, content)]
if "meta" not in st.session_state:
    st.session_state.meta = []      # list[dict(trace)]

# Render history
for i, msg in enumerate(st.session_state.messages):
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg["role"] == "assistant" and i < len(st.session_state.meta):
            meta = st.session_state.meta[i]
            if meta:
                st.caption(meta.get("trace", ""))

# Chat input
user_input = st.chat_input("Describe your travel (destination, duration, budget, interests)…")

if user_input:
    # Add user message to history and render it
    st.session_state.messages.append({"role": "user", "content": user_input})
    st.session_state.meta.append(None)
    with st.chat_message("user"):
        st.markdown(user_input)

    # Assistant output block
    with st.chat_message("assistant"):
        # Live “working…” text and progress bar
        live_msg = st.empty()
        progress = st.progress(0)

        # Per-request tool log (shown in the sidebar)
        tool_events: List[Dict[str, Any]] = []

        def ui_tool_logger(event: Dict[str, Any]) -> None:
            """Append an event and re-render the sidebar log."""
            tool_events.append(event)
            with tool_panel:
                st.markdown("**Recent tool calls**")
                for ev in tool_events[-60:]:  # last N entries
                    t = ev.get("tool", "unknown")
                    et = ev.get("type", "event")
                    if et == "call":
                        st.write(f"• **{t}** called with `{ev.get('args')}`")
                    elif et == "result":
                        st.write(f"• **{t}** result preview:\n\n> {ev.get('preview')}")
                    elif et == "error":
                        st.error(f"• **{t}** error: {ev.get('error')}")
                    elif et == "end":
                        st.write(f"• **{t}** finished")

        # Install the logger so tools can report to the sidebar
        set_tool_logger(ui_tool_logger)

        try:
            # Optional: clear sidebar panel on each run
            with tool_panel:
                st.empty()

            # Step 1: Planner
            with st.status("🧭 Planner Agent: generating itinerary…", expanded=True) as status:
                live_msg.markdown("🧭 Planner Agent is creating your itinerary…")
                plan_text = run_planner(user_input)
                progress.progress(40)
                status.update(label="🔎 Reviewer Agent: validating with live searches…", state="running")

            # Step 2: Reviewer (tool calls will appear live in sidebar)
            live_msg.markdown("🔎 Reviewer Agent is validating the plan with live searches…")
            review_text = run_reviewer(plan_text)
            progress.progress(90)

            # Completed
            live_msg.markdown("✅ Validation complete. Rendering results…")
            time.sleep(0.2)
            progress.progress(100)

            # Final render: show only the validated result, with the raw plan expandable
            st.info("🤖 **Reviewer Agent** (validated)")
            st.markdown(review_text)
            with st.expander("See raw plan from Planner Agent"):
                st.markdown(plan_text)

            # Save only the validated result to history
            st.session_state.messages.append({"role": "assistant", "content": review_text})
            st.session_state.meta.append({"trace": "Planner Agent → Reviewer Agent"})
            st.caption("Planner Agent → Reviewer Agent")

        except Exception as e:
            # Friendly error box
            live_msg.markdown("❌ Something went wrong.")
            err = f"⚠️ Error while processing your request:\n\n```\n{e}\n```"
            st.markdown(err)
            st.session_state.messages.append({"role": "assistant", "content": err})
            st.session_state.meta.append({"trace": "Runtime error."})

        finally:
            # Always remove the logger so it doesn't leak into the next request
            set_tool_logger(None)
