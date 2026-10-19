"""Suggest an access-control policy for an MCP gateway from what was actually observed.

WSO2's MCP Access Control policy is configured as `tools.mode` (allow | deny) plus
`tools.exceptions` (exact tool names). With mode "deny" and a list of exceptions, only the listed tools
get through: an allow-list. This module proposes that list:

    allow     tools that were really used and look safe
    review    tools that look risky (names like delete / write / send) or whose description has injection-like text
    unused    tools the server offers that nobody has called (candidates to leave off the list)

It is a SUGGESTION to review, never applied automatically. For the risky tools it also proposes a scope
name, because per-tool scopes are how API Manager decides who may call what.
"""
# Reuse the risk and injection checks.
from obsergent.analysis.safety import injection_findings, risky_tools


# Build the suggestion for one server.
def suggest_policy(server: str, tools: list[dict], calls_per_tool: dict[str, int]) -> dict:
    # tool name -> why it looks risky.
    risky = {finding["tool"]: finding["message"] for finding in risky_tools(tools)}
    # tool name -> injection-like text found in its description.
    poisoned = {tool["name"]: hit["message"] for tool in tools
                for hit in injection_findings(tool.get("description", ""), "its description")}
    # The three buckets.
    allow, review, unused = [], [], []
    # Go through tools alphabetically.
    for tool in sorted(tools, key=lambda t: t["name"]):
        # This tool's name.
        name = tool["name"]
        # How many times it was actually called.
        calls = calls_per_tool.get(name, 0)
        # Suspicious description: needs a human look.
        if name in poisoned:
            review.append({"tool": name, "calls": calls, "reason": poisoned[name]})
        # Risky name: needs a human look.
        elif name in risky:
            review.append({"tool": name, "calls": calls, "reason": risky[name]})
        # Used and not risky: safe to allow.
        elif calls:
            allow.append({"tool": name, "calls": calls})
        # Offered but never used: leave off the list.
        else:
            unused.append({"tool": name})
    # The allow-list for the gateway policy.
    exceptions = [entry["tool"] for entry in allow]
    # The suggestion, with notes for the reader.
    return {
        "server": server,
        "allow": allow,
        "review": review,
        "unused": unused,
        # Same shape as the gateway's policy parameters: deny everything except the listed tools.
        "policy": {"tools": {"mode": "deny", "exceptions": exceptions}},
        # Risky tools are better protected by a scope than by a plain allow-list entry.
        "suggested_scopes": {entry["tool"]: f"{server}:{entry['tool']}" for entry in review},
        "notes": ["Review before applying: this is based only on calls Obsergent has seen.",
                  "A tool left out of `exceptions` is blocked by the gateway (mode deny)."],
    }
