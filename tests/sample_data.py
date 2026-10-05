"""Invented complaint rows for tests and screenshots. Dates are relative to today so nothing looks stale.

Every company, device and person here is fictional. The rows use the exact decisions.csv shape that
vigil.process() writes (vigil.FIELDS), so the console reads them like real output."""
import csv, datetime as dt, os, shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIELDS = ["time", "id", "received", "device", "priority", "score", "distress", "decision", "category",
          "reason", "deadline_days", "due_date", "confidence", "missing", "duplicate_of", "status", "text",
          "product_code", "memory", "failure_mode", "source"]


def _row(i, days_ago, device, priority, score, decision, category, reason, deadline, due_in, conf, text,
         status="PENDING_REVIEW", missing="", failure_mode="other", memory="", distress=0, source="replay", product_code="BZD"):
    today = dt.date.today()
    processed = dt.datetime.combine(today, dt.time(9, 12)) - dt.timedelta(days=days_ago, minutes=7 * i)
    due = (today + dt.timedelta(days=due_in)).isoformat() if due_in is not None else ""
    return dict(time=processed.isoformat(timespec="seconds"), id=f"NW-{24000 + i}", received=(today - dt.timedelta(days=days_ago)).strftime("%Y%m%d"),
                device=device, priority=priority, score=score, distress=distress, decision=decision, category=category, reason=reason,
                deadline_days=deadline or "", due_date=due, confidence=conf, missing=missing, duplicate_of="", status=status, text=text,
                product_code=product_code, memory=memory, failure_mode=failure_mode, source=source)


def sample_rows():
    """10 rows covering every state the console shows: reportable (30-day and 5-day), needs info, not reportable,
    approved, info requested, due today, under 7 days, overdue, and a recurring failure mode."""
    cpap = "AeroFlow A200 CPAP"
    return [
        _row(1, 8, cpap, "URGENT", 21, "REPORTABLE", "SERIOUS_INJURY",
             "The device may have caused or contributed to a serious injury (hospital visit for breathing difficulty) under 21 CFR 803.50(a)(1).",
             30, 22, 91, "Patient woke at night unable to breathe through the mask; black particles were found in the humidifier chamber. Taken to the emergency department and kept overnight.",
             missing="lot number; serial number", failure_mode="material degradation/particles", distress=2,
             memory="3 prior complaints on AEROFLOW (top issue: material degradation/particles, last: 2 Sep 2026)"),
        _row(2, 2, "ThermaCare T40 warming blanket", "URGENT", 24, "REPORTABLE", "SERIOUS_INJURY",
             "Fire and smoke from the device is a malfunction likely to cause serious injury if it recurs; remedial action is needed under 21 CFR 803.53.",
             5, 3, 88, "Blanket controller began smoking during use and scorched the bedding. The patient suffered a minor burn to the forearm and was treated on the ward. Unit retained for inspection.",
             missing="controller serial number", failure_mode="electrical/shock/fire", distress=3),
        _row(3, 32, "PulseGuard P1 infusion pump", "HIGH", 12, "REPORTABLE", "MALFUNCTION",
             "Over-infusion is a malfunction that would be likely to cause serious injury if it recurred, 21 CFR 803.50(a)(2).",
             30, -2, 84, "Pump delivered a bolus roughly twice the programmed rate for about ten minutes before the occlusion alarm stopped it. No injury reported; patient observed for six hours.",
             missing="firmware version; event date", failure_mode="pressure/airflow"),
        _row(4, 30, cpap, "HIGH", 11, "REPORTABLE", "MALFUNCTION",
             "Foam degradation inside the air path is a malfunction likely to cause serious injury on recurrence, 21 CFR 803.50(a)(2).",
             30, 0, 79, "Customer reports grey foam dust in the tubing after six months of use and a persistent cough. Device still in use; replacement requested.",
             missing="patient age; medical treatment", failure_mode="material degradation/particles",
             memory="2 prior complaints on AEROFLOW (top issue: material degradation/particles, last: 11 Aug 2026)"),
        _row(5, 24, "NightSense S3 glucose monitor", "HIGH", 9, "REPORTABLE", "MALFUNCTION",
             "Readings 60 mg/dL below the laboratory value could lead to a dosing error and serious injury if repeated, 21 CFR 803.50(a)(2).",
             30, 6, 76, "Sensor read 95 mg/dL while a fingerstick and laboratory draw read 158 mg/dL. The patient delayed a correction dose. No harm reported.",
             missing="sensor lot number", failure_mode="software"),
        _row(6, 5, "CardioLink C2 bedside monitor", "NORMAL", 6, "NEEDS_INFO", "MALFUNCTION",
             "An alarm that did not sound could be reportable; the outcome and alarm settings are not stated, so facts are pending under 21 CFR 803.50.",
             30, 25, 58, "Nurse reports the low-heart-rate alarm did not sound overnight. It is unclear whether the limit was set or whether the patient was affected.",
             missing="patient outcome; alarm limit settings; event date", failure_mode="alarm failure"),
        _row(7, 12, "Veloci V1 home ventilator", "HIGH", 10, "NEEDS_INFO", "MALFUNCTION",
             "Unexpected shutdown of a life-supporting device is likely reportable; the duration and backup response are not stated.",
             30, 18, 63, "Ventilator shut down without warning while on mains power and restarted after about a minute. Caregiver switched to the backup unit.",
             status="INFO REQUESTED by M. Okafor", missing="duration of shutdown; patient condition", failure_mode="power/shutdown"),
        _row(8, 15, cpap, "URGENT", 18, "REPORTABLE", "SERIOUS_INJURY",
             "Hospitalisation after inhaling particles from the device is a serious injury under 21 CFR 803.50(a)(1).",
             30, 15, 93, "Patient admitted for two nights with bronchitis; the pulmonologist linked it to black particles found in the CPAP tubing and mask.",
             status="APPROVED by A. Rivera", missing="", failure_mode="material degradation/particles", distress=1,
             memory="4 prior complaints on AEROFLOW (top issue: material degradation/particles, last: 20 Sep 2026)"),
        _row(9, 3, "PulseGuard P1 infusion pump", "NORMAL", 3, "NOT_REPORTABLE", "NONE",
             "A cosmetic crack in the housing with no effect on pump function does not meet the reporting threshold of 21 CFR 803.50.",
             None, None, 90, "Hairline crack on the rear of the pump housing noticed during cleaning. Pump passed its self-test and continues to operate normally.",
             status="LOGGED", failure_mode="mechanical", source="csv"),
        _row(10, 1, "NightSense S3 glucose monitor", "NORMAL", 2, "NOT_REPORTABLE", "NONE",
             "The app showed a connectivity notice and reconnected; no reading was missed and no patient effect is stated. Not reportable under 21 CFR 803.",
             None, None, 86, "Mobile app lost Bluetooth connection for about four minutes and reconnected on its own. Readings resumed with no gap in the log.",
             status="LOGGED", failure_mode="software", source="rest"),
    ]


