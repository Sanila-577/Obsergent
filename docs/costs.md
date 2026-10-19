# How AgentTrace calculates what a model call costs

**An estimate, never a bill.** It is the recorded number of words (tokens) times the model's price per word. The price comes
from public price lists that AgentTrace downloads and re-checks by itself. Nothing is typed in by hand.

## What costs money, and what does not

| Thing                                                                        | Cost                                                                                                                                                                                                                                       |
| ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| A model call (hosted: OpenAI, Anthropic, Groq, OpenRouter, Hugging Face ...) | **yes**: tokens in and out, cheaper for cached tokens                                                                                                                                                                                |
| A model on your own computer (Ollama, LM Studio, vLLM)                       | **$0 per call**, shown as "free". (Electricity and hardware are not counted.)                                                                                                                                                        |
| An MCP call itself                                                           | none: MCP is an open protocol. A hosted, commercial MCP server may charge per call, but no price list exists for that, so it is not counted                                                                                                |
| The WSO2 gateway                                                             | none from AgentTrace's point of view: it is open source; you pay for the machine it runs on                                                                                                                                                |
| Tools' hidden cost                                                           | **yes, and often the biggest part**: every model call carries all tool descriptions in its prompt, and every tool result is fed back to the model. The **By action** view shows what the model spent deciding to use each tool |

## Exact costs: when the provider tells us

A provider that reports the charge with each response makes an estimate unnecessary. Checked in the official documentation:

