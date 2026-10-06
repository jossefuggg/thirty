"""Sample data for demo mode: ~40 invented complaints at rest plus 6 "incoming" ones for live replays,
a pre-written result for each (what the sample agent returns), and an invented device history.

Every company, device and person is fictional. Dates are computed from today at seed time, so the demo
never looks stale: `seed(data_dir)` rewrites decisions.csv, actions.csv, history.csv and the drafted PDFs.
Row shape = vigil.FIELDS, exactly what vigil.process() writes.
"""
import csv, datetime as dt, os, random, shutil

from . import config

MAKER = "Northwind Medical"
FIELDS = ["time", "id", "received", "device", "priority", "score", "distress", "decision", "category",
          "reason", "deadline_days", "due_date", "confidence", "missing", "duplicate_of", "status", "text",
          "product_code", "memory", "failure_mode", "source"]

DEVICES = {  # key: (device name, common name, product code)
    "AF": ("AeroFlow A200 CPAP", "CPAP", "BZD"), "PG": ("PulseGuard P1 infusion pump", "Infusion pump", "FRN"),
    "NS": ("NightSense S3 glucose monitor", "Continuous glucose monitor", "QBJ"), "TC": ("ThermaCare T40 warming blanket", "Patient warming system", "DWJ"),
    "CL": ("CardioLink C2 bedside monitor", "Patient monitor", "MWI"), "VV": ("Veloci V1 home ventilator", "Home ventilator", "NOU"),
    "LM": ("Lumen L5 pulse oximeter", "Pulse oximeter", "DQA"), "SP": ("SteriPak S9 tabletop sterilizer", "Steam sterilizer", "FLE"),
}
R, N, X = "REPORTABLE", "NEEDS_INFO", "NOT_REPORTABLE"
PEND, LOG = "PENDING_REVIEW", "LOGGED"
REVIEWERS = ["A. Rivera", "M. Okafor", "J. Lindqvist"]

