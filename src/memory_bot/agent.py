from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from pydantic_ai import Agent, RunContext

from memory_bot.models import Note
from memory_bot.store import Store


@dataclass
class AgentDeps:
    store: Store
    user_id: int
    now: str
    new_id: Callable[[], str]


SYSTEM_PROMPT = (
    "You are a personal memory assistant. When the user shares information, "
    "save it with save_note using a short lowercase category. When they ask a "
    "question, use list_notes or search_notes and answer concisely. Reuse an "
    "existing category when one fits rather than inventing a near-duplicate."
)


def build_agent(model: str) -> Agent:
    agent = Agent(model, deps_type=AgentDeps, system_prompt=SYSTEM_PROMPT)

    @agent.system_prompt
    def existing_categories(ctx: RunContext[AgentDeps]) -> str:
        cats = ctx.deps.store.distinct_categories(ctx.deps.user_id)
        if not cats:
            return "No categories exist yet."
        return "Existing categories: " + ", ".join(cats) + "."

    @agent.tool
    def save_note(ctx: RunContext[AgentDeps], text: str, category: str,
                  summary: str | None = None) -> str:
        status = "open" if category == "todo" else None
        note = Note(
            note_id=ctx.deps.new_id(), text=text, category=category,
            created_at=ctx.deps.now, summary=summary, status=status,
        )
        ctx.deps.store.put_note(ctx.deps.user_id, note)
        return f"Filed under '{category}'."

    @agent.tool
    def search_notes(ctx: RunContext[AgentDeps], query: str,
                     category: str | None = None) -> list[Note]:
        return ctx.deps.store.query_notes(ctx.deps.user_id, category=category)

    @agent.tool
    def list_notes(ctx: RunContext[AgentDeps], category: str | None = None,
                   status: str | None = None) -> list[Note]:
        return ctx.deps.store.query_notes(
            ctx.deps.user_id, category=category, status=status)

    return agent


def run_message(agent: Agent, deps: AgentDeps, text: str) -> str:
    result = agent.run_sync(text, deps=deps)
    return result.output
