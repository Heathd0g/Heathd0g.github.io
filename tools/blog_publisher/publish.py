#!/usr/bin/env python3
"""Publish one markdown file to the heath.dog blog.

Drop a .md file on "Blog Publisher.app" (or run this script on it) and it:
  1. reads the title (front matter `title:`, else the first `# Heading`, else the file name)
     and the date (front matter `date:`, else today),
  2. copies any local images it links to into assets/blog/<slug>/ and points the links there,
  3. writes _posts/YYYY-MM-DD-<slug>.md with the front matter the site's layout needs,
  4. checks the text for things that should not go online (private network addresses,
     email addresses, /Users/ paths) and warns,
  5. shows the title, date and web address and waits for Publish (Preview opens a local copy),
  6. commits only the post and its images, pushes, waits for GitHub Pages to build,
     and opens the live page.

A file whose title matches a post already on the site updates that post in place
(same date, same address).

Usage:
  publish.py <file.md>              ask with Mac dialogs (what the app runs)
  publish.py <file.md> --dry-run    print what it would do; write nothing
  publish.py <file.md> --yes        no dialogs: publish straight away (terminal use)
Options:
  --repo PATH     the site repo (default: the repo this script sits in)
  --no-wait       push but do not wait for the live page
  --title TEXT    use this title instead of the one in the file
  --date YYYY-MM-DD   use this date instead of the file's or today's
"""
import argparse
import datetime as dt
import html
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

SITE_URL = "https://heath.dog"
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif"}
DEFAULT_REPO = Path(__file__).resolve().parents[2]


class Stop(Exception):
    """A problem that ends the run with a message to HG."""


# ---------- reading the file ----------

def split_front_matter(text):
    """Return (dict of simple key: value lines, list of raw lines, body)."""
    if text.startswith("﻿"):
        text = text[1:]
    m = re.match(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?", text, re.S)
    if not m:
        return {}, [], text
    raw = m.group(1).splitlines()
    fm = {}
    for line in raw:
        km = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if km:
            fm[km.group(1)] = unquote(km.group(2).strip())
    return fm, raw, text[m.end():]


def unquote(v):
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def yaml_str(s):
    return json.dumps(s, ensure_ascii=False)  # a JSON string is a valid YAML string


def slugify(s):
    s = s.lower().replace("&", " and ").replace("'", "").replace("’", "")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:70].rstrip("-") or "post"


def parse_date(s):
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s or "")
    if not m:
        return None
    return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


# ---------- images ----------

IMG_MD = re.compile(r"(!\[[^\]]*\]\()\s*(<[^>]+>|[^)\s]+)(\s+\"[^\"]*\")?\s*(\))")
IMG_HTML = re.compile(r"(<img\b[^>]*?\bsrc=)([\"'])([^\"']+)(\2)", re.I)


def is_local(ref):
    return not re.match(r"^(https?:|data:|mailto:|/|#)", ref)


def collect_images(body, src_dir, slug):
    """Find local images, plan their copies, rewrite links. Returns (body, copies, missing)."""
    copies, missing, seen = [], [], {}

    def target_for(ref):
        ref_clean = ref.strip("<>")
        if not is_local(ref_clean):
            return None
        path = (src_dir / urllib.request.url2pathname(ref_clean.split("?")[0])).resolve()
        if path in seen:
            return seen[path]
        if not path.is_file():
            missing.append(ref_clean)
            seen[path] = None
            return None
        if path.suffix.lower() not in IMAGE_EXT:
            missing.append(ref_clean + " (not an image type)")
            seen[path] = None
            return None
        name = slugify(path.stem) + path.suffix.lower()
        used = {c[1] for c in copies}
        n = 2
        while name in used:
            name = "%s-%d%s" % (slugify(path.stem), n, path.suffix.lower())
            n += 1
        url = "/assets/blog/%s/%s" % (slug, name)
        copies.append((path, name))
        seen[path] = url
        return url

    def md_sub(m):
        url = target_for(m.group(2))
        if not url:
            return m.group(0)
        return m.group(1) + url + (m.group(3) or "") + m.group(4)

    def html_sub(m):
        url = target_for(m.group(3))
        if not url:
            return m.group(0)
        return m.group(1) + m.group(2) + url + m.group(4)

    body = IMG_MD.sub(md_sub, body)
    body = IMG_HTML.sub(html_sub, body)
    return body, copies, missing


