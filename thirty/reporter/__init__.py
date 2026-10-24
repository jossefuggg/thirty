"""Reporter Front_Door: the public, no-login "Report a device problem" web flow.

A reporter scans a per-device QR code (or opens ``/report``), picks a language,
answers an adaptive one-question-at-a-time interview, reviews a plain-words
summary, confirms, and receives a reference number plus a PDF receipt.

Single-pipeline-entry rule
---------------------------
This package submits confirmed reports ONLY through ``intake.submit(...)`` with
``source="reporter"``. It NEVER calls ``vigil.process()`` directly, and it NEVER
edits ``vigil.py``. Dedupe, raw storage, the background worker, and the
``(http_status, response_dict)`` contract all come for free from ``intake.py``,
so a reporter report is scored, classified, drafted, and clocked exactly like
every other channel.

Public surface
--------------
    from thirty.reporter import init_app, qr_svg, build_receipt
    from thirty.reporter import (
        start_state, record_answer, should_continue,
        end_interview, to_draft_3500a, to_intake_payload,
    )

- ``init_app(app)`` — register the Flask blueprint (``front_door``), mounted next
  to ``intake.init_app(app)`` in the console's init block.
- ``qr_svg(data, ...)`` — pure-Python QR-to-SVG generator (``qr``).
- ``build_receipt(...)`` — fpdf2 PDF receipt builder (``receipt``).
- the ``interview`` reducers — pure interview-state logic (``interview``).

The names above are resolved lazily (PEP 562) so importing ``thirty.reporter``
succeeds before the sibling modules land; each name binds once its module exists.
"""
import importlib

# name -> submodule that provides it. Resolved lazily so the package imports
# cleanly before the sibling modules (front_door, qr, receipt, interview) exist.
_EXPORTS = {
    "init_app": "front_door",
    "qr_svg": "qr",
    "build_receipt": "receipt",
    # interview reducers (pure interview-state logic)
    "start_state": "interview",
    "record_answer": "interview",
    "should_continue": "interview",
    "end_interview": "interview",
    "to_draft_3500a": "interview",
    "to_intake_payload": "interview",
}

__all__ = list(_EXPORTS)


def __getattr__(name):  # PEP 562 module-level lazy attribute access
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(f"{__name__}.{module}")
    return getattr(mod, name)


def __dir__():
    return sorted(set(globals()) | set(_EXPORTS))
