"""LLM calls inside an agent: turn flat span attributes into generations and a conversation.

The SDK (OpenInference instrumentors) records every model call as a span whose
attributes are FLATTENED, for example:

    llm.input_messages.3.message.role                          = "tool"
    llm.input_messages.3.message.tool_call_id                  = "e426..."
    llm.output_messages.0.message.tool_calls.0.tool_call.function.name = "search_books"
    llm.token_count.prompt                                     = 243
    llm.model_name                                             = "qwen2.5:7b"

This module rebuilds structured objects from them. It is pure functions over `Span`
objects (no database, no network), so it is easy to test.

    spans of one trace
        |  find_generations()     one Generation per model call (messages, tokens, latency)
        |  link_tool_calls()      model-requested tool call  ->  TOOL span  ->  MCP proxy span
        v
    build_conversation() / summarize_generations()   what the API and the UI show

Attribute names follow OpenInference (`llm.*`); the OpenTelemetry GenAI names
(`gen_ai.*`) are accepted for model, provider and token counts.
"""
# json: parse stored JSON text.
import json

# re: regular expressions to read the flattened keys.
import re

# dataclass: ready-made record classes.
from dataclasses import dataclass, field

# The shared data shape.
from agenttrace.models import Span

# The attribute OpenInference uses to say what kind of step a span is.
SPAN_KIND = "openinference.span.kind"
# Value for a model call.
LLM_KIND = "LLM"
# Value for a tool step.
TOOL_KIND = "TOOL"

# One flattened message key, after the "llm.input_messages." prefix: "3.message.<rest>"
MESSAGE_KEY = re.compile(r"^(\d+)\.message\.(.+)$")
# Matches "tool_calls.0.tool_call.id" (or function.name / function.arguments).
TOOL_CALL_KEY = re.compile(r"^tool_calls\.(\d+)\.tool_call\.(id|function\.name|function\.arguments)$")
# Matches a text part of a message: "contents.0.message_content.text".
CONTENT_KEY = re.compile(r"^contents\.(\d+)\.message_content\.text$")


@dataclass
# One chat message.
class Message:
    role: str  # system / user / assistant / tool
    content: str = ""
    tool_calls: list[dict] = field(default_factory=list)  # assistant only: [{id, name, arguments}]
    tool_call_id: str = ""  # tool messages only: which call this answers
    name: str = ""  # tool messages only: the tool's name


@dataclass
# A tool call the model requested, followed to what really happened.
class ToolLink:
    """A tool call the model asked for, followed through to what really happened."""
    tool_call_id: str
    name: str
    arguments: str
    tool_span_id: str | None = None  # the agent's TOOL span that ran it
    mcp_span_id: str | None = None  # the proxy span of the real MCP call (child of the TOOL span)
    mcp_status: str | None = None  # status of that MCP call: OK / ERROR / UNSET
    gateway_decision: str | None = None  # allowed / denied / ... when a gateway is in the path


@dataclass
# One model call with everything about it.
class Generation:
    span_id: str
    parent_span_id: str | None
    start_ns: int
    end_ns: int
    span_name: str  # e.g. "ChatOllama"
    model: str | None
    provider: str | None
    parameters: dict  # invocation parameters without the (large) tool list
    tools: list[str]  # names of the tools offered to the model
    input_messages: list[Message]
    output_messages: list[Message]
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    status_code: str
    status_message: str
    # The parts of the prompt that were read from / written to the provider's cache, and the reasoning part of the answer.
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    # A cost the provider itself reported (OpenInference: llm.cost.total), which beats any estimate.
    billed_usd: float | None = None
    # About how many tokens the tool descriptions in the prompt take (characters / 4: an estimate).
    tool_definition_tokens: int = 0
    # Facts that change the price of a call (all from the provider's own usage report; see ingest/billed.py).
    service_tier: str | None = None  # standard / batch / flex / priority
    cache_write_1h_tokens: int = 0  # cache writes that last an hour (Anthropic bills those at twice the input price)
    web_search_requests: int = 0  # searches the provider ran for the model (billed per search)
    inference_geo: str | None = None  # where the model ran (Anthropic: "us" costs 1.1x)
    audio_in_tokens: int = 0
    audio_out_tokens: int = 0
    extra_output_tokens: int = 0  # output billed but reported next to the completion count (Gemini thinking)
    billed_prompt_tokens: int | None = None  # Cohere bills on "billed units"
    billed_completion_tokens: int | None = None
    billed_source: str | None = None  # openrouter / xai / ...: who reported billed_usd
    upstream_usd: float | None = None  # OpenRouter bring-your-own-key: what your provider charged
    tool_links: list[ToolLink] = field(default_factory=list)
    # The cost of this call, filled in by the server (server/costing.py) as a plain dict.
    cost: dict | None = None

    @property
    # How long the model call took.
    def latency_ms(self) -> float:
        return (self.end_ns - self.start_ns) / 1e6