# (n, device key, decision, category, status, deadline, due_in days, confidence, text, reason, missing, questions, fields)
# status: PEND | LOG | "appr" | "info" (reviewer picked round-robin). due_in None = no deadline.
CATALOGUE = [
    (1, "AF", R, "SERIOUS_INJURY", PEND, 30, 22, 91,
     "Patient woke at night unable to breathe through the mask; black particles were found in the humidifier chamber. Taken to the emergency department and kept overnight.",
     "The device may have caused or contributed to a serious injury (hospital visit for breathing difficulty) under 21 CFR 803.50(a)(1).",
     ["lot number", "serial number"], ["What is the serial number on the base of the unit?", "What treatment did the patient receive in the emergency department?", "Is the device available for return?"],
     {"A2_age": "67", "A3_sex": "F", "B2_outcomes": ["Hospitalization (initial or prolonged)"], "D4_model": "A200", "H3_device_evaluated": "NO"}),
    (2, "TC", R, "SERIOUS_INJURY", PEND, 5, 3, 88,
     "Blanket controller began smoking during use and scorched the bedding. The patient suffered a minor burn to the forearm and was treated on the ward. Unit retained for inspection.",
     "Fire and smoke from the device is a malfunction likely to cause serious injury if it recurs; remedial action is needed under 21 CFR 803.53.",
     ["controller serial number"], ["Can you provide the controller serial number?", "Was the controller plugged into a hospital-grade outlet?", "How long had the blanket been running?"],
     {"A2_age": "54", "A3_sex": "M", "B2_outcomes": ["Required intervention to prevent permanent impairment/damage"], "D4_model": "T40", "H3_device_evaluated": "YES"}),
    (3, "PG", R, "MALFUNCTION", PEND, 30, -2, 84,
     "Pump delivered a bolus roughly twice the programmed rate for about ten minutes before the occlusion alarm stopped it. No injury reported; patient observed for six hours.",
     "Over-infusion is a malfunction that would be likely to cause serious injury if it recurred, 21 CFR 803.50(a)(2).",
     ["firmware version", "event date"], ["Which firmware version is shown on the pump's About screen?", "On what date did the over-infusion happen?", "Which drug and concentration were programmed?"],
     {"B1_event_type": "PRODUCT_PROBLEM", "D4_model": "P1", "H1_type_of_reportable_event": "MALFUNCTION", "H3_device_evaluated": "UNKNOWN"}),
    (4, "AF", R, "MALFUNCTION", PEND, 30, 0, 79,
     "Customer reports grey foam dust in the tubing after six months of use and a persistent cough. Device still in use; replacement requested.",
     "Foam degradation inside the air path is a malfunction likely to cause serious injury on recurrence, 21 CFR 803.50(a)(2).",
     ["patient age", "medical treatment"], ["How old is the patient?", "Has the patient seen a doctor about the cough?", "Is the device still in use?"],
     {"B1_event_type": "BOTH", "D4_model": "A200", "H1_type_of_reportable_event": "MALFUNCTION", "H3_device_evaluated": "NO"}),
    (5, "NS", R, "MALFUNCTION", PEND, 30, 6, 76,
     "Sensor read 95 mg/dL while a fingerstick and laboratory draw read 158 mg/dL. The patient delayed a correction dose. No harm reported.",
     "Readings 60 mg/dL below the laboratory value could lead to a dosing error and serious injury if repeated, 21 CFR 803.50(a)(2).",
     ["sensor lot number"], ["What is the lot number printed on the sensor applicator?", "How many days had the sensor been worn?", "Was the sensor calibrated that day?"],
     {"B1_event_type": "PRODUCT_PROBLEM", "D4_model": "S3", "H1_type_of_reportable_event": "MALFUNCTION", "H3_device_evaluated": "UNKNOWN"}),
    (6, "CL", N, "MALFUNCTION", PEND, 30, 25, 58,
     "Nurse reports the low-heart-rate alarm did not sound overnight. It is unclear whether the limit was set or whether the patient was affected.",
     "An alarm that did not sound could be reportable; the outcome and alarm settings are not stated, so facts are pending under 21 CFR 803.50.",
     ["patient outcome", "alarm limit settings", "event date"], ["Was the patient harmed or treated as a result?", "What alarm limits were set on the monitor?", "On what date and shift did this happen?"],
     {"B1_event_type": "PRODUCT_PROBLEM", "D4_model": "C2", "H1_type_of_reportable_event": "MALFUNCTION", "H3_device_evaluated": "UNKNOWN"}),
    (7, "VV", N, "MALFUNCTION", "info", 30, 18, 63,
     "Ventilator shut down without warning while on mains power and restarted after about a minute. Caregiver switched to the backup unit.",
     "Unexpected shutdown of a life-supporting device is likely reportable; the duration and backup response are not stated.",
     ["duration of shutdown", "patient condition"], ["How long was the ventilator off before it restarted?", "How was the patient during and after the shutdown?", "Was any error code shown on restart?"],
     {"B1_event_type": "PRODUCT_PROBLEM", "D4_model": "V1", "H1_type_of_reportable_event": "MALFUNCTION", "H3_device_evaluated": "NO"}),
    (8, "AF", R, "SERIOUS_INJURY", "appr", 30, 15, 93,
     "Patient admitted for two nights with bronchitis; the pulmonologist linked it to black particles found in the CPAP tubing and mask.",
     "Hospitalisation after inhaling particles from the device is a serious injury under 21 CFR 803.50(a)(1).",
     [], ["Is the device available for return and evaluation?", "What is the serial number of the unit?"],
     {"A2_age": "72", "A3_sex": "M", "B2_outcomes": ["Hospitalization (initial or prolonged)"], "D4_model": "A200", "H3_device_evaluated": "YES"}),
    (9, "PG", X, "NONE", LOG, None, None, 90,
     "Hairline crack on the rear of the pump housing noticed during cleaning. Pump passed its self-test and continues to operate normally.",
     "A cosmetic crack in the housing with no effect on pump function does not meet the reporting threshold of 21 CFR 803.50.", [], [], {}),
    (10, "NS", X, "NONE", LOG, None, None, 86,
     "Mobile app lost Bluetooth connection for about four minutes and reconnected on its own. Readings resumed with no gap in the log.",
     "The app showed a connectivity notice and reconnected; no reading was missed and no patient effect is stated. Not reportable under 21 CFR 803.", [], [], {}),
    (11, "VV", R, "SERIOUS_INJURY", PEND, 30, -5, 90,
     "Home ventilator alarmed for low pressure and stopped delivering breaths for several minutes; the patient became cyanotic and was taken to hospital by ambulance.",
     "Loss of ventilation leading to hospital treatment is a serious injury under 21 CFR 803.50(a)(1).",
     ["device serial number", "circuit lot number"], ["What is the serial number of the ventilator?", "Was the breathing circuit changed recently?", "What did the hospital find?"],
     {"A2_age": "9", "A3_sex": "F", "B2_outcomes": ["Life-threatening", "Hospitalization (initial or prolonged)"], "D4_model": "V1", "H3_device_evaluated": "NO"}),
    (12, "LM", R, "MALFUNCTION", PEND, 30, 1, 74,
     "Oximeter displayed 97% saturation while an arterial blood gas showed 84%. The discrepancy delayed oxygen therapy by about twenty minutes.",
     "A falsely high reading that delayed treatment is a malfunction likely to cause serious injury on recurrence, 21 CFR 803.50(a)(2).",
     ["probe type", "patient skin tone"], ["Which probe was in use: finger clip or adhesive?", "Was the probe repositioned before the blood gas?", "What is the oximeter serial number?"],
     {"B1_event_type": "PRODUCT_PROBLEM", "D4_model": "L5", "H1_type_of_reportable_event": "MALFUNCTION", "H3_device_evaluated": "UNKNOWN"}),
    (13, "CL", R, "SERIOUS_INJURY", PEND, 5, 4, 87,
     "A nurse received an electrical shock from the monitor's chassis while connecting ECG leads and needed treatment for a burn to the hand. The unit was taken out of service.",
     "Electrical shock causing injury is a malfunction with an unreasonable risk of substantial harm; a 5-day report under 21 CFR 803.53.",
     ["unit serial number", "power supply lot"], ["What is the serial number of the monitor?", "Was the monitor on mains or battery?", "Has biomedical engineering inspected the power supply?"],
     {"A2_age": "41", "A3_sex": "F", "B2_outcomes": ["Required intervention to prevent permanent impairment/damage"], "D4_model": "C2", "H3_device_evaluated": "YES"}),
    (14, "SP", R, "MALFUNCTION", PEND, 30, 9, 71,
     "Sterilizer reported a completed cycle although the chamber never reached temperature; the biological indicator later tested positive. Instruments were used on one patient before the result was known.",
     "A false cycle-complete indication could cause serious injury through infection if it recurred, 21 CFR 803.50(a)(2).",
     ["cycle log", "patient follow-up"], ["Can you send the printed cycle log for that run?", "Has the patient been contacted about follow-up?", "What is the sterilizer serial number?"],
     {"B1_event_type": "PRODUCT_PROBLEM", "D4_model": "S9", "H1_type_of_reportable_event": "MALFUNCTION", "H3_device_evaluated": "UNKNOWN"}),
    (15, "AF", R, "MALFUNCTION", PEND, 30, 14, 81,
     "User found a layer of dark residue on the inside of the mask and reports a sore throat each morning. The humidifier chamber also shows discolouration.",
     "Residue entering the air path is a malfunction likely to cause serious injury on recurrence, 21 CFR 803.50(a)(2).",
     ["device serial number", "months in use"], ["How long has the device been in use?", "Can you send a photo of the residue?", "Is the device available for return?"],
     {"B1_event_type": "BOTH", "D4_model": "A200", "H1_type_of_reportable_event": "MALFUNCTION", "H3_device_evaluated": "NO"}),
    (16, "PG", R, "MALFUNCTION", PEND, 30, 20, 77,
     "The pump's keypad accepted a rate of 125 mL/h when 12.5 mL/h was typed; the nurse caught the error at the confirmation screen. No drug was delivered at the wrong rate.",
     "A keypad entry defect that could lead to a tenfold over-infusion is a malfunction likely to cause serious injury if it recurred, 21 CFR 803.50(a)(2).",
     ["firmware version"], ["Which firmware version is the pump running?", "Does the fault repeat when the rate is entered again?", "What is the pump serial number?"],
     {"B1_event_type": "PRODUCT_PROBLEM", "D4_model": "P1", "H1_type_of_reportable_event": "MALFUNCTION", "H3_device_evaluated": "UNKNOWN"}),
    (17, "TC", R, "MALFUNCTION", PEND, 30, 27, 69,
     "Blanket reached 43 °C although the controller was set to 38 °C; the discrepancy was noticed during routine checks before any skin change.",
     "Over-temperature on a warming device is a malfunction likely to cause serious injury (burns) on recurrence, 21 CFR 803.50(a)(2).",
     ["controller serial number", "temperature log"], ["What is the controller serial number?", "Does the controller store a temperature log you can export?", "Had the probe been changed recently?"],
     {"B1_event_type": "PRODUCT_PROBLEM", "D4_model": "T40", "H1_type_of_reportable_event": "MALFUNCTION", "H3_device_evaluated": "NO"}),
    (18, "NS", R, "SERIOUS_INJURY", "appr", 30, 10, 85,
     "Patient dosed insulin on a sensor reading of 240 mg/dL; a later fingerstick read 110 mg/dL and the patient became hypoglycaemic and was treated by paramedics.",
     "A false high reading that led to treatment by paramedics is a serious injury under 21 CFR 803.50(a)(1).",
     [], ["What is the sensor lot number?", "Which app version was in use?"],
     {"A2_age": "35", "A3_sex": "F", "B2_outcomes": ["Required intervention to prevent permanent impairment/damage"], "D4_model": "S3", "H3_device_evaluated": "NO"}),
    (19, "VV", R, "MALFUNCTION", "appr", 5, 7, 89,
     "A burning smell and smoke came from the ventilator's power inlet; the caregiver switched to the backup unit at once and nobody was hurt.",
     "Smoke from a life-supporting device is a malfunction with an unreasonable risk of substantial harm; 5-day report under 21 CFR 803.53.",
     [], ["What is the ventilator serial number?", "Is the unit available for return?"],
     {"B1_event_type": "PRODUCT_PROBLEM", "D4_model": "V1", "H1_type_of_reportable_event": "MALFUNCTION", "H3_device_evaluated": "YES"}),
    (20, "CL", R, "MALFUNCTION", "appr", 30, 21, 80,
     "The monitor froze its display for about three minutes during a rapid-response call; vital signs were taken manually. The patient was not affected.",
     "A frozen display on a patient monitor during an emergency is a malfunction likely to cause serious injury if it recurred, 21 CFR 803.50(a)(2).",
     [], ["What software version is the monitor running?", "Was the monitor networked at the time?"],
     {"B1_event_type": "PRODUCT_PROBLEM", "D4_model": "C2", "H1_type_of_reportable_event": "MALFUNCTION", "H3_device_evaluated": "YES"}),
    (21, "LM", R, "SERIOUS_INJURY", "appr", 30, 2, 82,
     "Oximeter failed to alarm while a sleeping patient desaturated to 78%; the patient was found by a nurse and given oxygen, then moved to a higher-care bed.",
     "A missed alarm leading to escalation of care is a serious injury under 21 CFR 803.50(a)(1).",
     [], ["What alarm limits were set?", "What is the oximeter serial number?"],
     {"A2_age": "80", "A3_sex": "M", "B2_outcomes": ["Required intervention to prevent permanent impairment/damage"], "D4_model": "L5", "H3_device_evaluated": "UNKNOWN"}),
    (22, "PG", R, "MALFUNCTION", "appr", 30, 26, 83,
     "Pump battery indicator showed 60% but the pump shut down on battery after eleven minutes during a patient transfer. Infusion was restarted on mains power.",
     "A battery that fails well before its indicated charge is a malfunction likely to cause serious injury on recurrence, 21 CFR 803.50(a)(2).",
     [], ["How old is the battery pack?", "What is the pump serial number?"],
     {"B1_event_type": "PRODUCT_PROBLEM", "D4_model": "P1", "H1_type_of_reportable_event": "MALFUNCTION", "H3_device_evaluated": "NO"}),
    (23, "AF", R, "MALFUNCTION", "info", 30, 12, 73,
     "Customer reports a strong chemical smell from the device and headaches on waking for the past week. No particles seen yet.",
     "A chemical emission from the air path with symptoms is a malfunction likely to cause serious injury on recurrence, 21 CFR 803.50(a)(2).",
     ["device serial number", "medical attention"], ["Has the patient seen a doctor about the headaches?", "What is the device serial number?", "When was the device purchased?"],
     {"B1_event_type": "BOTH", "D4_model": "A200", "H1_type_of_reportable_event": "MALFUNCTION", "H3_device_evaluated": "NO"}),
    (24, "SP", R, "MALFUNCTION", "info", 30, 0, 70,
     "Door seal split mid-cycle and steam escaped into the room; a technician standing nearby reported a scald to the wrist and was seen by occupational health.",
     "Steam release causing a scald is a malfunction likely to cause serious injury if it recurred, 21 CFR 803.50(a)(2).",
     ["seal lot number", "injury details"], ["What is the lot number on the door seal?", "What treatment did the technician receive?", "How many cycles had the seal completed?"],
     {"A2_age": "29", "A3_sex": "M", "B1_event_type": "BOTH", "D4_model": "S9", "H1_type_of_reportable_event": "MALFUNCTION", "H3_device_evaluated": "YES"}),
    (25, "PG", N, "MALFUNCTION", PEND, 30, 2, 55,
     "Pump showed an 'air in line' alarm three times in one shift with no air visible in the tubing. Nurse replaced the set and the alarm stopped.",
     "Repeated false alarms may indicate a sensor fault; whether an infusion was interrupted is not stated, so facts are pending under 21 CFR 803.50.",
     ["infusion interruption", "set lot number"], ["Was the infusion paused or delayed by the alarms?", "What is the lot number of the administration set?", "Which drug was being infused?"],
     {"B1_event_type": "PRODUCT_PROBLEM", "D4_model": "P1", "H1_type_of_reportable_event": "MALFUNCTION", "H3_device_evaluated": "UNKNOWN"}),
    (26, "LM", N, "MALFUNCTION", PEND, 30, 8, 52,
     "Finger probe cable intermittently loses signal when moved. Reported by a home user who says readings 'drop out'.",
     "An intermittent cable fault may be reportable if it affected care; the patient's condition and any missed alarm are not stated.",
     ["patient condition", "event date", "cable serial"], ["Did the dropouts cause a missed alarm or delayed care?", "On what date did it start?", "What is the serial number on the cable label?"],
     {"B1_event_type": "PRODUCT_PROBLEM", "D4_model": "L5", "H1_type_of_reportable_event": "MALFUNCTION", "H3_device_evaluated": "UNKNOWN"}),
    (27, "TC", N, "MALFUNCTION", PEND, 30, 12, 60,
     "Warming blanket controller rebooted twice during a four-hour procedure. The anaesthetist reports the patient's temperature stayed within range.",
     "Controller reboots on a warming device could be reportable if warming stopped; the duration of each interruption is not stated.",
     ["reboot duration", "error codes"], ["How long was the controller off at each reboot?", "Were any error codes shown?", "What is the controller serial number?"],
     {"B1_event_type": "PRODUCT_PROBLEM", "D4_model": "T40", "H1_type_of_reportable_event": "MALFUNCTION", "H3_device_evaluated": "UNKNOWN"}),
    (28, "NS", N, "MALFUNCTION", PEND, 30, 19, 57,
     "Sensor fell off after one day although the adhesive patch was applied as instructed. The patient missed readings overnight.",
     "Early sensor detachment may be reportable if a missed reading affected care; no outcome is stated.",
     ["patient outcome", "sensor lot number"], ["Did the missed readings lead to a high or low glucose event?", "What is the sensor lot number?", "Was the skin prepared with alcohol before application?"],
     {"B1_event_type": "PRODUCT_PROBLEM", "D4_model": "S3", "H1_type_of_reportable_event": "MALFUNCTION", "H3_device_evaluated": "UNKNOWN"}),
    (29, "VV", N, "MALFUNCTION", PEND, 30, 29, 54,
     "Caregiver reports the ventilator's humidifier is 'not as warm as before'. No alarms, no change in the patient's condition reported.",
     "A possible humidifier fault on a ventilator needs facts on measured output and patient effect before the 21 CFR 803 decision can be made.",
     ["humidifier output", "patient effect"], ["What temperature does the humidifier display?", "Has the patient had any breathing difficulty or dry secretions?", "What is the ventilator serial number?"],
     {"B1_event_type": "PRODUCT_PROBLEM", "D4_model": "V1", "H1_type_of_reportable_event": "MALFUNCTION", "H3_device_evaluated": "UNKNOWN"}),
    (30, "AF", N, "MALFUNCTION", "info", 30, 5, 61,
     "User reports the machine 'makes a grinding noise' and air pressure feels lower than usual. No symptoms mentioned.",
     "A pressure drop on a CPAP could be reportable; whether therapy was affected and any symptoms are not stated.",
     ["pressure reading", "patient symptoms", "serial number"], ["What pressure does the device display during use?", "Has the patient had any symptoms since the noise started?", "What is the device serial number?"],
     {"B1_event_type": "PRODUCT_PROBLEM", "D4_model": "A200", "H1_type_of_reportable_event": "MALFUNCTION", "H3_device_evaluated": "NO"}),
    (31, "CL", N, "MALFUNCTION", "info", 30, 16, 59,
     "Monitor's SpO2 trace was flat for a period while the patient was awake and talking. Nurse unsure whether the sensor had slipped.",
     "A flat trace may be a sensor placement issue or a device fault; the duration and whether an alarm sounded are not stated.",
     ["duration", "alarm behaviour"], ["How long was the trace flat?", "Did the monitor alarm during that time?", "Was the sensor repositioned afterwards?"],
     {"B1_event_type": "PRODUCT_PROBLEM", "D4_model": "C2", "H1_type_of_reportable_event": "MALFUNCTION", "H3_device_evaluated": "UNKNOWN"}),
    (32, "SP", N, "MALFUNCTION", "appr", 30, 11, 56,
     "Sterilizer display showed a chamber-pressure warning but the cycle completed and the indicator strip changed colour normally.",
     "A pressure warning on a completed cycle may be a sensor issue; whether any load was compromised is not stated, so facts are pending.",
     ["cycle log"], ["Can you export the cycle log for that run?", "Has the warning appeared again?"],
     {"B1_event_type": "PRODUCT_PROBLEM", "D4_model": "S9", "H1_type_of_reportable_event": "MALFUNCTION", "H3_device_evaluated": "UNKNOWN"}),
    (33, "AF", X, "NONE", LOG, None, None, 88,
     "Customer asks for a replacement mask cushion because the old one has become stiff after a year of use. No symptoms or device problem reported.",
     "Normal wear of an accessory with no patient effect is not reportable under 21 CFR 803.50.", [], [], {}),
    (34, "PG", X, "NONE", LOG, None, None, 92,
     "Pump's touchscreen brightness is lower than a colleague's unit. All functions work and the display is readable.",
     "A display brightness difference with no effect on function does not meet the reporting threshold of 21 CFR 803.50.", [], [], {}),
    (35, "NS", X, "NONE", LOG, None, None, 89,
     "User could not log in to the companion app for an hour after a password reset. Readings continued on the receiver.",
     "An app login problem with readings available on the receiver has no patient effect; not reportable under 21 CFR 803.", [], [], {}),
    (36, "TC", X, "NONE", LOG, None, None, 91,
     "A corner of the blanket cover has a small tear. The blanket was taken out of service for replacement; it was not used on a patient.",
     "Cosmetic damage found before use with no patient exposure is not reportable under 21 CFR 803.50.", [], [], {}),
    (37, "CL", X, "NONE", LOG, None, None, 87,
     "Monitor's clock drifted by four minutes after a power outage and was corrected by the nurse. No clinical impact.",
     "A clock drift corrected by the user with no clinical impact does not meet the reporting threshold of 21 CFR 803.50.", [], [], {}),
    (38, "VV", X, "NONE", LOG, None, None, 85,
     "Caregiver reports the carry bag zip broke. The ventilator itself is working normally.",
     "A failed accessory bag with no effect on the device is not reportable under 21 CFR 803.50.", [], [], {}),
    (39, "LM", X, "NONE", LOG, None, None, 90,
     "Oximeter battery cover is loose and was taped in place; readings are unaffected and the unit will be sent for repair.",
     "A loose battery cover with readings unaffected does not meet the reporting threshold of 21 CFR 803.50.", [], [], {}),
    (40, "AF", X, "NONE", LOG, None, None, 84,
     "Customer reports the device is louder than expected at high pressure settings. No symptoms; the user finds it hard to sleep.",
     "Noise without a device malfunction or patient harm is not reportable under 21 CFR 803.50.", [], [], {}),
]

