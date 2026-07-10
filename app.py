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
