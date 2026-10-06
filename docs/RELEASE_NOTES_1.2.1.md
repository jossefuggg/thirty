## Thirty 1.2.1

Unsigned builds for macOS (Apple Silicon and Intel), Windows and Linux. macOS: after installing, run `xattr -cr /Applications/Thirty.app` once, or right-click → Open.

### Changed
- **Update checks are on by default.** The app asks GitHub Releases for a newer version after start and every six hours and tells you when one exists. Until the macOS build is code-signed it opens the download page (macOS only lets a signed app replace itself); on Windows and Linux it downloads and installs on quit. Switch it off under Licence & updates.
- **Command Center** fits the window with no scrolling. The "layer" strip at the bottom is gone; its numbers now sit in the Live intake feed header. KPI cards carry a caption (next due, oldest overdue, approved this week) instead of a flat sparkline. Denser feed and decision cards: two decisions visible at laptop size, three on a large screen.
- Complaints table: failure modes on one line; Status stays visible without horizontal scrolling.

Everything from 1.2.0 (decision record, jurisdiction clocks, signed audit chain, submission pack) is included.
