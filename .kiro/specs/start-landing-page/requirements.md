# Requirements Document

## Introduction

A public landing page at `/start` for the Thirty console. The page carries a top bar (brand mark, in-page nav, two call-to-action pills), a pitch-deck hero (large Manrope headline, one sentence, decorative ribbon and badge art), then offers three doors: the reporter front door (`/report`), the quality-team console (`/`), and the device readiness check (`/readiness`). It needs no login, works in the public demo, and is exempt from the first-run setup redirect and from the public-demo locks. It uses the same dark pitch-deck look as the readiness page (thirty.css tokens, ribbon background, glass cards) in a centred 1440px column that also works at 390px width.

In the public demo only, the first visit to `/` in a browser session redirects to `/start`, so judges land on the landing page; the console stays one click away. The first visit is tracked with a plain browser-session cookie, not the Flask session.

Scope is `/start` and the `/` redirect only. No link back to `/start` is added to the console or the public-demo banner.

## Glossary

- **Console**: the Flask web application in `dashboard_v2/app.py`.
- **Start_Page**: the page served by the Console at `GET /start`, rendered from a Jinja template.
- **Home_Route**: the Console route at `GET /` that renders the quality-team console (`home.html`).
- **Public_Demo_Mode**: the Console state in which the `PUBLIC_DEMO` module global in `dashboard_v2/app.py` is true.
- **Setup_Redirect**: the Console `before_request` handler (`_first_run`) that redirects requests to `/setup` when setup is required, unless the request path starts with a prefix in `SETUP_FREE`.
- **Demo_Lock**: the Console `before_request` handler (`_public_demo_lock`) that blocks endpoints listed in `LOCKED_ENDPOINTS` while in Public_Demo_Mode.
- **Start_Cookie**: a browser-session cookie named `thirty_start_seen` with value `1`, set with no `Expires` or `Max-Age` attribute and not signed with the Flask secret.
- **Door_Card**: one of three large glass cards on the Start_Page, each a single link to one destination.
- **Demo_Strip**: the small text strip on the Start_Page that states the demo terms and links to the repository and the build write-up.
- **Dial_Image**: the 30-day dial image at `/static/thirty/img/brand/thirty-dial-30-days.webp`.
- **Repo_URL**: `https://github.com/jossefuggg/thirty`.
- **Submission_URL**: the GitHub URL of `docs/hackachusetts/SUBMISSION.md` on the `hackachusetts` branch of the Repo_URL repository.

## Requirements

### Requirement 1: Public route

**User Story:** As a visitor to the public demo, I want a landing page that opens without login or setup, so that I can see what Thirty is before choosing where to go.

#### Acceptance Criteria

1. WHEN the Console receives `GET /start`, THE Console SHALL respond with HTTP status 200 and the rendered Start_Page.
2. WHILE setup is required, WHEN the Console receives `GET /start`, THE Setup_Redirect SHALL pass the request through to the Start_Page without redirecting to `/setup`.
3. WHILE the Console is in Public_Demo_Mode, WHEN the Console receives `GET /start`, THE Demo_Lock SHALL pass the request through to the Start_Page.
4. THE Console SHALL serve the Start_Page without requiring any user authentication.

### Requirement 2: Hero

**User Story:** As a visitor, I want a short statement of what Thirty does, so that I understand the product in a few seconds.

#### Acceptance Criteria

1. THE Start_Page SHALL show the label text "Thirty" above the headline.
2. THE Start_Page SHALL show the headline text "Every complaint, on the clock." in Instrument Serif.
3. THE Start_Page SHALL show the sentence "Medical device complaint reporting: complete at the bedside, decided on time, approved by a named person." below the headline.
4. THE Start_Page SHALL show the Dial_Image with a non-empty `alt` attribute, beside the hero text on wide viewports and above it in the single-column layout.

### Requirement 3: Door cards

**User Story:** As a visitor, I want three clear doors, so that I can go straight to the part of Thirty that matters to me.

#### Acceptance Criteria

