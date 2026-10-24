# Implementation Plan: start-landing-page

## Overview

Add a public landing page at `GET /start` to the Flask console (`dashboard_v2/app.py` + `dashboard_v2/templates/start.html`) and, in the public demo only, redirect the first `GET /` of a browser session to it using the plain cookie `thirty_start_seen=1`. Python 3.11, Flask + Jinja, no new dependency, no JavaScript on the page, no Flask session use. Code and copy are given in full in design.md; follow it exactly.

## Tasks

- [ ] 1. Add the `/start` route and the public-demo redirect in `dashboard_v2/app.py`
  - [-] 1.1 Wire the route, cookie and home guard
    - Add `make_response` to the existing `from flask import ...` line
    - Append `"/start"` to the `SETUP_FREE` tuple; leave `LOCKED_ENDPOINTS` unchanged
    - Next to `home()`, add the constants `START_COOKIE = "thirty_start_seen"`, `REPO_URL` and `SUBMISSION_URL` (values from design.md)
    - Add the pure helper `_needs_start(public_demo, cookies)` returning `bool(public_demo) and cookies.get(START_COOKIE) != "1"`
    - Add `@app.route("/start") start_page()`: render `start.html` with `page="start"`, `title="Start"`, `repo_url`, `submission_url`; wrap in `make_response`; call `resp.set_cookie(START_COOKIE, "1", path="/", samesite="Lax", httponly=True)` with no `max_age` or `expires`
    - In `home()`, return `redirect("/start")` first when `_needs_start(PUBLIC_DEMO, request.cookies)` is true; read the module global at request time
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 6.1, 6.2, 6.3, 7.1, 7.2, 7.3_

- [ ] 2. Create the landing page template
  - [-] 2.1 Write `dashboard_v2/templates/start.html` per the design skeleton
    - `{% extends "base.html" %}`; set `content_class` to `st-page`; empty the `page_header` block
    - Do not add a `bg-fx` div; `base.html` already renders it with `aria-hidden="true"`
    - In the `head` block `<style>`, add the inline `@font-face` for "Instrument Serif" from `/static/thirty/fonts/instrument-serif-400.woff2`, plus the `st-` rules and the `.glass` rule built only from `thirty.css` tokens, including the 980px and 640px media queries
    - Hero: eyebrow "Thirty", `<h1>` "Every complaint, on the clock." in Instrument Serif, the one-sentence description, and the dial image `/static/thirty/img/brand/thirty-dial-30-days.webp` with a non-empty `alt`
    - Three door cards, each a single `<a class="st-door glass">` containing only `<span>`, `<h2>` and `<p>`: `/report` (nurses, patients and staff; 4 languages; the only `btn-accent`), `/` (`btn-secondary`), `/readiness` (`btn-secondary`)
    - Demo strip: "Public demo · invented sample data · nothing is sent to the FDA", a link to `{{ repo_url }}` and a "How we built it with Kiro" link to `{{ submission_url }}`, both with `target="_blank" rel="noopener"`
    - No `amber` token anywhere in the template; no "Never say" phrases in the copy
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.3, 5.4, 5.5_

- [ ] 3. Keep the public-demo tests working
  - [~] 3.1 Update `tests/test_public_demo.py`
    - Change the `pclient` fixture to call `c.set_cookie("thirty_start_seen", "1")` before returning the client, so the existing `GET /` tests still get 200
    - Add a round-trip test with a fresh cookie-less `public_console.app.test_client()`: `GET /` is 302 with `Location` ending in `/start`; `GET /start` is 200 and its `Set-Cookie` contains `thirty_start_seen=1`; the same client then gets 200 on `GET /`
    - _Requirements: 6.1, 7.1, 7.2, 8.2, 8.4_

