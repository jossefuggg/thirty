# Thirty brand kit v1

Everything the website needs, in one folder.

brand-sheet.html / .png / .pdf   The one-page chart: logo versions, clear space, don'ts, colours, type, buttons, pills.
components.html / .png           Live UI: nav, hero, every button and state, pills, the ring, deadline bars, inputs, cards. Open it in a browser and copy the markup.
css/thirty.css                   Tokens + all components. Link it and use the class names below.
colors/                          colors.css (CSS variables only), colors.json, swatches.svg.
logo/svg/                        Vector logos. Text is outlined, so they render the same everywhere.
logo/png/                        PNG exports: transparent @2x, on-colour versions, app icon and favicons.
fonts/                           Manrope 500/600/700/800 and Instrument Serif 400 (woff2, OFL licence included).

## Which logo where
- Website header, footer, email signatures: thirty-lockup-descriptor.svg (mark · Thirty | descriptor). Below 360px wide, use thirty-lockup.svg.
- Nav on small screens, slides, documents: thirty-lockup.svg. On dark: thirty-lockup-reverse.svg.
- Favicon and app icon: favicon.svg, favicon-32/64/192.png, apple-touch-icon-180.png, thirty-app-icon-1024.png.
- Social avatars: thirty-lockup-stacked.svg or the app icon.
- On a coral background: thirty-mark-on-coral.svg (the window turns ink).
- One colour (print, stamps): thirty-mark-mono-ink.svg.

## Colours
Paper #F7F5F0 (ground) · Ink #15181D (text, primary buttons, the mark) · Coral #FF5A3C (the accent: the five-day window, one key action per screen, deadlines, REPORTABLE, cost-of-failure numbers) · Slate #5B6470 (secondary text) · Stone #DDD8CE (lines, tracks, disabled) · Amber #F2B134 (NEEDS INFO only).
Hover: ink #2A2F37, coral #E84E31. Coral for small text on paper: #C2381A (coral itself fails contrast below 48px). On ink: secondary text #B9BEC6, lines #3A414B.
Dark mode: add data-theme="dark" to <html> (or class t-dark to a block); paper and ink swap.

## Type
Instrument Serif 400 for headlines and big numbers only. Manrope for everything else: 500 body, 700 buttons and labels, 800 wordmark, pills and h3. Classes: .t-display .t-h2 .t-h3 .t-lead .t-body .t-small .t-eyebrow .t-number.

## Buttons (css/thirty.css)
.btn .btn-primary      ink, the default
.btn .btn-accent       coral with ink text, ONE per screen (Approve, Book a demo)
.btn .btn-secondary    outlined
.btn .btn-ghost        text only, for rows and toolbars
.btn .btn-danger       coral outline, fills on hover (Override)
sizes: .btn-sm (36) default (44) .btn-lg (56) · .btn-block · disabled attribute for the disabled state
Spec: radius 10px, Manrope 700 15px, 2px border, hover darkens, active moves 1px down, focus = coral ring.

## Pills and badges
.pill .pill-reportable | .pill-needs-info | .pill-not-reportable | .pill-approved | .pill-five-day | .pill-neutral · .pill-lg
.badge-local  the "0 bytes to cloud AI" badge

## Clocks
.ring + the SVG in components.html (track stone, elapsed ink, first five days coral)
.deadline .deadline-track .deadline-fill(.is-urgent) .deadline-value(.is-urgent)

## Voice
Plain, specific, numbers first, no drama. "Thirty drafts; a human files." Never: "the only offline tool", "fully automated", "replaces your QMS", "Thirty submits to the FDA".