# ---------- privacy check ----------

PRIVACY = [
    ("a private network address", re.compile(
        r"\b(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b|\b127\.0\.0\.1\b|\blocalhost:\d+")),
    ("an IP address", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    ("an email address", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("a file path on this Mac", re.compile(r"/Users/[^\s)\"']+|~/(?:Documents|Desktop|Library)\b")),
    ("a phone number", re.compile(r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)")),
]


def privacy_flags(text):
    flags, found = [], set()
    for label, rx in PRIVACY:
        for m in rx.finditer(text):
            hit = m.group(0)
            if hit in found:
                continue
            if label == "an IP address" and any(hit in f for f in found):
                continue
            found.add(hit)
            flags.append("%s: %s" % (label, hit))
    return flags


# ---------- planning ----------

def plan_post(src, repo, title=None, date=None):
    if not src.is_file():
        raise Stop("No file at %s" % src)
    if src.suffix.lower() not in (".md", ".markdown", ".mdown", ".txt"):
        raise Stop("%s is not a markdown file." % src.name)
    text = src.read_text(encoding="utf-8")
    fm, raw_fm, body = split_front_matter(text)

    # title: option, front matter, first H1, file name
    h1 = re.match(r"^\s*#\s+(.+?)\s*#*\s*(?:\r?\n|$)", body)
    t = title or fm.get("title") or (h1.group(1).strip() if h1 else None)
    if not t:
        t = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", src.stem).replace("-", " ").replace("_", " ").strip().title()
    if h1 and h1.group(1).strip() == t:
        body = body[h1.end():].lstrip("\n")  # the layout prints the title already

    slug = slugify(fm.get("slug") or t)

    # an existing post with this slug is updated in place
    posts_dir = repo / "_posts"
    existing = sorted(posts_dir.glob("????-??-??-%s.md" % slug)) if posts_dir.is_dir() else []
    existing_date = parse_date(existing[0].name) if existing else None

    d = parse_date(date) if date else None
    if date and not d:
        raise Stop("Date must look like 2026-11-17, got %r." % date)
    d = d or parse_date(fm.get("date", "")) or existing_date or dt.date.today()
    if existing and existing_date != d:
        raise Stop("A post called \"%s\" is already on the site, dated %s (%s). "
                   "Give this one a different title, or the same date to update it."
                   % (t, existing_date, existing[0].name))

    body, copies, missing = collect_images(body, src.parent, slug)

    # front matter: keep HG's own keys, set layout and title, drop date/slug (the file name holds them)
    keep = []
    for line in raw_fm:
        km = re.match(r"^([A-Za-z0-9_-]+):", line)
        key = km.group(1) if km else None
        if key in ("layout", "title", "date", "slug"):
            continue
        if not km and keep == [] and not line.strip():
            continue
        keep.append(line)
    out = "---\nlayout: post\ntitle: %s\n" % yaml_str(t)
    if keep:
        out += "\n".join(keep).rstrip() + "\n"
    out += "---\n" + body.rstrip() + "\n"

    fname = "%s-%s.md" % (d.isoformat(), slug)
    warnings = []
    if missing:
        warnings.append("Images not found: " + ", ".join(missing))
    if d > dt.date.today():
        warnings.append("The date %s is in the future: GitHub will not show the post until then." % d)
    if str(fm.get("published", "")).lower() == "false":
        warnings.append("The file says published: false, so the site will hide it.")
    flags = privacy_flags(body + "\n" + t)
    return {
        "src": src, "title": t, "date": d, "slug": slug, "fname": fname,
        "post_path": posts_dir / fname, "content": out, "copies": copies,
        "asset_dir": repo / "assets" / "blog" / slug,
        "url": "%s/blog/%04d/%02d/%02d/%s/" % (SITE_URL, d.year, d.month, d.day, slug),
        "update": bool(existing), "missing": missing, "warnings": warnings, "privacy": flags,
    }


def summary(p):
    lines = [
        ("Updates the post already on the site." if p["update"] else "A new post."),
        "Date: %s" % p["date"].strftime("%B %-d, %Y"),
        "Address: %s" % p["url"],
        "File: _posts/%s" % p["fname"],
        "Images: %d copied to assets/blog/%s/" % (len(p["copies"]), p["slug"]) if p["copies"] else "Images: none",
    ]
    if p["privacy"]:
        lines.append("")
        lines.append("Check before it goes online:")
        lines += ["  - " + f for f in p["privacy"][:8]]
        if len(p["privacy"]) > 8:
            lines.append("  - and %d more" % (len(p["privacy"]) - 8))
    if p["warnings"]:
        lines.append("")
        lines += ["Warning: " + w for w in p["warnings"]]
    return "\n".join(lines)


# ---------- preview ----------

def write_preview(p, repo, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    _, _, body = split_front_matter(p["content"])
    for src, name in p["copies"]:
        shutil.copy2(src, out_dir / name)
    body = body.replace("/assets/blog/%s/" % p["slug"], "")
    css = (repo / "assets" / "style.css").read_text(encoding="utf-8")
    page = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Preview: %s</title>
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=JetBrains+Mono:wght@500;600&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,700;1,8..60,400&display=swap" rel="stylesheet">
<style>%s</style>
<script src="https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js"></script></head>
<body><nav class="top"><a class="home" href="#">heath<span>.</span>dog</a><a href="#">OOTP</a><a class="on" href="#">Blog</a><a href="#">Portfolio</a></nav>
<main><p style="font:600 .7rem/1 monospace;color:#c33;letter-spacing:.1em">LOCAL PREVIEW (the site renders with kramdown; small differences are possible)</p>
<p class="post-date">%s</p><h1>%s</h1><article id="a"></article><footer><a href="#">All posts</a></footer></main>
<script id="md" type="text/plain">%s</script>
<script>document.getElementById('a').innerHTML = marked.parse(document.getElementById('md').textContent);</script>
</body></html>""" % (html.escape(p["title"]), css, p["date"].strftime("%B %-d, %Y"),
                     html.escape(p["title"]), body.replace("</script", "<\\/script"))
    f = out_dir / "index.html"
    f.write_text(page, encoding="utf-8")
    return f


# ---------- git ----------

def git(repo, *args, check=True):
    r = subprocess.run(["git", "-C", str(repo)] + list(args), capture_output=True, text=True)
    if check and r.returncode != 0:
        raise Stop("git %s failed:\n%s" % (" ".join(args), (r.stderr or r.stdout).strip()))
    return r.stdout.strip()


def publish(p, repo, log):
    if git(repo, "rev-parse", "--abbrev-ref", "HEAD") != "main":
        raise Stop("The site repo is not on its main branch; publishing stopped.")
    log("Getting the latest site from GitHub...")
    git(repo, "pull", "--rebase", "--autostash", "--quiet")

    p["post_path"].parent.mkdir(parents=True, exist_ok=True)
    p["post_path"].write_text(p["content"], encoding="utf-8")
    paths = [str(p["post_path"].relative_to(repo))]
    if p["copies"]:
        p["asset_dir"].mkdir(parents=True, exist_ok=True)
        for src, name in p["copies"]:
            shutil.copy2(src, p["asset_dir"] / name)
        paths.append(str(p["asset_dir"].relative_to(repo)))

    git(repo, "add", "--", *paths)
    if not git(repo, "diff", "--cached", "--name-only", "--", *paths):
        log("Nothing changed: the post on the site already matches this file.")
        return False
    verb = "Update" if p["update"] else "Post"
    git(repo, "commit", "--quiet", "-m", "Blog: %s %s" % (verb.lower(), p["title"]), "--", *paths)
    log("Pushing to GitHub...")
    git(repo, "push", "--quiet")
    return True


def wait_live(url, title, log, timeout=300):
    """Poll until the page answers and carries the title (an update must show the new text)."""
    log("Waiting for GitHub Pages to build (usually a minute or two)...")
    end = time.time() + timeout
    while time.time() < end:
        try:
            req = urllib.request.Request(url + "?t=%d" % time.time(), headers={"Cache-Control": "no-cache"})
            with urllib.request.urlopen(req, timeout=15) as r:
                page = r.read().decode("utf-8", "replace")
                if r.status == 200 and (title in page or html.escape(title, quote=False) in page):
                    return True
        except Exception:
            pass
        time.sleep(10)
    return False


# ---------- Mac dialogs ----------

def osa(script):
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def q(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def notify(msg):
    osa("display notification %s with title \"Blog Publisher\"" % q(msg))


def alert(msg, title="Blog Publisher"):
    osa("display dialog %s with title %s buttons {\"OK\"} default button \"OK\"" % (q(msg), q(title)))


def ask(p):
    """Title field + summary; returns (button, title)."""
    icon = "caution" if (p["privacy"] or p["warnings"]) else "note"
    rc, out = osa(
        "set r to display dialog %s default answer %s with title \"Blog Publisher\" "
        "buttons {\"Cancel\", \"Preview\", \"Publish\"} default button \"Publish\" "
        "cancel button \"Cancel\" with icon %s\n"
        "return (button returned of r) & linefeed & (text returned of r)"
        % (q("Title (edit if you like):\n\n" + summary(p)), q(p["title"]), icon))
    if rc != 0:
        return "Cancel", p["title"]
    button, _, title = out.partition("\n")
    return button, title.strip() or p["title"]


def run_gui(src, repo, args):
    try:
        p = plan_post(src, repo, args.title, args.date)
        while True:
            button, title = ask(p)
            if button == "Cancel":
                return 1
            if title != p["title"]:
                p = plan_post(src, repo, title, args.date)
                continue  # show the new address before anything goes out
            if button == "Preview":
                f = write_preview(p, repo, Path("/tmp") / "heathdog-preview" / p["slug"])
                subprocess.run(["open", str(f)])
                continue
            if p["missing"]:
                alert("Some images could not be found, so nothing was published:\n\n" + "\n".join(p["missing"]))
                return 1
            break
        if not publish(p, repo, notify):
            alert("Nothing changed: the post on the site already matches this file.")
            return 0
        if args.no_wait:
            notify("Pushed. It will be live at %s in a minute or two." % p["url"])
            return 0
        if wait_live(p["url"], p["title"], lambda m: None):
            notify("Live: " + p["title"])
            subprocess.run(["open", p["url"]])
        else:
            alert("Pushed, but the page was not live after 5 minutes. GitHub may still be building; "
                  "check https://github.com/Heathd0g/Heathd0g.github.io/actions\n\n" + p["url"])
        return 0
    except Stop as e:
        alert(str(e))
        return 1


def run_cli(src, repo, args):
    try:
        p = plan_post(src, repo, args.title, args.date)
    except Stop as e:
        print("STOP:", e)
        return 1
    print("Title:", p["title"])
    print(summary(p))
    if args.dry_run:
        print("\n--- %s ---\n%s" % (p["fname"], p["content"]))
        print("DRY RUN: nothing written.")
        return 0
    if p["missing"]:
        print("STOP: images missing; nothing published.")
        return 1
    if not args.yes:
        if input("\nPublish? [y/N] ").strip().lower() != "y":
            print("Not published.")
            return 1
    try:
        if not publish(p, repo, print):
            return 0
    except Stop as e:
        print("STOP:", e)
        return 1
    if args.no_wait:
        print("Pushed:", p["url"])
        return 0
    if wait_live(p["url"], p["title"], print):
        print("Live:", p["url"])
        return 0
    print("Pushed, but not live after 5 minutes:", p["url"])
    return 1


def main():
    ap = argparse.ArgumentParser(description="Publish a markdown file to the heath.dog blog.")
    ap.add_argument("file", nargs="?")
    ap.add_argument("--repo", default=str(DEFAULT_REPO))
    ap.add_argument("--gui", action="store_true", help="Mac dialogs (the app uses this)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--no-wait", action="store_true")
    ap.add_argument("--title")
    ap.add_argument("--date")
    args = ap.parse_args()
    repo = Path(args.repo).expanduser().resolve()
    if not (repo / "_config.yml").is_file():
        print("STOP: %s is not the site repo." % repo)
        return 1
    if not args.file:
        ap.print_help()
        return 1
    src = Path(args.file).expanduser().resolve()
    return run_gui(src, repo, args) if args.gui else run_cli(src, repo, args)


if __name__ == "__main__":
    sys.exit(main())