| Provider | Cost in the response? | Field |
|---|---|---|
| [OpenRouter](https://openrouter.ai/docs/guides/guides/usage-accounting) | **yes**, always | `usage.cost` (credits, 1 credit = $1), `usage.cost_details.upstream_inference_cost`, `usage.is_byok` |
| [xAI](https://docs.x.ai/developers/cost-tracking) | **yes**, includes server-side tool costs | `usage.cost_in_usd_ticks` (divide by 10^10) |
| [OpenAI](https://developers.openai.com/api/reference/python/resources/chat/subresources/completions/methods/create) | no | tokens, cached/reasoning counts, `service_tier` |
| [Anthropic](https://platform.claude.com/docs/en/api/messages) | no | tokens, cache counts, `server_tool_use.web_search_requests`, `service_tier`, `inference_geo` |
| [Gemini](https://ai.google.dev/api/generate-content) | no | `promptTokenCount`, `cachedContentTokenCount`, `candidatesTokenCount`, `thoughtsTokenCount`, `serviceTier` |
| [Groq](https://console.groq.com/docs/api-reference), [Together](https://docs.together.ai/reference/chat-completions-1), [Fireworks](https://docs.fireworks.ai/api-reference/post-chatcompletions), [DeepSeek](https://api-docs.deepseek.com/api/create-chat-completion), [Bedrock](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_TokenUsage.html) | no | tokens (and cache counts) only |
| [Cohere](https://docs.cohere.com/reference/chat) | no | `billed_units` (what is billed) next to `tokens` |
| Mistral, Azure OpenAI, Perplexity | not confirmed | |

How it gets here: LangChain's OpenAI client keeps the whole `usage` dictionary (the OpenAI SDK keeps unknown fields such as `cost`),
the OpenInference tracer records the model result as the span's `output.value`, and `ingest/billed.py` reads the charge out of it
when the span arrives. It recognises the provider by the SHAPE of the usage (the span says "openai" for OpenRouter and xAI too),
and stores it as `llm.cost.total`. **Streaming:** the charge is only in the last chunk; a call whose recorded response lacks it
falls back to the estimate. `pricing.exact_from_provider: false` shows estimates for everything.
OpenRouter **bring-your-own-key** calls also record what your own provider charged (`agenttrace.cost.upstream_usd`).

## Where prices come from (for everything that is estimated)

There is **no official, real-time price feed**: providers publish prices on web pages, and their `/v1/models` endpoints need a key.
So AgentTrace reads four public lists (plain GET requests, no key, nothing of yours is sent):

| List | Address | Covers | Unit |
|---|---|---|---|
| [models.dev](https://github.com/sst/models.dev) (open source) | `https://models.dev/api.json` | 232 providers, about 9,000 models; cache, reasoning and audio prices | $ per million tokens |
| OpenRouter | `https://openrouter.ai/api/v1/models` | the models OpenRouter serves (live) | $ per token |
| Hugging Face router | `https://router.huggingface.co/v1/models` | the models served through Hugging Face (live), per provider | $ per million tokens |
| [LiteLLM cost map](https://docs.litellm.ai/docs/proxy/custom_model_cost_map) | `https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json` | about 4,200 entries; **also** batch/flex/priority prices, long-prompt tiers, 1-hour cache price, search fees | $ per token |

(LiteLLM is an open-source library and AI gateway; AgentTrace does **not** run it, it only reads that one public JSON file.)

## When prices update, and how real-time it is

* **Exact costs are real time:** they arrive with the call.
* **Estimated costs follow the lists:** OpenRouter and Hugging Face publish live and are checked **every 30 minutes**; models.dev and
  LiteLLM are edited by people several times a day and are checked **every 2 hours** (`pricing.refresh_minutes` in `config.yaml`).
  A check sends the stored ETag, so an unchanged list answers "304 Not Modified" (a few hundred bytes). Checks happen while
  AgentTrace runs, once at start-up, once more (at most hourly) when a call arrives for a model with no price, and on **Check now**
  (`make prices`). If a download fails, the last prices stay and the Spending page says so.
* **Worst case lag** = the list's own update delay + our interval. A call made between a provider's change and our next check uses
  the old price; the price history records when AgentTrace first saw each price.
* **Costs on screen** are recalculated every time they are shown; the UI refreshes every 2 seconds in Live mode, otherwise when you
  open or reload a page. A banner on the Spending page lists price changes of the last two weeks.

## Which price is used (estimates)

1. **A call through a router** (OpenRouter, Hugging Face) uses that router's own live list.
2. Otherwise **models.dev's entry for that provider**; columns it lacks (service tiers, 1-hour cache write, search fee) are filled in from
   LiteLLM's entry for the same model; the LiteLLM entry alone if models.dev has none.
3. A provider on your own machine (`pricing.local_providers`) is **free**, even if a hosted model has the same name.
4. No price anywhere: **"no price"**, left out of totals and counted (never silently $0).
5. `pricing.overrides` in `config.yaml` (empty by default) beats everything.

The mark next to an estimate: **✓** two or more lists agree, **≈** they disagree a little (hover for the range), nothing: one list only.
`agenttrace prices show <model> --provider <p>` prints the price and the mark.

## The formula (estimates)

Prices are dollars per million tokens. Everything below stacks, as the providers' own pages say:

```
1. rates  = the model's price
            service tier (batch / flex / priority, from the response) replaces them when the list has it; batch and flex default to
            half price when it does not (the documented discount of OpenAI, Anthropic and Google)
2. rates  = the long-prompt tier whose size is below the prompt (100k, 128k, 200k, 272k ... whatever the list has)
3. uncached input = prompt - cache reads - cache writes - audio in
   cost = uncached input x input price
        + cache reads x cache-read price
        + 5-minute cache writes x write price + 1-hour cache writes x 1-hour price (Anthropic: 2x input)
        + audio in x audio-in price + audio out x audio-out price
        + (output - reasoning - audio out) x output price + reasoning x reasoning price (the output price if none is listed)
        + web searches x search fee (Anthropic: $10 per 1,000)
4. x 1.1 on the token cost for US-only inference (Anthropic 4.6 and later)
5. an exact cost reported by the provider replaces all of it
```

What the recorded numbers mean (verified): OpenAI reports `input_tokens` *including* cached ones (`ordinary = input - cached - writes`);
Anthropic's raw API reports it *without* them (`total = input + cache_creation + cache_read`), and the OpenInference tracer adds them so
the recorded prompt always includes cached tokens; Gemini bills thinking tokens at the output price and reports them next to the candidate
tokens (added when the recorded completion lacks them); Cohere bills on `billed_units`; DeepSeek's cache hits come as `prompt_cache_hit_tokens`.

**Not covered** (stated in the interface too): Anthropic Priority Tier commitments, fast mode, Bedrock/Vertex regional prices, batch
APIs used outside the recorded response, discounts, taxes, free tiers, other currencies, cache storage fees, local electricity.
**Not yet verified against a real bill:** OpenAI, Anthropic, Gemini and OpenRouter calls (the formula is checked against the providers'
published rules and documented examples).

## Old calls and changed prices

Nothing is frozen except the provider's own charge: every estimate is calculated when shown, from the recorded tokens and the price
table, so a refreshed price changes the numbers at once. The price table keeps a history (a new row only when a price changes) and by
default each call is priced with the price **valid when it was made**. `pricing.reprice: now` (or `?reprice=now`) uses today's prices.
A call older than the first price AgentTrace saw for that model uses the oldest known price.

## Turning it off

* `pricing.auto_refresh: false`: nothing is downloaded (costs use the last downloaded prices and overrides): no outbound call.
* `pricing.exact_from_provider: false`: always show estimates.
* `pricing.enabled: false`: no costs at all.
