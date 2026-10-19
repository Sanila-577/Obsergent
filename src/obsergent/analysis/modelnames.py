"""One name per model: `gpt-4o-mini` and `gpt-4o-mini-2024-07-18` are the same model, so they are shown (and counted) once.

Providers echo back the dated release of the model that answered, while the request names the model without a date. Both
are recorded, so without this module the same model would appear twice. The raw names are never thrown away: they are kept
as `versions` and shown in Detailed mode. `ui/src/lib/models.ts` does the same job in the browser; both are tested with
the same list of examples (tests/fixtures/model_names.json), so they cannot drift apart.
"""
# The same cleaning the price lookup uses: routing prefix, date suffix and ":latest" are removed.
from obsergent.analysis.pricing import base_name, canonical_provider


def canonical(name: str | None) -> str:
    """The model's name without provider path, routing prefix, release date or ':latest' (lower case)."""
    # Empty or missing names become one shared bucket instead of an empty string.
    return base_name(name) if name else "unknown model"


def display(name: str | None) -> str:
    """The name shown to people: the canonical name (one entry per model, no version date)."""
    return canonical(name)


def group_key(name: str | None, provider: str | None) -> tuple[str, str]:
    """What two calls must share to count as the same model: the provider (cleaned) and the canonical name."""
    return canonical_provider(provider), canonical(name)
