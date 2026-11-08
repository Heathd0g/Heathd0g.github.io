# heath.dog

The site at https://heath.dog (GitHub Pages builds it with Jekyll on every push).

- `/` home: OOTP and Personal
- `/ootp/` the Perfect Team tools page (`ootp/index.html`)
- `/blog/` lists every post in `_posts/`; shows "coming soon" while there are none
- `/portfolio/` coming soon (`portfolio/index.html`)
- Look: `assets/style.css` (ballpark theme; light = scorecard, dark = night game), layout in `_layouts/`

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
