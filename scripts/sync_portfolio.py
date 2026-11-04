#!/usr/bin/env python3
"""Keep the profile README in sync with the portfolio at irvandani.pages.dev.

Rewrites two marked blocks in README.md:

  <!-- STATS:START --> ... <!-- STATS:END -->
      Years of experience, number of websites and availability, read from the
      portfolio homepage (meta description + "Available for projects" label).

  <!-- PROJECTS:START --> ... <!-- PROJECTS:END -->
      The latest projects, in the order they appear on /projects/. Each card
      uses the project page's og:title, og:description and og:image.

Everything outside the markers is left alone, so the rest of the README can be
edited by hand as usual.

Safety: if the portfolio can't be reached, or no project can be read, the
script exits with an error and README.md is not touched. A broken or
redesigned portfolio never wipes the README; the failed run shows up in the
Actions tab instead.

Uses only the Python standard library.
"""

import html
import re
import sys
import time
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

SITE = "https://irvandani.pages.dev"
README = Path(__file__).resolve().parent.parent / "README.md"
MAX_PROJECTS = 6
USER_AGENT = "readme-sync/1.0 (+https://github.com/adityairvndn/adityairvndn)"


def fetch(url, tries=3):
    for attempt in range(1, tries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", "replace")
        except Exception as exc:  # network hiccups: retry, then give up loudly
            if attempt == tries:
                raise RuntimeError(f"could not fetch {url}: {exc}") from exc
            time.sleep(3 * attempt)


class _PageParser(HTMLParser):
    """Collects <meta> tags and <a href> links from a page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = {}
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta":
            key = attrs.get("property") or attrs.get("name")
            content = attrs.get("content")
            if key and content and key not in self.meta:
                self.meta[key] = content.strip()
        elif tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])


def parse(page):
    parser = _PageParser()
    parser.feed(page)
    return parser


def project_urls(index_html):
    """Project pages linked from /projects/, in page order, without duplicates."""
    host = urlparse(SITE).netloc
    seen, urls = set(), []
    for href in parse(index_html).links:
        link = urlparse(urljoin(SITE + "/projects/", href))
        if link.netloc != host:
            continue
        match = re.fullmatch(r"/projects/([a-z0-9][a-z0-9-]*)/?", link.path)
        if match and match.group(1) not in seen:
            seen.add(match.group(1))
            urls.append(f"{SITE}/projects/{match.group(1)}/")
    return urls


def shorten(text, limit=200):
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    first = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)[0]
    if len(first) <= limit:
        return first
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def project_info(url):
    meta = parse(fetch(url)).meta
    title = re.split(r"\s+[—|]\s+", meta.get("og:title", ""))[0].strip()
    if not title:
        print(f"warning: {url} has no og:title, skipped", file=sys.stderr)
        return None
    name, _, kind = title.partition(": ")
    description = meta.get("og:description") or meta.get("description") or ""
    image = meta.get("og:image")
    return {
        "url": url,
        "name": name.strip(),
        "kind": kind.strip(),
        "description": shorten(description),
        "image": urljoin(url, image) if image else "",
    }


def _card(p):
    e = html.escape
    lines = ['<td width="50%" valign="top">']
    if p["image"]:
        lines.append(
            f'<a href="{e(p["url"])}"><img src="{e(p["image"])}" '
            f'alt="{e(p["name"])} website" width="100%"></a>'
        )
    heading = f'<b><a href="{e(p["url"])}">{e(p["name"])}</a></b>'
    if p["kind"]:
        heading += f' · {e(p["kind"])}'
    lines.append(f"<p>{heading}<br>")
    if p["description"]:
        lines.append(f'{e(p["description"])}')
    lines.append("</p>")
    lines.append("</td>")
    return "\n".join(lines)


def render_projects(projects, total):
    more = f"{SITE}/projects/"
    cells = [_card(p) for p in projects]
    if len(cells) % 2:  # fill the empty slot with a link to the full list
        cells.append(
            '<td width="50%" valign="middle" align="center">\n'
            f'<a href="{more}"><b>See all {total} projects →</b></a><br>\n'
            "<sub>Case studies with screenshots and results</sub>\n"
            "</td>"
        )
        footer = ""
    else:
        footer = f'\n\n<p align="right"><a href="{more}">See all {total} projects →</a></p>'
    rows = [
        "<tr>\n" + "\n".join(cells[i : i + 2]) + "\n</tr>" for i in range(0, len(cells), 2)
    ]
    return "<table>\n" + "\n".join(rows) + "\n</table>" + footer


def render_stats(home_html):
    page = parse(home_html)
    desc = page.meta.get("description") or page.meta.get("og:description") or ""
    years = re.search(r"(\d+\+?)\s+years", desc)
    sites = re.search(r"(?:around|±|~)\s*(\d+)\s+(?:\w+\s+)?websites", desc)
    if not (years and sites):
        return None
    parts = [
        f"**{years.group(1)} years** of experience",
        f"**±{sites.group(1)}** business websites",
    ]
    if re.search(r"available for projects", home_html, re.I):
        parts.append("✅ Available for projects")
    return " · ".join(parts)


def replace_block(text, name, body):
    pattern = re.compile(rf"(<!-- {name}:START -->)(.*?)(<!-- {name}:END -->)", re.S)
    if not pattern.search(text):
        raise RuntimeError(f"marker <!-- {name}:START/END --> not found in README.md")
    return pattern.sub(lambda m: f"{m.group(1)}\n{body}\n{m.group(3)}", text, count=1)


def main():
    readme = README.read_text(encoding="utf-8")

    urls = project_urls(fetch(SITE + "/projects/"))
    projects = []
    for url in urls:
        info = project_info(url)
        if info:
            projects.append(info)
        if len(projects) == MAX_PROJECTS:
            break
    if not projects:
        raise RuntimeError("no projects found on the portfolio; README left unchanged")

    updated = replace_block(readme, "PROJECTS", render_projects(projects, len(urls)))

    stats = render_stats(fetch(SITE + "/"))
    if stats:
        updated = replace_block(updated, "STATS", stats)
    else:
        print("warning: stats not found on the homepage; kept the current ones", file=sys.stderr)

    if updated == readme:
        print(f"No changes ({len(projects)} projects).")
    else:
        README.write_text(updated, encoding="utf-8")
        print(f"README updated ({len(projects)} projects).")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        sys.exit(f"error: {exc}")
