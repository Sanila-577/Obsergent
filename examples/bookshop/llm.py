"""llm.py - which language model the agent uses.

Default: a free local model through Ollama.
    ollama pull qwen2.5:7b        # 16 GB RAM or more
    ollama pull llama3.2:3b       # 8 GB RAM  (then: export OLLAMA_MODEL=llama3.2:3b)
No Ollama yet? Set FAKE_LLM=1 to use a scripted stand-in model, so you can
still run and trace the whole agent.
"""
import json  # to read the JSON text that the MCP tools return
import os  # to read environment variables (FAKE_LLM, OLLAMA_MODEL, OLLAMA_HOST)
from typing import Any  # type hint for "anything"

from langchain_core.language_models.chat_models import BaseChatModel  # base class every chat model extends
from langchain_core.messages import (  # AIMessage = model reply; ToolMessage = a tool's result
    AIMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult  # wrappers LangChain expects a model to return


def get_llm():
    """Return the chat model the agent should use: fake one or real Ollama."""
    if os.environ.get("FAKE_LLM") == "1":  # e.g. FAKE_LLM=1 python agent.py
        return ScriptedFakeLLM()
    # Imported only here, so FAKE_LLM mode works even if langchain_ollama isn't installed.
    from langchain_ollama import ChatOllama

    return ChatOllama(
        # Which local model to run; override with OLLAMA_MODEL=llama3.2:3b
        model=os.environ.get("OLLAMA_MODEL", "qwen2.5:7b"),
        # Where the Ollama server listens (its default port is 11434).
        base_url=os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
        temperature=0,  # 0 = no randomness, so the same question gives the same answer
    )


def _text(message) -> str:
    """Tool results can be a string or a list of content blocks; return plain text."""
    content = message.content
    if isinstance(content, list):
        # A list of blocks: each is a dict like {"type": "text", "text": "..."} or a plain value.
        return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return content or ""  # plain string (or empty if None)


class ScriptedFakeLLM(BaseChatModel):
    """Pretends to be a model: search -> check price -> answer. For learning and tests only."""

    def bind_tools(self, tools: Any, **kwargs: Any):
        # A real model needs to be told which tools exist. Ours follows a fixed
        # script, so it ignores them and just returns itself.
        return self

    @property
    def _llm_type(self) -> str:
        return "scripted-fake"  # name LangChain shows in logs and traces

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        """Called each time the graph's "agent" node asks the model for a reply."""
        # Count how many tool results are already in the conversation: that
        # tells us which step of the script we are on.
        tool_results = [m for m in messages if isinstance(m, ToolMessage)]
        if len(tool_results) == 0:
            # Step 1: no tools used yet -> ask to search for "python" books.
            msg = AIMessage(content="", tool_calls=[
                {"name": "search_books", "args": {"query": "python"}, "id": "call_1"}])
        elif len(tool_results) == 1:
            # Step 2: we have search results -> take the first hit's id and ask for its price.
            hits = json.loads(_text(tool_results[0]) or "[]")
            book_id = hits[0]["id"] if hits else "b1"  # fall back to b1 if nothing found
            msg = AIMessage(content="", tool_calls=[
                {"name": "get_price_and_stock", "args": {"book_id": book_id}, "id": "call_2"}])
        else:
            # Step 3: we have the price -> write the final answer (no tool call, so the graph ends).
            info = json.loads(_text(tool_results[-1]))
            msg = AIMessage(content=f"Book {info['id']} costs ${info['price_usd']} "
                                    f"and there are {info['in_stock']} copies in stock.")
        return ChatResult(generations=[ChatGeneration(message=msg)])
