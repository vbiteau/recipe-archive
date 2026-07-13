"""
Takes raw, messy recipe data (whatever shape it came off the source page in)
and asks Claude to turn it into one consistent, simplified structure —
including inferring the country of origin, which is the whole point of
this project.
"""

import json
import os
import re

from anthropic import Anthropic

client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

SYSTEM_PROMPT = """You are a recipe data normalizer for a global recipe archive.

You will be given raw, messy recipe data scraped from a webpage — the
formatting, wording, and completeness varies wildly from source to source.
Your job is to convert it into ONE clean, consistent structure.

Rules:
- Simplify wording. Ingredients and steps should be clear and minimal,
  not marketing copy. Strip out filler like "the secret to amazing flavor" etc.
- Ingredients: one item per line, format like "2 cups flour" or "1 onion, diced".
  Keep quantities if given; do not invent quantities that weren't there.
- Steps: numbered, one clear action per step. Combine tiny fragments,
  split up overloaded steps.
- You MUST infer the single most likely country of origin for this dish,
  even if the source page never states it. Use your knowledge of global
  cuisine. Pick the country most associated with the dish's origin, not
  where the blog is based. If a dish is genuinely ambiguous/international
  (e.g. "chocolate chip cookies"), pick the country most credited with
  its invention or the cuisine it's most identified with.
- country_code MUST be a valid ISO 3166-1 alpha-2 code (e.g. "IT", "JP", "MX").
- cuisine_region is optional finer detail (e.g. "Sichuan", "Tuscany", "Oaxaca") —
  leave null if there's nothing more specific than the country.
- If a field genuinely isn't knowable (e.g. prep_time), use null. Do not invent data.

Respond with ONLY valid JSON, no markdown fences, no commentary, matching
exactly this shape:

{
  "title": string,
  "country_name": string,
  "country_code": string,
  "cuisine_region": string or null,
  "servings": string or null,
  "prep_time": string or null,
  "cook_time": string or null,
  "total_time": string or null,
  "ingredients": [string, ...],
  "steps": [string, ...],
  "notes": string or null
}
"""


def _strip_code_fences(text):
    text = text.strip()
    text = re.sub(r"^```(json)?", "", text.strip())
    text = re.sub(r"```$", "", text.strip())
    return text.strip()


def format_recipe(raw_recipe, source_url):
    """
    raw_recipe: dict from scraper.py (title/ingredients_raw/steps_raw/etc, all messy)
    Returns a normalized dict matching the Recipe model fields, or None on failure.
    """
    user_content = (
        f"Source URL: {source_url}\n\n"
        f"Raw scraped data:\n{json.dumps(raw_recipe, ensure_ascii=False, indent=2)}"
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_content}],
    )

    text = "".join(block.text for block in response.content if block.type == "text")
    text = _strip_code_fences(text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        print(f"[formatter] JSON parse failed for {source_url}: {e}")
        print(f"[formatter] Raw Claude output was: {text[:1000]}")
        return None

    required = {"title", "country_name", "country_code", "ingredients", "steps"}
    if not required.issubset(data.keys()):
        print(f"[formatter] Missing required fields for {source_url}. Got keys: {list(data.keys())}")
        return None
    if not data["title"] or not data["ingredients"] or not data["steps"]:
        print(f"[formatter] Empty required field for {source_url}. Data: {data}")
        return None

    return data
