"""Licensing scaffold: a licence-check interface and an offline implementation (a signed key file).

Designed for per-site annual licences. No payment provider; keys are issued with tools/make_licence.py
and verified offline with an Ed25519 public key. Without a valid key Thirty keeps working and shows
"Evaluation" (enforcement is a product decision for later; see docs/RELEASING.md).

Key file format (one line, <data>/licence.key):
    thirty1.<base64url payload>.<base64url signature>
payload = canonical JSON {"id", "site", "org", "issued", "expires", "seats", "notes"}

PUBLIC_KEY is empty until the owner runs `tools/make_licence.py keygen` and pastes the public key here
(or sets THIRTY_LICENCE_PUBKEY). Until then every key reports "cannot verify: no public key".
"""
import base64, datetime as dt, hashlib, json, os

from . import config

PUBLIC_KEY = ""  # hex, 32 bytes; set by the owner (see docs/RELEASING.md). Env THIRTY_LICENCE_PUBKEY overrides.
FILE = "licence.key"
PREFIX = "thirty1"
GRACE_DAYS = 14  # after expiry: still "licensed" with a warning, then evaluation


# ---------------------------------------------------------------- Ed25519 (pure Python, reference algorithm)
# Compact port of the public-domain reference implementation (Bernstein, Duif, Lange, Schwabe, Yang).
# Slow (tens of ms per verify) but dependency-free, which is what an offline check in a frozen app wants.
_q = 2 ** 255 - 19
_l = 2 ** 252 + 27742317777372353535851937790883648493


def _H(m):
    return hashlib.sha512(m).digest()


def _inv(x):
    return pow(x, _q - 2, _q)