# Incoming complaints for the live demo replay (not seeded at rest; processed by the pipeline with the sample agent).
INCOMING = [
    (101, "AF", R, "SERIOUS_INJURY", PEND, 30, 30, 92,
     "Patient's spouse reports black dust inside the mask and tubing; the patient was seen in the ER for wheezing and shortness of breath and was given a nebuliser.",
     "Emergency treatment for breathing difficulty linked to particles from the device is a serious injury under 21 CFR 803.50(a)(1).",
     ["lot number", "months in use"], ["What is the device serial number?", "How long has the device been in use?", "Is the device available for return?"],
     {"A2_age": "61", "A3_sex": "M", "B2_outcomes": ["Required intervention to prevent permanent impairment/damage"], "D4_model": "A200", "H3_device_evaluated": "NO"}),
    (102, "PG", N, "MALFUNCTION", PEND, 30, 30, 57,
     "Pump reported 'motor stall' and stopped. Nurse restarted the infusion on a second pump. Unclear how long the gap was.",
     "A motor stall on an infusion pump is likely reportable; the length of the interruption and the drug involved are not stated.",
     ["interruption length", "drug infused"], ["How long was the infusion interrupted?", "Which drug was being infused and at what rate?", "What is the pump serial number?"],
     {"B1_event_type": "PRODUCT_PROBLEM", "D4_model": "P1", "H1_type_of_reportable_event": "MALFUNCTION", "H3_device_evaluated": "UNKNOWN"}),
    (103, "LM", X, "NONE", LOG, None, None, 88,
     "Home user says the oximeter takes longer than usual to show a reading when their hands are cold. Readings are correct once shown.",
     "Slower acquisition with cold hands is expected behaviour and causes no harm; not reportable under 21 CFR 803.50.", [], [], {}),
    (104, "TC", R, "MALFUNCTION", PEND, 5, 5, 86,
     "Warming blanket controller caught fire on the shelf while charging overnight; the ward's fire alarm went off. No patients were in the room.",
     "Fire in the device is a malfunction with an unreasonable risk of substantial harm to the public; 5-day report under 21 CFR 803.53.",
     ["controller serial number"], ["What is the controller serial number?", "Which charger was connected?", "Is the unit available for inspection?"],
     {"B1_event_type": "PRODUCT_PROBLEM", "D4_model": "T40", "H1_type_of_reportable_event": "MALFUNCTION", "H3_device_evaluated": "YES"}),
    (105, "CL", R, "MALFUNCTION", PEND, 30, 30, 78,
     "Bedside monitor displayed another patient's name and vitals for about a minute after a network reconnect. Staff noticed before any decision was made.",
     "Showing the wrong patient's data is a malfunction likely to cause serious injury if it recurred, 21 CFR 803.50(a)(2).",
     ["software version", "network configuration"], ["What software version is the monitor running?", "Was the central station also affected?", "What is the monitor serial number?"],
     {"B1_event_type": "PRODUCT_PROBLEM", "D4_model": "C2", "H1_type_of_reportable_event": "MALFUNCTION", "H3_device_evaluated": "UNKNOWN"}),
    (106, "NS", X, "NONE", LOG, None, None, 90,
     "User asks whether the sensor can be worn while swimming. No problem with the device reported.",
     "A product question with no event, malfunction or harm is not a reportable complaint under 21 CFR 803.", [], [], {}),
]

