#!/usr/bin/env python3
"""Issue Thirty licence keys (offline, Ed25519). See docs/RELEASING.md.

    python3 tools/make_licence.py keygen                     # prints a public key; writes the secret key file
    python3 tools/make_licence.py issue --site "Harbor Medical Devices" --org "Harbor Medical" --days 365
    python3 tools/make_licence.py issue --site "Harbor Medical Devices" --demo --days 14      # 14-day demo
    python3 tools/make_licence.py issue --site "Harbor Medical Devices" --expires 2027-03-31  # fixed end date
    python3 tools/make_licence.py verify <key or file>

The secret key lives in THIRTY_LICENCE_SECRET (hex) or the file given by --secret (default
~/.thirty/licence-secret.key, mode 0600). Never commit it. The public key goes into
thirty/licensing.py PUBLIC_KEY (or THIRTY_LICENCE_PUBKEY) before building a release."""
import argparse, datetime as dt, os, secrets, sys, uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from thirty import licensing  # noqa: E402

DEFAULT_SECRET = os.path.expanduser("~/.thirty/licence-secret.key")


def load_secret(path):
    env = os.environ.get("THIRTY_LICENCE_SECRET")
    if env:
        return env.strip()
    with open(path) as f:
        return f.read().strip()


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("keygen"); k.add_argument("--secret", default=DEFAULT_SECRET)
    i = sub.add_parser("issue"); i.add_argument("--site", required=True); i.add_argument("--org", default="")
    i.add_argument("--days", type=int, default=365, help="licence length in days (any number: 7, 14, 30, 365…)")
    i.add_argument("--expires", help="fixed end date YYYY-MM-DD (overrides --days)")
    i.add_argument("--demo", action="store_true", help="mark the key as a demo licence (shown as Demo in the app)")
    i.add_argument("--seats", type=int, default=0); i.add_argument("--notes", default="")
    i.add_argument("--secret", default=DEFAULT_SECRET); i.add_argument("--out", help="write the key to this file")
    v = sub.add_parser("verify"); v.add_argument("key")
    a = ap.parse_args()
    if a.cmd == "keygen":
        if os.path.exists(a.secret):
            sys.exit(f"{a.secret} exists; remove it first if you really want a new keypair (old keys stop verifying)")
        sk = secrets.token_bytes(32)
        os.makedirs(os.path.dirname(a.secret), exist_ok=True)
        fd = os.open(a.secret, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(sk.hex() + "\n")
        print("secret key written to", a.secret, "(keep it private, back it up)")
        print("PUBLIC_KEY =", repr(licensing.publickey(sk).hex()), " # paste into thirty/licensing.py")
    elif a.cmd == "issue":
        today = dt.date.today()
        expires = dt.date.fromisoformat(a.expires) if a.expires else today + dt.timedelta(days=a.days)
        if expires <= today:
            sys.exit("expiry must be in the future")
        payload = {"id": ("DEMO-" if a.demo else "LIC-") + uuid.uuid4().hex[:12].upper(), "site": a.site, "org": a.org or a.site,
                   "issued": today.isoformat(), "expires": expires.isoformat(), "seats": a.seats or None, "notes": a.notes,
                   "kind": "demo" if a.demo else "site"}
        print(f"{'demo' if a.demo else 'site'} licence for {a.site}, {(expires - today).days} days, expires {expires}", file=sys.stderr)
        key = licensing.make_key(payload, load_secret(a.secret))
        if a.out:
            with open(a.out, "w") as f:
                f.write(key + "\n")
            print("written", a.out)
        print(key)
    else:
        key = open(a.key).read() if os.path.exists(a.key) else a.key
        payload, err = licensing.parse(key)
        print("payload:", payload)
        print("OK" if not err else "ERROR: " + err)
        sys.exit(0 if not err else 1)


if __name__ == "__main__":
    main()