_d = (-121665 * _inv(121666)) % _q
_I = pow(2, (_q - 1) // 4, _q)


def _xrecover(y):
    xx = (y * y - 1) * _inv(_d * y * y + 1)
    x = pow(xx, (_q + 3) // 8, _q)
    if (x * x - xx) % _q != 0:
        x = (x * _I) % _q
    if x % 2 != 0:
        x = _q - x
    return x


_By = (4 * _inv(5)) % _q
_B = (_xrecover(_By), _By)


def _edwards(P, Q):
    x1, y1 = P; x2, y2 = Q
    x3 = (x1 * y2 + x2 * y1) * _inv(1 + _d * x1 * x2 * y1 * y2)
    y3 = (y1 * y2 + x1 * x2) * _inv(1 - _d * x1 * x2 * y1 * y2)
    return (x3 % _q, y3 % _q)


def _scalarmult(P, e):
    if e == 0:
        return (0, 1)
    Q = _scalarmult(P, e // 2)
    Q = _edwards(Q, Q)
    if e & 1:
        Q = _edwards(Q, P)
    return Q


def _encodeint(y):
    return y.to_bytes(32, "little")


def _encodepoint(P):
    x, y = P
    bits = [(y >> i) & 1 for i in range(255)] + [x & 1]
    return bytes(sum(bits[i * 8 + j] << j for j in range(8)) for i in range(32))


def _decodeint(s):
    return int.from_bytes(s, "little")


def _decodepoint(s):
    y = sum(2 ** i * ((s[i // 8] >> (i % 8)) & 1) for i in range(255))
    x = _xrecover(y)
    if x & 1 != (s[31] >> 7) & 1:
        x = _q - x
    P = (x, y)
    if not _isoncurve(P):
        raise ValueError("decoding point that is not on curve")
    return P


def _isoncurve(P):
    x, y = P
    return (-x * x + y * y - 1 - _d * x * x * y * y) % _q == 0


def _Hint(m):
    h = _H(m)
    return sum(2 ** i * ((h[i // 8] >> (i % 8)) & 1) for i in range(512))


def publickey(sk):
    h = _H(sk)
    a = 2 ** 254 + sum(2 ** i * ((h[i // 8] >> (i % 8)) & 1) for i in range(3, 254))
    return _encodepoint(_scalarmult(_B, a))


def signature(m, sk, pk):
    h = _H(sk)
    a = 2 ** 254 + sum(2 ** i * ((h[i // 8] >> (i % 8)) & 1) for i in range(3, 254))
    r = _Hint(h[32:64] + m)
    R = _scalarmult(_B, r)
    S = (r + _Hint(_encodepoint(R) + pk + m) * a) % _l
    return _encodepoint(R) + _encodeint(S)


def checkvalid(s, m, pk):
    if len(s) != 64 or len(pk) != 32:
        return False
    try:
        R = _decodepoint(s[:32]); A = _decodepoint(pk)
    except ValueError:
        return False
    S = _decodeint(s[32:64])
    h = _Hint(_encodepoint(R) + pk + m)
    return _scalarmult(_B, S) == _edwards(R, _scalarmult(A, h))


# ---------------------------------------------------------------- key files
def _b64e(b):
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64d(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def canonical(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def make_key(payload, secret_key_hex):
    """Sign a licence payload with a 32-byte Ed25519 secret key (hex). Returns the one-line key string."""
    sk = bytes.fromhex(secret_key_hex)
    pk = publickey(sk)
    m = canonical(payload)
    return f"{PREFIX}.{_b64e(m)}.{_b64e(signature(m, sk, pk))}"


def public_key_hex():
    return (os.environ.get("THIRTY_LICENCE_PUBKEY") or PUBLIC_KEY or "").strip().lower()


def parse(key):
    """(payload, error). Verifies the signature against the configured public key."""
    key = (key or "").strip()
    parts = key.split(".")
    if len(parts) != 3 or parts[0] != PREFIX:
        return None, "not a Thirty licence key"
    try:
        m, sig = _b64d(parts[1]), _b64d(parts[2])
        payload = json.loads(m)
    except Exception:
        return None, "key is damaged"
    pk = public_key_hex()
    if not pk:
        return payload, "cannot verify: no public key configured in this build"
    try:
        ok = checkvalid(sig, m, bytes.fromhex(pk))
    except Exception:
        ok = False
    if not ok:
        return payload, "signature does not match"
    for k in ("id", "site", "expires"):
        if not payload.get(k):
            return payload, f"key is missing {k}"
    return payload, None


# ---------------------------------------------------------------- the check interface
class LicenseCheck:
    """What the app asks: status() -> {"state", "label", "site", "org", "expires", "days_left", "reason", "id"}.
    state: licensed | expiring | grace | expired | evaluation | invalid"""

    def status(self):
        raise NotImplementedError


class OfflineKeyFile(LicenseCheck):
    def __init__(self, path=None):
        self._path = path

    def path(self):
        return self._path or os.path.join(config.data_dir(), FILE)

    def read(self):
        try:
            with open(self.path(), encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            return ""

    def install(self, key):
        payload, err = parse(key)
        if payload is None:
            raise ValueError(err)
        os.makedirs(os.path.dirname(self.path()), exist_ok=True)
        with open(self.path(), "w", encoding="utf-8") as f:
            f.write(key.strip() + "\n")
        return self.status()

    def remove(self):
        try:
            os.remove(self.path())
        except OSError:
            pass

    def status(self, today=None):
        today = today or dt.date.today()
        key = self.read()
        base = {"state": "evaluation", "label": "Evaluation · no licence key", "site": "", "org": "", "expires": "", "days_left": None, "reason": "", "id": ""}
        if not key:
            return base
        payload, err = parse(key)
        if payload is None:
            return base | {"state": "invalid", "label": "Licence key invalid", "reason": err}
        info = {"site": payload.get("site", ""), "org": payload.get("org", ""), "expires": payload.get("expires", ""), "id": payload.get("id", "")}
        if err:
            return base | info | {"state": "invalid", "label": "Licence key not verified", "reason": err}
        try:
            exp = dt.date.fromisoformat(payload["expires"])
        except ValueError:
            return base | info | {"state": "invalid", "label": "Licence key invalid", "reason": "bad expiry date"}
        left = (exp - today).days
        if left < -GRACE_DAYS:
            return base | info | {"state": "expired", "label": f"Licence expired {-left} days ago", "days_left": left}
        if left < 0:
            return base | info | {"state": "grace", "label": f"Licence expired · {GRACE_DAYS + left} days of grace left", "days_left": left}
        if left <= 30:
            return base | info | {"state": "expiring", "label": f"Licensed to {info['site']} · renews in {left} days", "days_left": left}
        return base | info | {"state": "licensed", "label": f"Licensed to {info['site']} · until {exp:%-d %b %Y}", "days_left": left}


def check():
    """The app's licence check (the offline key file for now)."""
    return OfflineKeyFile()
