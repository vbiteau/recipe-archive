# World Recipe Archive

Submit a recipe site (or a single recipe URL), and it:

1. Crawls the site looking for recipe pages (using the structured "recipe"
   data most cooking sites embed under the hood, so it works regardless of
   how the page is visually designed).
2. Sends each raw recipe to Claude, which rewrites it into one clean,
   consistent format and figures out the country of origin.
3. Saves it to a database.
4. Shows it on a browsable page, grouped by country with flags.

## Running it locally

```bash
cd recipe-scraper
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# then edit .env and fill in ANTHROPIC_API_KEY at minimum.
# DATABASE_URL can stay unset locally — it'll fall back to a local SQLite file.

python app.py
```

Visit `http://localhost:5000`.

## Deploying (Render + a biteau.net subdomain)

Your domain (biteau.net) is on GoDaddy's Managed WordPress hosting, which can
only run WordPress — it can't run this Flask app. The plan: host this app on
Render (built for exactly this), and point a subdomain like
`recipes.biteau.net` at it. WordPress keeps living on the main domain,
untouched.

### 1. Push this project to GitHub

Render deploys from a GitHub repo.

```bash
cd recipe-scraper
git init
git add .
git commit -m "Initial commit"
```

Create a new repo on GitHub, then:

```bash
git remote add origin https://github.com/YOUR_USERNAME/recipe-archive.git
git push -u origin main
```

### 2. Create a Postgres database on Render

1. Go to [render.com](https://render.com) and sign up / log in.
2. Click **New +** → **PostgreSQL**.
3. Give it a name, pick the free tier, create it.
4. Once it's up, copy the **Internal Database URL** (you'll use this in step 3).

### 3. Create the web service on Render

1. Click **New +** → **Web Service**.
2. Connect your GitHub repo.
3. Settings:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app`
4. Under **Environment Variables**, add:
   - `DATABASE_URL` → the Internal Database URL from step 2
   - `ANTHROPIC_API_KEY` → your key from console.anthropic.com
   - `ANTHROPIC_MODEL` → `claude-sonnet-5`
   - `SECRET_KEY` → any random string
   - `MAX_CRAWL_PAGES` → `60` (or whatever limit you want)
5. Click **Create Web Service**. Render will build and deploy it — you'll get
   a URL like `recipe-archive.onrender.com`. Confirm the site loads there
   before moving on.

### 4. Point recipes.biteau.net at it

1. In Render, on your web service, go to **Settings** → **Custom Domains** →
   **Add Custom Domain** → enter `recipes.biteau.net`. Render will show you a
   CNAME target (something like `recipe-archive.onrender.com`).
2. In GoDaddy: go to your domain → **DNS** tab.
3. Add a new record:
   - **Type:** CNAME
   - **Name:** `recipes`
   - **Value:** the target Render gave you
   - **TTL:** default is fine
4. Save. DNS changes can take anywhere from a few minutes to a few hours to
   propagate.
5. Once it resolves, Render will automatically issue an SSL certificate for
   `recipes.biteau.net`.

Visit `https://recipes.biteau.net` once that's done — that's your live app.

## Notes on how the crawler works

- It stays within the same domain you submit and won't wander off to other sites.
- It's capped at `MAX_CRAWL_PAGES` per submission (default 60) so a run can't
  balloon out of control on a huge site. If a site has more recipes than
  that, submit it again later — already-saved recipes won't be re-added
  automatically, but nothing stops you from re-running it (duplicates aren't
  currently deduplicated; see "Possible next steps" below).
- Sites without embedded structured recipe data fall back to a rougher
  heuristic scrape, which is less reliable. If a site isn't picking up
  recipes well, try the "just this one page" mode on a single recipe URL to
  see what's actually being extracted.

## Possible next steps

- **Deduplication:** check `source_url` before inserting, so re-crawling a
  site doesn't create duplicate entries.
- **Background jobs:** right now, a crawl runs synchronously during the
  request — fine for smaller sites, but a large site could take long enough
  to time out. Moving this to a background task queue (e.g. Celery, or
  Render's background workers) would make big crawls more robust.
- **Editing:** there's currently no way to fix a recipe if Claude gets
  something wrong (e.g. a country guess you disagree with) — an edit page
  would close that gap.
- **Search:** a text search across titles/ingredients would help once the
  archive grows.
