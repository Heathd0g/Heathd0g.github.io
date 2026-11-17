# heath.dog

The site at https://heath.dog (GitHub Pages builds it with Jekyll on every push).

- `/` home: OOTP and Personal
- `/ootp/` the Perfect Team tools page (`ootp/index.html`)
- `/blog/` lists every post in `_posts/`; shows "coming soon" while there are none
- `/portfolio/` coming soon (`portfolio/index.html`)
- Look: the OOTP section (`/ootp/`) uses `assets/style.css` (ballpark theme; light = scorecard, dark = night game); everything else uses `assets/magazine.css` (Magazine: Playfair headlines, cobalt accent). `_layouts/default.html` picks by the page address.

## Writing a blog post

1. Make a file in `_posts/` named `YYYY-MM-DD-title.md`, e.g. `_posts/2026-11-10-hello.md`.
2. Start it with:

   ```
   ---
   layout: post
   title: "Hello"
   ---
   ```

3. Write in markdown below that, then commit and push. It shows up on /blog/ in a minute or two.

Drafts go in `_drafts/` (never published). `_drafts/example-post.md` shows the format.

## Blog Publisher (the easy way)

Drag a markdown file onto `tools/blog_publisher/Blog Publisher.app` (put it in the Dock), or double-click the app and pick a file.
It reads the title (front matter `title:`, else the first `# Heading`, else the file name) and the date (front matter `date:`, else today),
copies any local images the file links to into `assets/blog/<slug>/`, flags private addresses, emails and Mac file paths,
and shows the title, date and web address with Cancel / Preview / Publish. Publish commits only that post and its images,
pushes, waits for GitHub Pages, and opens the live page. Dropping a file with the same title again updates that post.

From a terminal: `python3 tools/blog_publisher/publish.py <file.md> --dry-run` (shows the result, writes nothing), or `--yes` to publish without dialogs.
After editing `droplet.applescript`, rebuild the app with osacompile (compile it outside ~/Documents, then `ditto --noextattr --norsrc` it back).
