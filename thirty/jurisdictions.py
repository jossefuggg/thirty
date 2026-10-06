"""Reporting clocks per jurisdiction, from the manufacturer's awareness date.

Deterministic: no model involved. The rules encoded here (sources in docs/COMPLIANCE.md):

    US  21 CFR 803.50 / 803.53     30 calendar days; 5 work days when remedial action is needed
                                   to prevent an unreasonable risk of substantial harm to public health.
    EU  MDR 2017/745 Art. 87(3-5)  2 days for a serious public health threat; 10 days for death or an
                                   unanticipated serious deterioration; 15 days for any other serious incident.
    UK  SI 2024/1368 (GB PMS)      same 2 / 10 / 15 day ladder as the EU.
    CA  SOR/98-282 s.59            10 days for death or serious deterioration; 30 days when a recurrence
                                   could cause death or serious deterioration (malfunction).

Weekends count for calendar-day clocks. Public holidays are not modelled; the 5-day US clock counts Mon-Fri.
"""
import datetime as dt

JURISDICTIONS = {
    "US": {"name": "US FDA", "rule": "21 CFR 803", "portal": "FDA ESG (eMDR)"},
    "EU": {"name": "EU MDR", "rule": "MDR 2017/745 Art. 87", "portal": "Competent authority (MIR 7.3.1)"},
    "UK": {"name": "UK MHRA", "rule": "SI 2024/1368", "portal": "MORE portal"},
    "CA": {"name": "Health Canada", "rule": "SOR/98-282 s.59", "portal": "Canada Vigilance"},
}
DEFAULT = ["US"]
CATEGORIES = ("DEATH", "SERIOUS_INJURY", "MALFUNCTION")


def normalise(codes):
    """Keep known codes, in canonical order; US FDA is always included."""
    codes = [c.upper() for c in (codes or []) if isinstance(c, str)]
    return [c for c in JURISDICTIONS if c == "US" or c in codes]


def add_days(start, days, work=False):
    if not work:
        return start + dt.timedelta(days=days)
    d, left = start, days
    while left:
        d += dt.timedelta(days=1)
        if d.weekday() < 5:
            left -= 1
    return d


def rule_for(code, category, five_day=False, public_health_threat=False, unanticipated=False):
    """(days, work_days, basis) for one jurisdiction, or None when nothing is due there."""
    if category not in CATEGORIES:
        return None
    if code == "US":
        if five_day:
            return 5, True, "803.53 5-day report: remedial action to prevent substantial harm"
        return 30, False, "803.50 30-day report"
    if code in ("EU", "UK"):
        art = "Art. 87" if code == "EU" else "GB PMS reg."
        if public_health_threat:
            return 2, False, f"{art}: serious public health threat"
        if category == "DEATH" or (category == "SERIOUS_INJURY" and unanticipated):
            return 10, False, f"{art}: death or unanticipated serious deterioration"
        return 15, False, f"{art}: serious incident"
    if code == "CA":
        if category in ("DEATH", "SERIOUS_INJURY"):
            return 10, False, "s.59(1)(a): death or serious deterioration"
        return 30, False, "s.59(1)(b): recurrence could cause death or serious deterioration"
    return None


def deadlines(category, aware, enabled=None, five_day=False, public_health_threat=False, unanticipated=False, today=None):
    """Every clock that applies, earliest first. aware: date the manufacturer became aware."""
    today = today or dt.date.today()
    out = []
    for code in normalise(enabled):
        rule = rule_for(code, category, five_day, public_health_threat, unanticipated)
        if not rule:
            continue
        days, work, basis = rule
        due = add_days(aware, days, work)
        out.append({"code": code, "name": JURISDICTIONS[code]["name"], "rule": JURISDICTIONS[code]["rule"], "portal": JURISDICTIONS[code]["portal"],
                    "days": days, "work_days": work, "basis": basis, "due": due.isoformat(), "days_left": (due - today).days})
    out.sort(key=lambda d: (d["due"], d["code"] != "US"))
    return out


def awareness_from_due(due, days):
    """Invert a US due date back to the awareness date (the decisions log keeps only the due date)."""
    if days == 5:
        d, left = due, 5
        while left:
            d -= dt.timedelta(days=1)
            if d.weekday() < 5:
                left -= 1
        return d
    return due - dt.timedelta(days=days)