# Rebuild messages from flat attribute keys.
def parse_messages(attributes: dict, prefix: str) -> list[Message]:
    """Rebuild the messages stored under `prefix` (e.g. "llm.input_messages") from flat attributes."""
    # Only keys beginning with this are messages.
    start = prefix + "."
    # message number -> pieces found so far.
    raw: dict[int, dict] = {}
    # Look at every attribute.
    for key, value in attributes.items():
        # Not a message key: skip.
        if not key.startswith(start):
            # Next one.
            continue
        # Split off the message number.
        match = MESSAGE_KEY.match(key[len(start):])
        # Unrecognised shape: skip.
        if not match:
            continue
        # Find or create the record for this message number.
        entry = raw.setdefault(int(match.group(1)), {"fields": {}, "calls": {}, "parts": {}})
        # What the key says about this message (role, content, tool call...).
        rest = match.group(2)
        # A tool call request: store its id/name/arguments.
        if call := TOOL_CALL_KEY.match(rest):
            entry["calls"].setdefault(int(call.group(1)), {})[call.group(2)] = value
        # A text part of the content.
        elif part := CONTENT_KEY.match(rest):
            entry["parts"][int(part.group(1))] = str(value)
        # A plain field: role, content, name, tool_call_id.
        else:
            entry["fields"][rest] = value  # role, content, name, tool_call_id

    # The final list.
    messages = []
    # Messages in order.
    for index in sorted(raw):
        # Pieces of this message.
        entry = raw[index]
        # Its plain fields.
        fields = entry["fields"]
        # Content is either one string or several text parts (tool results use parts).
        content = fields.get("content")
        # ...or several text parts to be joined (tool results use parts).
        if content is None:
            content = "".join(entry["parts"][i] for i in sorted(entry["parts"]))
        # Build the message.
        messages.append(Message(
            role=str(fields.get("role", "")),
            content=str(content),
            tool_calls=[{"id": call.get("id", ""), "name": call.get("function.name", ""),
                         "arguments": call.get("function.arguments", "")}
                        for _, call in sorted(entry["calls"].items())],
            tool_call_id=str(fields.get("tool_call_id", "")),
            name=str(fields.get("name", "")),
        ))
    # The rebuilt conversation part.
    return messages


# The first attribute that exists among several alternative names.
def first_attribute(attributes: dict, *names: str):
    """The value of the first attribute that is present (OpenInference name first, then GenAI names)."""
    # First present value, or None.
    return next((attributes[name] for name in names if attributes.get(name) is not None), None)


# Settings sent to the model (temperature...).
def parse_parameters(attributes: dict) -> dict:
    """The model's invocation parameters (temperature, ...) as a dict, without the bulky tool list."""
    # The value is JSON text; parse it.
    try:
        # Parse (empty object if missing).
        parameters = json.loads(attributes.get("llm.invocation_parameters") or "{}")
    # Not valid JSON: no parameters.
    except (TypeError, json.JSONDecodeError):
        # Give up quietly.
        return {}
    # Must be an object.
    if not isinstance(parameters, dict):
        # The summary dict.
        return {}
    # Drop the bulky tool list and empty values.
    return {key: value for key, value in parameters.items() if key != "tools" and value is not None}


# Names of the tools offered to the model.
def tool_definition_tokens(attributes: dict) -> int:
    """About how many tokens the tool descriptions in the prompt take: their text length divided by 4 (an estimate)."""
    characters = sum(len(str(value)) for key, value in attributes.items()
                     if re.fullmatch(r"llm\.tools\.\d+\.tool\.json_schema", key))
    return round(characters / 4)


def parse_tool_names(attributes: dict) -> list[str]:
    """Names of the tools offered to the model (llm.tools.N.tool.json_schema)."""
    # Collected names.
    names = []
    # Keys like llm.tools.0.tool.json_schema, in order.
    for key in sorted(k for k in attributes if re.fullmatch(r"llm\.tools\.\d+\.tool\.json_schema", k)):
        # Each schema is JSON text.
        try:
            # Parse it.
            schema = json.loads(attributes[key])
            # The tool name is under function.name or name.
            names.append(schema.get("function", {}).get("name") or schema.get("name", ""))
        # Bad schema: skip.
        except (TypeError, json.JSONDecodeError, AttributeError):
            continue
    # Non-empty names only.
    return [name for name in names if name]


