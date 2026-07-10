"""
Extracts raw recipe data from a single page.

Strategy:
1. Look for Schema.org "Recipe" structured data (JSON-LD). Most recipe sites
   embed this regardless of how the page is visually designed, since it's what
   Google uses for rich recipe search results. This is why it's the most
   reliable way to get consistent raw data "no matter how it's formatted."
2. If that's not present, fall back to a heuristic text scrape looking for
   ingredient/instruction sections.

Either way, the output here is intentionally raw/messy — normalization and
country inference happen later, in formatter.py, via Claude.
"""

import json
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; RecipeArchiveBot/1.0; +https://biteau.net)"
}

REQUEST_TIMEOUT = 12


def fetch_page(url):
    """Fetch a URL and return a BeautifulSoup object, or None on failure."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            return None
        return BeautifulSoup(resp.text, "lxml")
    except requests.RequestException:
        return None


def _flatten_jsonld(data):
    """JSON-LD can nest recipes inside @graph, or be a list of objects. Flatten it."""
    items = []
    if isinstance(data, list):
        for d in data:
            items.extend(_flatten_jsonld(d))
    elif isinstance(data, dict):
        if "@graph" in data:
            items.extend(_flatten_jsonld(data["@graph"]))
        else:
            items.append(data)
    return items


def _is_recipe_type(item):
    t = item.get("@type")
    if isinstance(t, list):
        return "Recipe" in t
    return t == "Recipe"


def _text_or_join(value):
    """Recipe instructions can be a string, list of strings, or list of HowToStep objects."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()]
    if isinstance(value, list):
        out = []
        for v in value:
            if isinstance(v, str):
                out.append(v.strip())
            elif isinstance(v, dict):
                text = v.get("text") or v.get("name")
                if text:
                    out.append(text.strip())
        return out
    return []


def extract_jsonld_recipe(soup):
    """Return a raw recipe dict from JSON-LD structured data, or None."""
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue

        for item in _flatten_jsonld(data):
            if not isinstance(item, dict) or not _is_recipe_type(item):
                continue

            ingredients = item.get("recipeIngredient") or item.get("ingredients") or []
            if isinstance(ingredients, str):
                ingredients = [ingredients]

            steps = _text_or_join(item.get("recipeInstructions"))

            image = item.get("image")
            if isinstance(image, list):
                image = image[0] if image else None
            if isinstance(image, dict):
                image = image.get("url")

            return {
                "title": item.get("name"),
                "ingredients_raw": ingredients,
                "steps_raw": steps,
                "servings_raw": item.get("recipeYield"),
                "prep_time_raw": item.get("prepTime"),
                "cook_time_raw": item.get("cookTime"),
                "total_time_raw": item.get("totalTime"),
                "image_url": image,
                "cuisine_raw": item.get("recipeCuisine"),
                "extraction_method": "jsonld",
            }
    return None


def extract_heuristic_recipe(soup):
    """
    Fallback for sites without structured data. Looks for headings that
    mention ingredients/instructions and grabs nearby list content.
    Less reliable, so we hand Claude everything and let it sort out the mess.
    """
    title_tag = soup.find("h1")
    title = title_tag.get_text(strip=True) if title_tag else None

    def collect_near(keyword):
        results = []
        for heading in soup.find_all(["h1", "h2", "h3", "h4", "strong", "b"]):
            if keyword in heading.get_text(strip=True).lower():
                sib = heading.find_next(["ul", "ol"])
                if sib:
                    results.extend(li.get_text(" ", strip=True) for li in sib.find_all("li"))
        return results

    ingredients = collect_near("ingredient")
    steps = collect_near("instruction") or collect_near("direction") or collect_near("method")

    if not title and not ingredients and not steps:
        return None

    return {
        "title": title,
        "ingredients_raw": ingredients,
        "steps_raw": steps,
        "servings_raw": None,
        "prep_time_raw": None,
        "cook_time_raw": None,
        "total_time_raw": None,
        "image_url": None,
        "cuisine_raw": None,
        "extraction_method": "heuristic",
    }


def extract_recipe_from_soup(soup):
    """Try structured data first, fall back to heuristics. Returns None if nothing found."""
    if soup is None:
        return None
    recipe = extract_jsonld_recipe(soup)
    if recipe is None:
        recipe = extract_heuristic_recipe(soup)

    # Require at least some ingredients or steps to count as a real recipe
    if recipe and (recipe.get("ingredients_raw") or recipe.get("steps_raw")):
        return recipe
    return None


def scrape_single_url(url):
    """Convenience function: fetch + extract in one call. Used for single-recipe-URL input."""
    soup = fetch_page(url)
    return extract_recipe_from_soup(soup)
