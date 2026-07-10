import os
import threading
import time
import uuid
from urllib.parse import urlparse

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from dotenv import load_dotenv

from models import db, Recipe
from scraper import scrape_single_url
from crawler import crawl_site
from formatter import format_recipe
from utils import flag_emoji

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-me")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///recipes.db")
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}

db.init_app(app)

with app.app_context():
    db.create_all()

app.jinja_env.filters["flag"] = flag_emoji

# In-memory tracker for live scrape job progress, keyed by job_id.
# Fine for a single-process app like this; not meant to survive a restart.
SCRAPE_JOBS = {}


# ---------- Home / submit a site ----------

@app.route("/")
def index():
    total_recipes = Recipe.query.count()
    total_countries = db.session.query(Recipe.country_code).distinct().count()
    return render_template(
        "index.html",
        total_recipes=total_recipes,
        total_countries=total_countries,
    )


def _is_whole_site_url(url):
    """
    A bare domain (nothing after the TLD, or just a trailing slash) means
    "crawl the whole site". Any URL with a real path after it means
    "scrape just this one recipe".
    """
    path = urlparse(url).path
    return path in ("", "/")


def _save_normalized_recipe(normalized, raw_recipe, page_url):
    """Insert or update a Recipe row. Returns True if it counts as saved."""
    if normalized is None:
        return False

    existing = Recipe.query.filter_by(source_url=page_url).first()
    if existing:
        existing.title = normalized["title"]
        existing.country_name = normalized.get("country_name")
        existing.country_code = normalized.get("country_code")
        existing.cuisine_region = normalized.get("cuisine_region")
        existing.servings = normalized.get("servings")
        existing.prep_time = normalized.get("prep_time")
        existing.cook_time = normalized.get("cook_time")
        existing.total_time = normalized.get("total_time")
        existing.ingredients = normalized.get("ingredients", [])
        existing.steps = normalized.get("steps", [])
        existing.notes = normalized.get("notes")
        existing.image_url = raw_recipe.get("image_url")
        db.session.commit()
        return True

    recipe = Recipe(
        title=normalized["title"],
        country_name=normalized.get("country_name"),
        country_code=normalized.get("country_code"),
        cuisine_region=normalized.get("cuisine_region"),
        servings=normalized.get("servings"),
        prep_time=normalized.get("prep_time"),
        cook_time=normalized.get("cook_time"),
        total_time=normalized.get("total_time"),
        ingredients=normalized.get("ingredients", []),
        steps=normalized.get("steps", []),
        notes=normalized.get("notes"),
        image_url=raw_recipe.get("image_url"),
        source_url=page_url,
        source_domain=urlparse(page_url).netloc,
    )
    db.session.add(recipe)
    db.session.commit()
    return True


def _process_scrape_job(job_id, normalized_urls):
    """
    Runs in a background thread. Processes each submitted URL fully
    (scrape -> Claude format -> save) before moving to the next, updating
    SCRAPE_JOBS[job_id] along the way so the frontend can poll and show
    live per-link progress in the terminal view.
    """
    with app.app_context():
        job = SCRAPE_JOBS[job_id]

        for u in normalized_urls:
            item = job["items"][u]
            item["state"] = "working"
            item["detail"] = "starting..."
            item["started_at"] = time.time()

            try:
                if _is_whole_site_url(u):
                    def progress_cb(visited, found_count, item=item):
                        item["detail"] = f"visited {visited} page{'s' if visited != 1 else ''}, found {found_count} candidate{'s' if found_count != 1 else ''}"
                    raw_items = crawl_site(u, progress_callback=progress_cb)
                else:
                    raw = scrape_single_url(u)
                    raw_items = [{"url": u, "raw_recipe": raw}] if raw else []
            except Exception as e:
                print(f"[scrape job] Failed to scrape {u}: {e}")
                raw_items = []

            saved_count = 0
            total_candidates = len(raw_items)

            for i, candidate in enumerate(raw_items, start=1):
                page_url = candidate["url"]
                raw_recipe = candidate["raw_recipe"]
                item["detail"] = f"formatting {i}/{total_candidates}..."

                try:
                    normalized = format_recipe(raw_recipe, page_url)
                    if _save_normalized_recipe(normalized, raw_recipe, page_url):
                        saved_count += 1
                except Exception as e:
                    print(f"[scrape job] Claude formatting failed for {page_url}: {e}")

            item["state"] = "done"
            item["count"] = saved_count
            item["detail"] = f"{saved_count} recipe{'s' if saved_count != 1 else ''} scraped"
            item["finished_at"] = time.time()

        job["finished"] = True
        print(f"[scrape job] {job_id} finished.")


@app.route("/scrape", methods=["POST"])
def scrape():
    raw_input = request.form.get("url", "").strip()

    if not raw_input:
        flash("Please enter at least one URL.")
        return redirect(url_for("index"))

    # Split on newlines (and tolerate commas/whitespace too), drop blanks, dedupe while preserving order
    raw_lines = [line.strip() for line in raw_input.replace(",", "\n").splitlines()]
    seen = set()
    urls = []
    for line in raw_lines:
        if not line or line in seen:
            continue
        seen.add(line)
        urls.append(line)

    if not urls:
        flash("Please enter at least one URL.")
        return redirect(url_for("index"))

    normalized_urls = []
    for u in urls:
        if not u.startswith(("http://", "https://")):
            u = "https://" + u
        if urlparse(u).netloc:
            normalized_urls.append(u)

    if not normalized_urls:
        flash("None of those looked like valid URLs.")
        return redirect(url_for("index"))

    job_id = uuid.uuid4().hex[:12]
    SCRAPE_JOBS[job_id] = {
        "urls": normalized_urls,
        "items": {
