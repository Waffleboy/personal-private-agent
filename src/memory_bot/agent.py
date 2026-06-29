from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import ModelMessage, ModelRequest

from memory_bot.models import Note
from memory_bot.store import Store


@dataclass
class AgentDeps:
    store: Store
    user_id: int
    now: str
    new_id: Callable[[], str]


SYSTEM_PROMPT = (
    "You are a personal assistant. Your job is to help the user manage their "
    "information."
    "When the user shares information, first, see if it fits an existing "
    "category. If not, think about a new category then save it."
    "Save notes using save_note with a short lowercase category."
    "When they ask a question, use list_notes or search_notes and answer concisely."
    "Reuse an existing category when one fits rather than inventing a near-duplicate."
    "When the user gives a deadline (e.g. 'due tomorrow', 'by Friday'), resolve it "
    "relative to the current date below and in the user's timezone into an absolute "
    "ISO 8601 timestamp that includes the UTC offset, then pass it as save_note's "
    "due_at. If the user has no timezone set, ask them to set one with set_timezone "
    "before interpreting relative deadlines."
)


def _local_now(now_utc: str, tz: str | None) -> str:
    """Render the UTC `now` string in the user's timezone, with offset."""
    dt = datetime.strptime(now_utc, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=ZoneInfo("UTC")
    )
    if tz is None:
        return dt.isoformat()
    return dt.astimezone(ZoneInfo(tz)).isoformat()


def build_agent(model: str) -> Agent:
    agent = Agent(model, deps_type=AgentDeps, system_prompt=SYSTEM_PROMPT)

    @agent.system_prompt
    def current_datetime(ctx: RunContext[AgentDeps]) -> str:
        tz = ctx.deps.store.get_timezone(ctx.deps.user_id)
        local = _local_now(ctx.deps.now, tz)
        if tz is None:
            return (
                f"The current date and time is {local} (UTC). The user has not set "
                "a timezone."
            )
        return (
            f"The user's timezone is {tz}. The current local date and time is {local}."
        )

    @agent.system_prompt
    def existing_categories(ctx: RunContext[AgentDeps]) -> str:
        cats = ctx.deps.store.distinct_categories(ctx.deps.user_id)
        if not cats:
            return "No categories exist yet."
        return "Existing categories: " + ", ".join(cats) + "."

    @agent.tool
    def save_note(
        ctx: RunContext[AgentDeps],
        text: str,
        category: str,
        summary: str | None = None,
        due_at: str | None = None,
    ) -> str:
        status = "open" if category == "todo" else None
        note = Note(
            note_id=ctx.deps.new_id(),
            text=text,
            category=category,
            created_at=ctx.deps.now,
            summary=summary,
            status=status,
            due_at=due_at,
        )
        ctx.deps.store.put_note(ctx.deps.user_id, note)
        return f"Filed under '{category}'."

    @agent.tool
    def set_timezone(ctx: RunContext[AgentDeps], tz: str) -> str:
        """Set the user's timezone. `tz` must be an IANA name, e.g. Asia/Singapore."""
        try:
            ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError):
            return f"'{tz}' is not a valid IANA timezone."
        ctx.deps.store.set_timezone(ctx.deps.user_id, tz)
        return f"Timezone set to {tz}."

    @agent.tool
    def search_notes(
        ctx: RunContext[AgentDeps], query: str, category: str | None = None
    ) -> list[Note]:
        return ctx.deps.store.query_notes(ctx.deps.user_id, category=category)

    @agent.tool
    def list_notes(
        ctx: RunContext[AgentDeps],
        category: str | None = None,
        status: str | None = None,
    ) -> list[Note]:
        return ctx.deps.store.query_notes(
            ctx.deps.user_id, category=category, status=status
        )

    return agent


def _is_user_prompt(msg: ModelMessage) -> bool:
    return isinstance(msg, ModelRequest) and any(
        getattr(p, "part_kind", None) == "user-prompt" for p in msg.parts
    )


def trim_history(messages: list[ModelMessage], n: int) -> list[ModelMessage]:
    """Keep the last `n` user->bot exchanges, intact with their tool messages.

    An exchange begins at a ModelRequest carrying a user-prompt part. The
    returned slice always starts on such a boundary, never on a dangling
    tool-return. `n == 0` disables history.
    """
    if n <= 0:
        return []
    # Walk from the end; cut once we have passed `n` user-prompt boundaries.
    seen = 0
    cut = 0
    for i in range(len(messages) - 1, -1, -1):
        if _is_user_prompt(messages[i]):
            seen += 1
            if seen == n:
                cut = i
                break
    return messages[cut:]


def run_message(
    agent: Agent,
    deps: AgentDeps,
    text: str,
    message_history: list[ModelMessage] | None = None,
) -> tuple[str, list[ModelMessage]]:
    result = agent.run_sync(text, deps=deps, message_history=message_history)
    return result.output, list(result.all_messages())