def actions_rows():
    today = dt.date.today()
    return [
        {"time": dt.datetime.combine(today - dt.timedelta(days=14), dt.time(10, 41)).isoformat(timespec="seconds"), "id": "NW-24008", "kind": "approve", "by": "A. Rivera"},
        {"time": dt.datetime.combine(today - dt.timedelta(days=11), dt.time(15, 3)).isoformat(timespec="seconds"), "id": "NW-24007", "kind": "info", "by": "M. Okafor"},
    ]


def write_sample_dir(data_dir, with_pdf=True):
    """Create a data folder the console can point at (VIGIL_DIR): decisions.csv, actions.csv, a copy of vigil.py
    and demo_set.csv (the console imports vigil.py from VIGIL_DIR), and one drafted PDF. Returns the row ids."""
    os.makedirs(data_dir, exist_ok=True)
    for name in ("vigil.py", "demo_set.csv", "philips_chart.png"):
        src = os.path.join(ROOT, name)
        if os.path.exists(src):
            shutil.copy(src, os.path.join(data_dir, name))
    rows = sample_rows()
    with open(os.path.join(data_dir, "decisions.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS); w.writeheader(); w.writerows(rows)
    with open(os.path.join(data_dir, "actions.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["time", "id", "kind", "by"]); w.writeheader(); w.writerows(actions_rows())
    if with_pdf:
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("vigil_sample", os.path.join(data_dir, "vigil.py"))
            v = importlib.util.module_from_spec(spec); spec.loader.exec_module(v)
            if v.FPDF is not None:
                v.REPORTS = os.path.join(data_dir, "reports")
                r = rows[0]
                c = dict(id=r["id"], text=r["text"], device=r["device"], manufacturer="Northwind Medical", event_date="",
                         received=r["received"], generic_name="CPAP", product_code="BZD", product_problems="", manufacturer_narrative="")
                fields = {"A2_age": "67", "A3_sex": "F", "B1_event_type": "BOTH", "B2_outcomes": ["Hospitalization (initial or prolonged)"],
                          "B3_date_of_event": "UNKNOWN", "B5_event_description": r["text"], "D1_brand_name": r["device"],
                          "D2_common_device_name": "CPAP", "D2b_product_code": "BZD", "D3_manufacturer": "Northwind Medical",
                          "D4_model": "A200", "D4_lot": "UNKNOWN", "D4_serial": "UNKNOWN", "H1_type_of_reportable_event": "SERIOUS_INJURY",
                          "H3_device_evaluated": "NO", "H10_manufacturer_narrative": "Complaint received; device not yet returned for evaluation.",
                          "follow_up_questions": ["What is the device serial number?", "What treatment did the patient receive?"],
                          "B4_date_of_report": dt.date.today().isoformat(), "G7_report_type": "30-day",
                          "G4_date_received_by_manufacturer": dt.date.today().isoformat(), "G4_note": ""}
                v.render_mdr_pdf(c, {**r, "awareness": dt.date.today().isoformat()}, fields)
        except Exception as e:  # the PDF is a nice-to-have for screenshots
            print("sample PDF skipped:", e)
    return [r["id"] for r in rows]


if __name__ == "__main__":
    import sys
    print(write_sample_dir(sys.argv[1] if len(sys.argv) > 1 else "sample_data"))
