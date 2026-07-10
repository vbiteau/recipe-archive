import os
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


@app.route("/scrape", methods=["POST"])
def scrape():
    url = request.form.get("url", "").strip()
    mode = request.form.get("mode", "site")  # "site" = crawl whole domain, "single" = one recipe page

    if not url:
        flash("Please enter a URL.")
        return redirect(url_for("index"))

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    parsed = urlparse(url)
    if not parsed.netloc:
        flash("That doesn't look like a valid URL.")
        return redirect(url_for("index"))

    source_domain = parsed.netloc

    # Step 1: get raw recipe(s) off the site
    if mode == "single":
        raw = scrape_single_url(url)
        found = [{"url": url, "raw_recipe": raw}] if raw else []
    else:
        found = crawl_site(url)

    if not found:
        return render_template(
            "scrape_result.html",
            source_url=url,
            saved=[],
            failed_count=0,
            no_recipes_found=True,
        )

    # Step 2: normalize each raw recipe with Claude, then save
    saved = []
    failed_count = 0

    for item in found:
        page_url = item["url"]
        raw_recipe = item["raw_recipe"]

        normalized = format_recipe(raw_recipe, page_url)
        if normalized is None:
            failed_count += 1
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
            source_domain=source_domain,
        )
        db.session.add(recipe)
        saved.append(recipe)

    db.session.commit()

    return render_template(
        "scrape_result.html",
        source_url=url,
        saved=saved,
        failed_count=failed_count,
        no_recipes_found=False,
    )


# ---------- Browse recipes, grouped by country ----------

@app.route("/recipes")
def recipes():
    country_filter = request.args.get("country")

    query = Recipe.query.order_by(Recipe.country_name, Recipe.title)
    if country_filter:
        query = query.filter(Recipe.country_code == country_filter.upper())
    all_recipes = query.all()

    # Group by country for display
    grouped = {}
    for r in all_recipes:
        key = (r.country_code, r.country_name)
        grouped.setdefault(key, []).append(r)

    # Sort countries alphabetically by name
    grouped_sorted = dict(sorted(grouped.items(), key=lambda kv: (kv[0][1] or "Unknown")))

    # For the filter dropdown: every distinct country currently in the DB
    all_countries = (
        db.session.query(Recipe.country_code, Recipe.country_name)
        .distinct()
        .order_by(Recipe.country_name)
        .all()
    )

    return render_template(
        "recipes.html",
        grouped=grouped_sorted,
        all_countries=all_countries,
        active_filter=country_filter.upper() if country_filter else None,
    )


@app.route("/recipes/<int:recipe_id>")
def recipe_detail(recipe_id):
    recipe = Recipe.query.get_or_404(recipe_id)
    return render_template("recipe_detail.html", recipe=recipe)


@app.route("/api/recipes")
def api_recipes():
    """Simple JSON API, handy if you want a frontend framework on top later."""
    all_recipes = Recipe.query.order_by(Recipe.country_name, Recipe.title).all()
    return jsonify([r.to_dict() for r in all_recipes])


if __name__ == "__main__":
    app.run(debug=True, port=5000)