- [ ] 4. Add the landing page test module
  - [~] 4.1 Write example tests in `tests/test_start_page.py`
    - Use the existing `console` / `client` fixtures from `tests/conftest.py`; toggle state with `monkeypatch.setattr(console, "PUBLIC_DEMO", ...)` and `monkeypatch.setattr(console.tsetup, "required", lambda: True)`
    - `test_start_200_normal` (1.1, 8.1); `test_start_200_public_demo`, including `"start_page" not in LOCKED_ENDPOINTS` (1.3, 8.2); `test_start_bypasses_setup`: `/start` is 200 and `/` is still 302 to `/setup` (1.2)
    - `test_start_links`: `href="/report"`, `href="/"`, `href="/readiness"` (3.2–3.4, 8.3)
    - `test_start_hero_copy`: label "Thirty" before `<h1>`, headline, sentence, dial `<img>` with non-empty `alt`, Instrument Serif `@font-face` (2.1–2.4)
    - `test_start_three_doors`: exactly 3 `class="st-door` anchors, the three titles, "nurses, patients and staff" and "4 languages", no `<a` nested inside a door (3.1–3.5)
    - `test_start_demo_strip`: strip text, Repo_URL link, "How we built it with Kiro" link to Submission_URL, both with `target="_blank"` and `rel="noopener"` (4.1–4.4)
    - `test_start_style_rules`: exactly one `<link rel="stylesheet">` and it is `thirty.css`; one `bg-fx` with `aria-hidden="true"`; the `start.html` source has one `btn-accent` and no `amber` (5.1, 5.2, 5.5)
    - `test_start_cookie_attributes`: `Set-Cookie` is `thirty_start_seen=1` with `Path=/`, no `Expires`, no `Max-Age`, and no Flask session cookie is set (6.1–6.3)
    - `test_home_redirect_public_demo`: no cookie gives 302 to `/start`, cookie `1` gives 200 (7.1, 7.2, 8.4); `test_home_normal_ignores_cookie`: 200 with and without the cookie (7.3)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.5, 6.1, 6.2, 6.3, 7.1, 7.2, 7.3, 8.1, 8.2, 8.3, 8.4_

  - [ ]* 4.2 Write property test for the start page response
    - **Property 1: The start page always renders and sets only the session start cookie**
    - Hypothesis `@settings(max_examples=100)`; take the module-level `console` fixture and set `PUBLIC_DEMO` and `tsetup.required` inside the body with `pytest.MonkeyPatch.context()`; fresh `console.app.test_client()` per example
    - Generate the public-demo flag, setup-required flag, an optional `thirty_start_seen` value (printable ASCII without `;`, `,`, `"`, `\` or whitespace) sent as a raw `Cookie` header, and a query string
    - Assert 200, Start_Page HTML, exactly one `thirty_start_seen=1` with `Path=/` and no `Expires`/`Max-Age`, and no `app.config["SESSION_COOKIE_NAME"]` cookie
    - Tag: `# Feature: start-landing-page, Property 1: The start page always renders and sets only the session start cookie`
    - **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 6.1, 6.2, 6.3**

  - [ ]* 4.3 Write property test for the console redirect
    - **Property 2: The console redirects to the start page only in the public demo without the cookie**
    - Same fixture and client setup as 4.2; setup not required
    - Generate the public-demo flag and a cookie value (absent, `"1"`, or any other allowed string)
    - Assert `GET /` is a redirect to `/start` if and only if the flag is true and the value is not `"1"`, otherwise 200; assert `console._needs_start(flag, cookies)` agrees
    - Tag: `# Feature: start-landing-page, Property 2: The console redirects to the start page only in the public demo without the cookie`
    - **Validates: Requirements 7.1, 7.2, 7.3**

- [ ] 5. Optional layout checks
  - [ ]* 5.1 Add the start page to `tools/screenshots.py` and a 390px check
    - Add `("27-start", "/start")` to the `shots` list
    - After the 1440px loop, open a 390×844 context, load `/start`, assert `document.documentElement.scrollWidth <= window.innerWidth`, and save `27-start-mobile.png`
    - _Requirements: 5.3, 5.4_

- [~] 6. Final checkpoint
  - Run `pytest` and confirm zero failures, including the updated `tests/test_public_demo.py`. Ask the user if questions arise.
  - _Requirements: 8.5_

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP.
- `tests/test_setup.py` (`/` redirects to `/setup` when setup is required) needs no change: `_needs_start` is false outside the public demo and `_first_run` runs before `home()`.
- Hypothesis rejects function-scoped fixtures inside `@given`, so the property tests use the module-level `console` fixture and patch inside the test body.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1"] },
    { "id": 1, "tasks": ["3.1", "4.1", "5.1"] },
    { "id": 2, "tasks": ["4.2"] },
    { "id": 3, "tasks": ["4.3"] }
  ]
}
```