FAILURE_WORDS = {  # for seeded failure_mode (same labels vigil.failure_mode() uses)
    "AF": "material degradation/particles", "PG": "pressure/airflow", "NS": "software", "TC": "electrical/shock/fire",
    "CL": "alarm failure", "VV": "power/shutdown", "LM": "software", "SP": "mechanical"}


def cid(n):
    return f"NW-{24000 + n}"


def complaint(item):
    """The complaint dict vigil.process() takes, for one catalogue item."""
    n, dev, *_ = item
    name, common, code = DEVICES[dev]
    days_ago = _days_ago(item)
    category, fields = item[3], item[12]
    outcomes = ", ".join(fields.get("B2_outcomes") or []) if category == "SERIOUS_INJURY" else ""
    return dict(id=cid(n), text=item[8], device=name, manufacturer=MAKER, event_date="",
                received=(dt.date.today() - dt.timedelta(days=days_ago)).strftime("%Y%m%d"),
                event_type={"SERIOUS_INJURY": "Injury", "DEATH": "Death", "MALFUNCTION": "Malfunction"}.get(category, ""), outcomes=outcomes,
                generic_name=common, product_code=code, product_problems="", manufacturer_narrative="", source="replay")


def _days_ago(item):
    n, _, decision, _, _, deadline, due_in, *_ = item
    if due_in is None:
        return (n * 7) % 40 + 1
    return max(1, (deadline or 30) - due_in) if deadline == 30 else max(1, 7 - due_in)


