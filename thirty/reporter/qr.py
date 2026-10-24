"""QR-code to inline-SVG generator for the reporter Front_Door.

The Integrations page shows one QR code per sample device, each encoding the
Front_Door URL ``/report/<slug>`` (Requirement 10.3). We render each code as an
inline ``<svg>`` produced entirely inside this Python process — no network, no
CDN, no external service (Requirement 10.4).

Encoding is delegated to :mod:`segno`, a pure-Python, dependency-free QR
encoder (pinned in ``requirements.txt``). It runs fully offline. We use
error-correction level M (~15% recovery), a balanced default for a code printed
and scanned off paper, and let segno auto-select the smallest QR version that
fits the payload. Public demo URLs look like
``https://thirty-demo.onrender.com/report/<slug>`` (~50-60 characters) and
encode comfortably at this level; no artificial length limit is imposed.

Public surface::

    from thirty.reporter.qr import qr_svg, QRError
    svg = qr_svg("https://thirty-demo.onrender.com/report/AF")  # <svg ...>...</svg>
"""

import segno
from segno import DataOverflowError


class QRError(Exception):
    """Raised when the data cannot be encoded as a QR code.

    The integrations QR panel catches this per device so that one device whose
    code fails to generate is omitted (with an error indication) while the
    remaining devices still render (Requirement 10.6).
    """


def qr_svg(url, *, scale=4):
    """Encode ``url`` as a QR code and return a complete inline ``<svg>`` string.

    Uses error-correction level M and lets :mod:`segno` pick the smallest QR
    version that fits ``url``. The returned string is a self-contained
    ``<svg>...</svg>`` element (segno's ``svg_inline``) suitable for embedding
    directly in a Jinja template.

    :param url: the URL to encode, e.g. ``/report/AF`` or the full public form
        ``https://thirty-demo.onrender.com/report/AF``.
    :param scale: pixel size of one QR module (default 4).
    :raises QRError: if ``url`` is empty/whitespace-only or cannot be encoded by
        segno (e.g. too long for any QR version). The integrations panel catches
        this so a single failing device is omitted while the others still render.
    """
    if not isinstance(url, str) or not url.strip():
        raise QRError("cannot encode empty data")

    try:
        return segno.make(url, error="m").svg_inline(scale=scale)
    except DataOverflowError as exc:
        raise QRError(f"data too long to encode as a QR code: {exc}") from exc
    except Exception as exc:  # any other segno encoding failure -> QRError
        raise QRError(f"QR encoding failed: {exc}") from exc