# Is this span a model call?
def is_generation(span: Span) -> bool:
    """A model call: an OpenInference LLM span, or a span that carries a model name (GenAI conventions)."""
    # MCP traffic is never a model call.
    if span.attributes.get("mcp.method.name"):
        return False  # MCP traffic, never a model call
    # An LLM span, or any span naming a model.
    return span.attributes.get(SPAN_KIND) == LLM_KIND or first_attribute(
        span.attributes, "llm.model_name", "gen_ai.request.model", "gen_ai.response.model") is not None


# Convert one span to a Generation.
def to_generation(span: Span) -> Generation:
    # Shortcut.
    attrs = span.attributes
    # Input tokens.
    prompt = first_attribute(attrs, "llm.token_count.prompt", "gen_ai.usage.input_tokens")
    # Output tokens.
    completion = first_attribute(attrs, "llm.token_count.completion", "gen_ai.usage.output_tokens")
    # Total tokens.
    total = first_attribute(attrs, "llm.token_count.total")
    # Compute the total if only the parts are known.
    if total is None and prompt is not None and completion is not None:
        total = int(prompt) + int(completion)
    # Cached and reasoning tokens, when the instrumentation reports them (OpenInference names first, then GenAI names).
    cache_read = first_attribute(attrs, "llm.token_count.prompt_details.cache_read", "gen_ai.usage.cache_read_input_tokens")
    cache_write = first_attribute(attrs, "llm.token_count.prompt_details.cache_write", "gen_ai.usage.cache_creation_input_tokens")
    reasoning = first_attribute(attrs, "llm.token_count.completion_details.reasoning", "gen_ai.usage.reasoning_tokens")
    billed = first_attribute(attrs, "llm.cost.total")
    billed_in = first_attribute(attrs, "agenttrace.billed_units.input")
    billed_out = first_attribute(attrs, "agenttrace.billed_units.output")
    upstream = first_attribute(attrs, "agenttrace.cost.upstream_usd")
    # Fill the record from the attributes.
    return Generation(
        span_id=span.span_id,
        parent_span_id=span.parent_span_id,
        start_ns=span.start_ns,
        end_ns=span.end_ns,
        span_name=span.name,
        model=first_attribute(attrs, "llm.model_name", "gen_ai.response.model", "gen_ai.request.model"),
        provider=first_attribute(attrs, "llm.provider", "gen_ai.provider.name", "gen_ai.system"),
        parameters=parse_parameters(attrs),
        tools=parse_tool_names(attrs),
        input_messages=parse_messages(attrs, "llm.input_messages"),
        output_messages=parse_messages(attrs, "llm.output_messages"),
        prompt_tokens=int(prompt) if prompt is not None else None,
        completion_tokens=int(completion) if completion is not None else None,
        total_tokens=int(total) if total is not None else None,
        status_code=span.status_code,
        status_message=span.status_message,
        cache_read_tokens=int(cache_read or 0),
        cache_write_tokens=int(cache_write or 0),
        reasoning_tokens=int(reasoning or 0),
        billed_usd=float(billed) if billed is not None else None,
        tool_definition_tokens=tool_definition_tokens(attrs),
        service_tier=first_attribute(attrs, "llm.service_tier"),
        cache_write_1h_tokens=int(first_attribute(attrs, "agenttrace.cache_write_1h_tokens") or 0),
        web_search_requests=int(first_attribute(attrs, "agenttrace.web_search_requests") or 0),
        inference_geo=first_attribute(attrs, "agenttrace.inference_geo"),
        audio_in_tokens=int(first_attribute(attrs, "llm.token_count.prompt_details.audio") or 0),
        audio_out_tokens=int(first_attribute(attrs, "llm.token_count.completion_details.audio") or 0),
        extra_output_tokens=int(first_attribute(attrs, "agenttrace.extra_output_tokens") or 0),
        billed_prompt_tokens=int(billed_in) if billed_in is not None else None,
        billed_completion_tokens=int(billed_out) if billed_out is not None else None,
        billed_source=first_attribute(attrs, "agenttrace.cost.source"),
        upstream_usd=float(upstream) if upstream is not None else None,
    )


# All model calls of a run, oldest first.
def find_generations(spans: list[Span]) -> list[Generation]:
    """Every model call of a trace, oldest first, with its tool calls linked to the MCP traffic."""
    # Convert every model-call span.
    generations = [to_generation(span) for span in sorted(spans, key=lambda s: s.start_ns) if is_generation(span)]
    # Attach what each requested tool call really did.
    link_tool_calls(spans, generations)
    # The result.
    return generations