def result_for(complaint_id):
    """Pre-written classification for a catalogue complaint, in the agent's classify() shape; None if unknown."""
    item = BY_ID.get(complaint_id)
    if not item:
        return None
    _, _, decision, category, _, deadline, _, conf, _, reason, missing, *_ = item
    return {"decision": decision, "category": category, "reason": reason, "remedial_action_needed": deadline == 5,
            "missing_info": list(missing), "confidence": conf}


def fields_for(complaint_id, c, row):
    """Pre-written Form 3500A fields for a catalogue complaint (the agent's draft_report() shape)."""
    item = BY_ID.get(complaint_id)
    base = {"A1_patient_identifier": "UNKNOWN", "A2_age": "UNKNOWN", "A3_sex": "UNKNOWN", "A4_weight": "UNKNOWN",
            "B1_event_type": "ADVERSE_EVENT", "B2_outcomes": [], "B3_date_of_event": "UNKNOWN",
            "B5_event_description": c.get("text", ""), "D1_brand_name": c.get("device", ""),
            "D2_common_device_name": c.get("generic_name") or "UNKNOWN", "D2b_product_code": c.get("product_code") or "UNKNOWN",
            "D3_manufacturer": c.get("manufacturer") or MAKER, "D4_model": "UNKNOWN", "D4_lot": "UNKNOWN", "D4_serial": "UNKNOWN",
            "H1_type_of_reportable_event": (row.get("category") or "MALFUNCTION") if row.get("category") != "NONE" else "MALFUNCTION",
            "H3_device_evaluated": "UNKNOWN",
            "H10_manufacturer_narrative": "Complaint received and logged. The device has not yet been returned; evaluation pending.",
            "follow_up_questions": []}
    if item:
        base["follow_up_questions"] = list(item[11])
        base.update(item[12])
    return base


