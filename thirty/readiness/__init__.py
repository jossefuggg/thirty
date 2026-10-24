"""Device readiness: decision support for wellness/wearable companies.

The public ``/readiness`` page answers three questions for a company with a
health feature: (1) is the feature likely general wellness or a medical device
under current FDA policy, (2) what has already gone wrong with similar devices
in public FDA data, and (3) which obligations start on day one as a device
manufacturer, and which of those Thirty handles.

Core stance (do not weaken):

- **Decision support, not regulatory advice.** Every outcome says "likely",
  cites its source, and tells the user to confirm with a regulatory
  professional or ask FDA (a 513(g) request or a Q-Submission).
- **Deterministic and data-driven.** The category is decided by a pure,
  total function (:func:`categorize`) that reads its thresholds, labels,
  citations and the day-one checklist from ``thirty/readiness_rules.json`` —
  **no AI and no model decide the outcome**, and nothing is hard-coded in
  templates.
- **Cite only the catalogue.** The feature references only the regulations,
  guidance names, dates and URLs listed in the rules file's ``citations``
  block. It never invents any of these.
- **Offline-first signals.** The "what goes wrong" step reads cached openFDA
  JSON from ``data/openfda_cache/`` and never calls the network on render.

This module stays import-light (Flask-free) so the Hypothesis property tests
can drive the engine and the cache loader without a web server.
"""

from .engine import (  # noqa: F401
    CATEGORIES,
    CLAIM_OPTIONS,
    DISCLAIMER,
    PREDICATE,
    USERS,
    WORST_OUTCOMES,
    categorize,
    day_one_checklist,
    load_rules,
    normalize,
)
from .openfda import (  # noqa: F401
    RefreshError,
    cache_dir,
    fetch_and_cache,
    load_signals,
    where_to_look_first,
)
from .pdf import available, build_pdf  # noqa: F401
