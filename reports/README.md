# Reports

Each nightly run writes `YYYY-MM-DD.md`, `YYYY-MM-DD.html`, `YYYY-MM-DD.json`,
and refreshes `latest.html` here. The GitHub Action commits them automatically.

This directory starts empty on purpose. To see what a report looks like without
waiting for a live run:

    python -m buffett.run --offline --output-dir /tmp/demo && open /tmp/demo/latest.html

That uses synthetic filers, so nothing in it is a real company or a real price.