def questions_for(complaint_id):
    item = BY_ID.get(complaint_id)
    return list(item[11]) if item else []


BY_ID = {cid(it[0]): it for it in CATALOGUE + INCOMING}


# ---------------------------------------------------------------- seeding
def _load_vigil():
    import importlib.util, sys
    if "vigil" in sys.modules:
        return sys.modules["vigil"]
    spec = importlib.util.spec_from_file_location("vigil", os.path.join(config.CODE_DIR, "vigil.py"))
    v = importlib.util.module_from_spec(spec); sys.modules["vigil"] = v; spec.loader.exec_module(v)
    return v


def rows(today=None):
    """decisions.csv rows for the catalogue at rest, plus the actions.csv rows that match them."""
    today = today or dt.date.today()
    v = _load_vigil()
    out, actions, rev = [], [], 0
    per_family = {}
    for item in sorted(CATALOGUE, key=lambda it: -_days_ago(it)):  # oldest first, so memory counts grow
        n, dev, decision, category, status, deadline, due_in, conf, text, reason, missing, *_ = item
        c = complaint(item)
        score, level, dist = v.priority(c)
        days_ago = _days_ago(item)
        t = dt.datetime.combine(today - dt.timedelta(days=days_ago), dt.time(8 + n % 9, (n * 11) % 60))
        fam = v.device_family(c["device"])
        prior = per_family.get(fam, [])
        memory = ""
        if prior:
            last = prior[-1]
            memory = f"{len(prior)} prior complaint{'s' * (len(prior) != 1)} on {fam} (top issue: {FAILURE_WORDS[dev]}, last: {last.day} {last:%b %Y})"
        per_family.setdefault(fam, []).append(t.date())
        due = (today + dt.timedelta(days=due_in)).isoformat() if due_in is not None else ""
        st = status
        if status in ("appr", "info"):
            who = REVIEWERS[rev % len(REVIEWERS)]; rev += 1
            st = f"APPROVED by {who}" if status == "appr" else f"INFO REQUESTED by {who}"
            when = t + dt.timedelta(days=1, hours=2, minutes=(n * 7) % 50)
            actions.append({"time": when.isoformat(timespec="seconds"), "id": c["id"], "kind": "approve" if status == "appr" else "info", "by": who})
        out.append(dict(time=t.isoformat(timespec="seconds"), id=c["id"], received=c["received"], device=c["device"], priority=level, score=score,
                        distress=dist, decision=decision, category=category, reason=reason, deadline_days=deadline or "", due_date=due,
                        confidence=conf, missing="; ".join(missing), duplicate_of="", status=st, text=text[:500], product_code=c["product_code"],
                        memory=memory, failure_mode=v.failure_mode("", text) if v.failure_mode("", text) != "other" else FAILURE_WORDS[dev],
                        source="csv" if n % 9 == 0 else "rest" if n % 7 == 0 else "replay"))
    actions.sort(key=lambda a: a["time"])
    return out, actions


