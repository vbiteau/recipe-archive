"""
Given a starting URL (a homepage, category page, or single recipe page),
crawl within that same domain and collect every page that turns out to
contain a recipe, using scraper.extract_recipe_from_soup().

Bounded by MAX_CRAWL_PAGES so a submission can't run forever. Skips
common non-content paths (images, feeds, admin, etc.) to avoid wasting
requests.
"""

import os
from collections import deque
from urllib.parse import urljoin, urlparse

from scraper import fetch_page, extract_recipe_from_soup

MAX_CRAWL_PAGES = int(os.environ.get("MAX_CRAWL_PAGES", 60))

SKIP_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico",
    ".css", ".js", ".pdf", ".zip", ".mp4", ".mp3", ".xml", ".json",
)

SKIP_PATH_HINTS = (
    "/wp-admin", "/wp-login", "/cart", "/checkout", "/account",
    "/login", "/signup", "/feed", "/tag/", "/author/", "/privacy",
    "/terms", "/contact",
)


def _same_domain(url, root_netloc):
    return urlparse(url).netloc == root_netloc


def _should_skip(url):
    path = urlparse(url).path.lower()
    if path.endswith(SKIP_EXTENSIONS):
        return True
    if any(hint in path for hint in SKIP_PATH_HINTS):
        return True
    return False


def crawl_site(start_url, max_pages=None, progress_callback=None):
    """
    BFS crawl starting at start_url, staying within the same domain.
    Returns a list of dicts: {"url": ..., "raw_recipe": {...}}

    progress_callback, if given, is called with (pages_visited, recipes_found)
    after each page — useful for streaming status back to a user.
    """
    max_pages = max_pages or MAX_CRAWL_PAGES
    root_netloc = urlparse(start_url).netloc

    visited = set()
    queue = deque([start_url])
    found = []

    while queue and len(visited) < max_pages:
        url = queue.popleft()
        if url in visited or _should_skip(url):
            continue
        visited.add(url)

        soup = fetch_page(url)
        if soup is None:
            continue

        recipe = extract_recipe_from_soup(soup)
        if recipe:
            found.append({"url": url, "raw_recipe": recipe})

        # Queue up internal links for further crawling
        for a in soup.find_all("a", href=True):
            link = urljoin(url, a["href"]).split("#")[0]
            if (
                _same_domain(link, root_netloc)
                and link not in visited
                and not _should_skip(link)
                and len(visited) + len(queue) < max_pages * 3  # cap queue growth
            ):
                queue.append(link)

        if progress_callback:
            progress_callback(len(visited), len(found))

    return found