# Match model-requested tool calls to TOOL spans and proxy spans.
def link_tool_calls(spans: list[Span], generations: list[Generation]) -> None:
    """Fill `tool_links`: model-requested call -> TOOL span -> the proxy's MCP span.

    The model's tool-call id is NOT stored on the TOOL span, so the match is structural:
    a tool call requested by generation N is executed by a TOOL span with the same name that
    starts after generation N ended and before generation N+1 started. Repeated calls of the same
    tool are matched in order. The MCP span is the child of that TOOL span (the SDK passes the
    tool step's trace context to the proxy).
    """
    # The agent's tool steps, oldest first.
    tool_spans = sorted((s for s in spans if s.attributes.get(SPAN_KIND) == TOOL_KIND), key=lambda s: s.start_ns)
    # proxy span of each real MCP call, keyed by its parent (the TOOL span).
    mcp_by_parent = {s.parent_span_id: s for s in spans if s.attributes.get("mcp.method.name") == "tools/call"}
    # TOOL spans already matched (so repeated calls match in order).
    used: set[str] = set()
    # For each model call...
    for position, generation in enumerate(generations):
        # ...when the next model call started (the window ends there).
        next_start = generations[position + 1].start_ns if position + 1 < len(generations) else None
        # ...for each message it produced...
        for message in generation.output_messages:
            # ...for each tool it requested...
            for call in message.tool_calls:
                # ...start a link record...
                link = ToolLink(tool_call_id=call["id"], name=call["name"], arguments=call["arguments"])
                # ...find the TOOL span: same name, started after this call ended, before the next began.
                tool_span = next((s for s in tool_spans
                                  if s.span_id not in used and s.attributes.get("tool.name") == call["name"]
                                  and s.start_ns >= generation.end_ns
                                  and (next_start is None or s.start_ns < next_start)), None)
                # Found it.
                if tool_span:
                    # Mark as used.
                    used.add(tool_span.span_id)
                    # Remember it.
                    link.tool_span_id = tool_span.span_id
                    # The proxy span below that tool step.
                    if mcp_span := mcp_by_parent.get(tool_span.span_id):
                        # Remember it.
                        link.mcp_span_id = mcp_span.span_id
                        # Did the MCP call succeed?
                        link.mcp_status = mcp_span.status_code
                        # What the gateway decided, if any.
                        link.gateway_decision = mcp_span.attributes.get("gateway.decision")
                # Keep the link (even if unmatched).
                generation.tool_links.append(link)


# The run as chat messages.
def build_conversation(generations: list[Generation]) -> list[dict]:
    """The run as a chat: the last model call saw the whole history, so history = its input + its reply.

    Every tool call (and its tool-result message) is enriched with a `link` that points at the real
    MCP call, which is what lets the UI jump from "the model asked for X" to "what happened on the wire".
    """
    # No model calls: empty chat.
    if not generations:
        return []
    # tool_call_id -> its link.
    links = {link.tool_call_id: link for generation in generations for link in generation.tool_links}
    # The last call saw the whole history.
    last = generations[-1]
    # Result list.
    conversation = []
    # History = last call's input + its reply.
    for message in last.input_messages + last.output_messages:
        # Message as a plain dict.
        entry = {"role": message.role, "content": message.content, "name": message.name,
                 "tool_call_id": message.tool_call_id, "tool_calls": []}
        # Attach a link to each requested call.
        for call in message.tool_calls:
            # Its link.
            link = links.get(call["id"])
            # Add the call with its link.
            entry["tool_calls"].append(call | {"link": link.__dict__ if link else None})
        # For a tool-result message, the call it answers.
        link = links.get(message.tool_call_id) if message.tool_call_id else None
        # Attach it.
        entry["link"] = link.__dict__ if link else None
        # Keep.
        conversation.append(entry)
    # The chat.
    return conversation


# Totals for the run.
def summarize_generations(generations: list[Generation]) -> dict:
    """Totals for the run: calls, tokens, time spent in the model, models used."""
    # Sum of the numbers that are present (None if none).
    def total(values):
        # Ignore missing values.
        numbers = [v for v in values if v is not None]
        # The total, or None.
        return sum(numbers) if numbers else None

    return {
        "calls": len(generations),
        "models": sorted({g.model for g in generations if g.model}),
        "prompt_tokens": total(g.prompt_tokens for g in generations),
        "completion_tokens": total(g.completion_tokens for g in generations),
        "total_tokens": total(g.total_tokens for g in generations),
        "latency_ms": sum(g.latency_ms for g in generations),
    }