HISTORY_FIELDS = ["id", "date_received", "device", "device_family", "product_code", "manufacturer", "event_type",
                  "product_problems", "failure_mode", "text"]
_MODES = ["material degradation/particles", "pressure/airflow", "software", "electrical/shock/fire", "alarm failure",
          "power/shutdown", "mechanical", "contamination", "other"]


def history_rows(today=None, months=36, seed=30):
    """Invented device history (the long-term memory): ~500 past reports over 3 years, with a rising particles
    signal on AEROFLOW so the pattern alert and Trends have something to show."""
    today = today or dt.date.today()
    rnd = random.Random(seed)
    v = _load_vigil()
    out, k = [], 0
    weights = {"AF": 5, "PG": 3, "NS": 3, "TC": 1, "CL": 2, "VV": 2, "LM": 2, "SP": 1}
    for m in range(months, 0, -1):
        month_start = (today.replace(day=1) - dt.timedelta(days=30 * m)).replace(day=1)
        for dev, w in weights.items():
            n = rnd.randint(0, w) + (rnd.randint(1, 3) if dev == "AF" and m < 8 else 0)
            for _ in range(n):
                k += 1
                name, common, code = DEVICES[dev]
                d = month_start + dt.timedelta(days=rnd.randint(0, 27))
                if d > today: continue
                mode = FAILURE_WORDS[dev] if rnd.random() < (0.7 if dev == "AF" and m < 8 else 0.45) else rnd.choice(_MODES)
                ev = rnd.choices(["Malfunction", "Injury", "Death"], [80, 18, 2])[0]
                out.append(dict(id=f"HX-{20000 + k}", date_received=d.isoformat(), device=name, device_family=v.device_family(name),
                                product_code=code, manufacturer=MAKER, event_type=ev, product_problems="", failure_mode=mode,
                                text=f"Historical report: {mode} on {name} ({ev.lower()})."))
    out.sort(key=lambda r: r["date_received"])
    return out


