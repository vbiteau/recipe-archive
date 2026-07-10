import os
import threading
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


def _process_scrape_job(normalized_urls, mode):
    """
    Runs in a background thread so the web request can return immediately
    instead of blocking (and risking a timeout) while every URL gets
    scraped and sent to Claude one at a time.
    """
    with app.app_context():
        found = []
        for u in normalized_urls:
            try:
                if mode == "single":
                    raw = scrape_single_url(u)
                    if raw:
                        found.append({"url": u, "raw_recipe": raw})
                else:
                    found.extend(crawl_site(u))
            except Exception as e:
                print(f"[scrape job] Failed to scrape {u}: {e}")

        for item in found:
            page_url = item["url"]
            raw_recipe = item["raw_recipe"]
            try:
                normalized = format_recipe(raw_recipe, page_url)
            except Exception as e:
                print(f"[scrape job] Claude formatting failed for {page_url}: {e}")
                continue

            if normalized is None:
                continue

            existing = Recipe.query.filter_by(source_url=page_url).first()
            if existing:
                # Already have this URL — update it in place rather than duplicating
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
                continue

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
            db.session.commit()  # commit one at a time so results show up progressively

        print(f"[scrape job] Finished. Processed {len(found)} candidate recipe(s) from {len(normalized_urls)} submitted URL(s).")


@app.route("/scrape", methods=["POST"])
def scrape():
    raw_input = request.form.get("url", "").strip()
    mode = request.form.get("mode", "single")  # "single" = each link is one recipe page, "site" = crawl as a whole site

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

    if mode == "site" and len(normalized_urls) > 1:
        flash(f"Whole-site mode only processes one link per submission — crawling just the first ({normalized_urls[0]}). Submit the others separately.")
        normalized_urls = normalized_urls[:1]

    # Kick off the actual scraping + Claude formatting in the background so
    # this request returns immediately rather than risking a timeout.
    thread = threading.Thread(target=_process_scrape_job, args=(normalized_urls, mode), daemon=True)
    thread.start()

    return render_template(
        "scrape_result.html",
        submitted_count=len(normalized_urls),
        submitted_urls=normalized_urls,
        mode=mode,
    )


# ---------- Browse