1. THE Start_Page SHALL show exactly three Door_Cards.
2. THE Start_Page SHALL show a Door_Card titled "Report a device problem" that states the page is for nurses, patients and staff, states that 4 languages are available, and links to `/report`.
3. THE Start_Page SHALL show a Door_Card titled "See what the quality team sees" that describes the Console and links to `/`.
4. THE Start_Page SHALL show a Door_Card titled "Is your feature a medical device?" that links to `/readiness`.
5. THE Start_Page SHALL make the whole area of each Door_Card a single link to the Door_Card destination.

### Requirement 4: Demo strip

**User Story:** As a hackathon judge, I want the demo terms and source links on the landing page, so that I know the data is invented and can find the code and the build write-up.

#### Acceptance Criteria

1. THE Start_Page SHALL show a Demo_Strip with the text "Public demo · invented sample data · nothing is sent to the FDA".
2. THE Demo_Strip SHALL contain a link to the Repo_URL.
3. THE Demo_Strip SHALL contain a link labelled "How we built it with Kiro" to the Submission_URL.
4. THE Demo_Strip SHALL open both external links in a new browser tab with `rel="noopener"`.

### Requirement 5: Visual style and layout

**User Story:** As a visitor, I want the landing page to match the pitch-deck look of the rest of the demo, so that the product feels consistent.

#### Acceptance Criteria

1. THE Start_Page SHALL use the dark glass style of the readiness page, built from the existing `thirty.css` tokens, with no new CSS framework and no external stylesheet beyond `thirty.css`.
2. THE Start_Page SHALL render the ribbon background markup (`bg-fx` with three `glow` elements and one `ribbon` element) with `aria-hidden="true"`.
3. THE Start_Page SHALL place content in a horizontally centred column with a maximum width of 1440px.
4. WHILE the viewport width is 390px, THE Start_Page SHALL show the hero, the three Door_Cards and the Demo_Strip in a single column with no horizontal scrolling.
5. THE Start_Page SHALL use Coral for at most one key action and Amber for no element.

### Requirement 6: First-visit cookie

**User Story:** As the demo operator, I want the Console to remember that a visitor has seen the landing page, so that the redirect happens only once per browser session.

#### Acceptance Criteria

1. WHEN the Console renders the Start_Page, THE Console SHALL set the Start_Cookie on the response.
2. THE Console SHALL set the Start_Cookie with path `/`, no `Expires` attribute and no `Max-Age` attribute.
3. THE Console SHALL track the first visit using only the Start_Cookie, without reading or writing the Flask session.

### Requirement 7: Public-demo redirect from the console

**User Story:** As a hackathon judge, I want my first visit to the demo to land on the landing page, so that I see the three doors before the console.

#### Acceptance Criteria

1. WHILE the Console is in Public_Demo_Mode, WHEN the Console receives `GET /` without the Start_Cookie, THE Home_Route SHALL respond with an HTTP redirect to `/start`.
2. WHILE the Console is in Public_Demo_Mode, WHEN the Console receives `GET /` with the Start_Cookie, THE Home_Route SHALL render the Console.
3. WHILE the Console is not in Public_Demo_Mode, WHEN the Console receives `GET /`, THE Home_Route SHALL render the Console regardless of the Start_Cookie.

### Requirement 8: Tests

**User Story:** As a developer, I want automated tests for the landing page, so that the demo entry point keeps working.

#### Acceptance Criteria

1. THE test suite SHALL verify that `GET /start` returns HTTP status 200 when the Console is not in Public_Demo_Mode.
2. THE test suite SHALL verify that `GET /start` returns HTTP status 200 when the Console is in Public_Demo_Mode.
3. THE test suite SHALL verify that the Start_Page response contains links to `/report`, `/` and `/readiness`.
4. THE test suite SHALL verify that `GET /` redirects to `/start` in Public_Demo_Mode without the Start_Cookie and renders the Console with the Start_Cookie.
5. WHEN `pytest` runs after the change, THE test suite SHALL report zero failures.