def seed(data_dir, with_pdfs=True, with_history=True):
    """(Re)write the sample data set into data_dir. Returns the complaint ids written."""
    os.makedirs(data_dir, exist_ok=True)
    rs, actions = rows()
    with open(os.path.join(data_dir, "decisions.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS); w.writeheader(); w.writerows(rs)
    with open(os.path.join(data_dir, "actions.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["time", "id", "kind", "by"]); w.writeheader(); w.writerows(actions)
    if with_history:
        with open(os.path.join(data_dir, "history.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=HISTORY_FIELDS); w.writeheader(); w.writerows(history_rows())
    for name in ("outbox.txt", "intake.json", ".push_pending"):
        try: os.remove(os.path.join(data_dir, name))
        except OSError: pass
    reports = os.path.join(data_dir, "reports")
    shutil.rmtree(reports, ignore_errors=True)
    if with_pdfs:
        v = _load_vigil()
        if v.FPDF is not None:
            old = v.REPORTS; v.REPORTS = reports
            try:
                for item in CATALOGUE:
                    if item[2] in (R, N):
                        c = complaint(item)
                        row = next(r for r in rs if r["id"] == c["id"])
                        v.render_mdr_pdf(c, {**row, "awareness": (dt.date.today() - dt.timedelta(days=_days_ago(item))).isoformat()},
                                         {**fields_for(c["id"], c, row), "B4_date_of_report": dt.date.today().isoformat(),
                                          "G7_report_type": "5-day" if str(row["deadline_days"]) == "5" else "30-day",
                                          "G4_date_received_by_manufacturer": (dt.date.today() - dt.timedelta(days=_days_ago(item))).isoformat(), "G4_note": ""})
            finally:
                v.REPORTS = old
    with open(os.path.join(data_dir, ".sample-seed"), "w", encoding="utf-8") as f:
        f.write(dt.date.today().isoformat())
    return [r["id"] for r in rs]


def seed_date(data_dir):
    """Date the sample data was last seeded, or None."""
    try:
        with open(os.path.join(data_dir, ".sample-seed"), encoding="utf-8") as f:
            return dt.date.fromisoformat(f.read().strip())
    except (OSError, ValueError):
        return None


def incoming_complaints():
    """The complaints a demo replay feeds through the pipeline, in order."""
    return [complaint(it) for it in INCOMING]


if __name__ == "__main__":
    import sys
    print(len(seed(sys.argv[1] if len(sys.argv) > 1 else config.data_dir())), "complaints seeded")
