"""Plugins: discovery, state and status for agent plugins.

A plugin is a folder with two files:

    plugin.json   the manifest: id, name, version, description, capabilities, settings schema
    plugin.py     a module with  create(settings: dict) -> thirty.agents.base.Agent

Built-in plugins live in thirty/plugins/builtin/<id>/; user plugins in <data_dir>/plugins/<id>/.
Which plugins are enabled, their settings and which agent is active are kept in <data_dir>/plugins.json.
See docs/PLUGINS.md for the contract and an example.
"""
import importlib.util, json, os, threading, time

from .. import config

BUILTIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "builtin")
MANIFEST = "plugin.json"
MODULE = "plugin.py"
CAPABILITIES = {"agent"}
SETTING_TYPES = {"string", "url", "secret", "number", "bool", "select"}
STATE_FILE = "plugins.json"

_lock = threading.RLock()
_registry = {"plugins": None, "scanned": 0}
_instances = {}  # (plugin id, settings json) -> agent instance


class PluginError(Exception):
    pass


class Plugin:
    def __init__(self, path, manifest, builtin):
        self.path, self.manifest, self.builtin = path, manifest, builtin
        self.id = manifest["id"]
        self.name = manifest.get("name") or self.id
        self.version = str(manifest.get("version") or "0")
        self.description = manifest.get("description") or ""
        self.capabilities = list(manifest.get("capabilities") or [])
        self.settings_schema = list(manifest.get("settings") or [])
        self.error = None  # a manifest or import problem; the plugin is listed but cannot run
        self._module = None

    def defaults(self):
        return {s["key"]: s.get("default", "" if s.get("type") != "bool" else False) for s in self.settings_schema}

    def missing(self, settings):
        """Required settings that are empty."""
        return [s["key"] for s in self.settings_schema if s.get("required") and settings.get(s["key"]) in (None, "", False)]

    def module(self):
        if self._module is None:
            spec = importlib.util.spec_from_file_location(f"thirty_plugin_{self.id.replace('-', '_')}", os.path.join(self.path, MODULE))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if not callable(getattr(mod, "create", None)):
                raise PluginError(f"{MODULE} must define create(settings)")
            self._module = mod
        return self._module

    def create(self, settings):
        agent = self.module().create({**self.defaults(), **(settings or {})})
        for name in ("classify", "draft_report", "follow_up_questions", "health"):
            if not callable(getattr(agent, name, None)):
                raise PluginError(f"agent is missing {name}()")
        return agent

    def public(self):
        return {"id": self.id, "name": self.name, "version": self.version, "description": self.description,
                "capabilities": self.capabilities, "settings": self.settings_schema, "builtin": self.builtin,
                "path": self.path, "error": self.error}


def _validate(manifest, path):
    if not isinstance(manifest, dict):
        raise PluginError("manifest must be a JSON object")
    pid = manifest.get("id")
    if not isinstance(pid, str) or not pid or not all(c.isalnum() or c in "-_" for c in pid):
        raise PluginError("manifest id must be letters, digits, - or _")
    if pid != os.path.basename(path.rstrip(os.sep)).replace("_", "-") and pid != os.path.basename(path.rstrip(os.sep)):
        raise PluginError(f"manifest id {pid!r} must match the folder name")
    caps = manifest.get("capabilities") or []
    if not set(caps) & CAPABILITIES:
        raise PluginError(f"capabilities must include one of {sorted(CAPABILITIES)}")
    for s in manifest.get("settings") or []:
        if not isinstance(s, dict) or not s.get("key") or s.get("type", "string") not in SETTING_TYPES:
            raise PluginError(f"bad setting entry: {s!r}")
        s.setdefault("type", "string"); s.setdefault("label", s["key"])


def _load_dir(root, builtin):
    found = []
    if not os.path.isdir(root):
        return found
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        mf = os.path.join(path, MANIFEST)
        if not os.path.isfile(mf):
            continue
        try:
            with open(mf, encoding="utf-8") as f:
                manifest = json.load(f)
            _validate(manifest, path)
            p = Plugin(path, manifest, builtin)
            if not os.path.isfile(os.path.join(path, MODULE)):
                p.error = f"{MODULE} not found"
        except Exception as e:
            p = Plugin(path, {"id": name, "name": name}, builtin)
            p.error = f"{type(e).__name__}: {e}"
        found.append(p)
    return found


def user_dir():
    return os.path.join(config.data_dir(), "plugins")


def discover(force=False):
    """All plugins, built-in first. Rescans at most every 2 s unless forced."""
    with _lock:
        if force or _registry["plugins"] is None or time.time() - _registry["scanned"] > 2:
            plugins = {}
            for p in _load_dir(BUILTIN_DIR, True) + _load_dir(user_dir(), False):
                plugins.setdefault(p.id, p)  # a user plugin cannot shadow a built-in id
            _registry.update(plugins=plugins, scanned=time.time())
        return dict(_registry["plugins"])


def get(plugin_id):
    return discover().get(plugin_id)


# ---------------------------------------------------------------- state (plugins.json)
def _state_path():
    return os.path.join(config.data_dir(), STATE_FILE)


def _default_state():
    return {"active_agent": None, "plugins": {}}


def state():
    with _lock:
        try:
            with open(_state_path(), encoding="utf-8") as f:
                st = json.load(f)
        except (OSError, ValueError):
            st = _default_state()
        st.setdefault("active_agent", None); st.setdefault("plugins", {})
        return st


def save_state(st):
    with _lock:
        os.makedirs(config.data_dir(), exist_ok=True)
        tmp = _state_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, indent=2)
        try:
            os.chmod(tmp, 0o600)  # plugin settings may hold secrets
        except OSError:
            pass
        os.replace(tmp, _state_path())
        _instances.clear()
    from ..agents import set_agent
    set_agent(None)  # the running process picks up the change on its next call


def plugin_state(plugin_id):
    """{"enabled": bool, "settings": {...}} for a plugin (built-ins are enabled unless switched off)."""
    p = get(plugin_id)
    st = state()["plugins"].get(plugin_id) or {}
    enabled = st.get("enabled", bool(p and p.builtin))
    settings = {**(p.defaults() if p else {}), **(st.get("settings") or {})}
    return {"enabled": enabled, "settings": settings}


def update_plugin(plugin_id, enabled=None, settings=None):
    p = get(plugin_id)
    if p is None:
        raise PluginError(f"unknown plugin {plugin_id}")
    st = state()
    cur = st["plugins"].setdefault(plugin_id, {"enabled": p.builtin, "settings": {}})
    if enabled is not None:
        cur["enabled"] = bool(enabled)
        if not cur["enabled"] and st.get("active_agent") == plugin_id:
            st["active_agent"] = "none"  # the active agent was disabled: manual review until another is chosen
    if settings is not None:
        allowed = {s["key"]: s for s in p.settings_schema}
        clean = dict(cur.get("settings") or {})
        for k, v in settings.items():
            if k not in allowed:
                continue
            t = allowed[k]["type"]
            if t == "secret" and v in ("", None):
                continue  # blank keeps the stored secret
            if t == "bool":
                v = bool(v) if not isinstance(v, str) else v.lower() in ("1", "true", "on", "yes")
            elif t == "number":
                try: v = float(v)
                except (TypeError, ValueError): raise PluginError(f"{allowed[k]['label']} must be a number")
            else:
                v = str(v).strip()
            clean[k] = v
        cur["settings"] = clean
    save_state(st)
    return plugin_state(plugin_id)


def set_active(plugin_id):
    """Choose the active agent: a plugin id, or "none" for manual review."""
    if plugin_id not in ("none", None):
        p = get(plugin_id)
        if p is None or "agent" not in p.capabilities:
            raise PluginError(f"{plugin_id} is not an agent plugin")
        if not plugin_state(plugin_id)["enabled"]:
            raise PluginError(f"{p.name} is disabled")
    st = state(); st["active_agent"] = plugin_id or "none"; save_state(st)
    from ..agents import set_agent
    set_agent(None)


def active_agent_id():
    """The active agent plugin id ("none" = manual review). Env THIRTY_AGENT forces it; otherwise plugins.json;
    otherwise the default: the local model when one is configured, else the sample agent."""
    forced = (os.environ.get("THIRTY_AGENT") or "").strip().lower()
    if forced in ("sample", "local", "none"):
        return forced
    chosen = state().get("active_agent")
    if chosen:
        if chosen == "none" or (get(chosen) and plugin_state(chosen)["enabled"]):
            return chosen
    return "local" if config.model_configured() else "sample"


def forced_by_env():
    return (os.environ.get("THIRTY_AGENT") or "").strip().lower() in ("sample", "local", "none")


def instantiate(plugin_id):
    """An agent instance for a plugin with its current settings (cached until settings change)."""
    p = get(plugin_id)
    if p is None:
        raise PluginError(f"unknown plugin {plugin_id}")
    if p.error:
        raise PluginError(p.error)
    ps = plugin_state(plugin_id)
    key = (plugin_id, json.dumps(ps["settings"], sort_keys=True))
    with _lock:
        if key not in _instances:
            _instances[key] = p.create(ps["settings"])
        return _instances[key]


def status(plugin_id, probe=True):
    """ready | not-configured | error | disabled (+ label). probe=False skips the agent's own health check."""
    p = get(plugin_id)
    if p is None:
        return {"state": "error", "label": "not installed"}
    if p.error:
        return {"state": "error", "label": p.error}
    ps = plugin_state(plugin_id)
    if not ps["enabled"]:
        return {"state": "disabled", "label": "disabled"}
    missing = p.missing(ps["settings"])
    if missing:
        labels = {s["key"]: s.get("label", s["key"]) for s in p.settings_schema}
        return {"state": "not-configured", "label": "needs " + ", ".join(labels[m] for m in missing)}
    if not probe:
        return {"state": "ready", "label": "configured"}
    try:
        h = instantiate(plugin_id).health()
    except Exception as e:
        return {"state": "error", "label": f"{type(e).__name__}: {e}"[:160]}
    if h.get("ok"):
        return {"state": "ready", "label": h.get("label") or "ready", "health": h}
    return {"state": "error", "label": h.get("label") or "not responding", "health": h}


def overview(probe=True):
    """Everything the Plugins screen shows."""
    active = active_agent_id()
    items = []
    for p in discover(force=True).values():
        ps = plugin_state(p.id)
        d = p.public() | {"enabled": ps["enabled"], "settings": {k: ("" if s_type(p, k) == "secret" else v) for k, v in ps["settings"].items()},
                          "has_secret": {k: bool(v) for k, v in ps["settings"].items() if s_type(p, k) == "secret"},
                          "status": status(p.id, probe=probe), "active": p.id == active}
        items.append(d)
    return {"active_agent": active, "forced_by_env": forced_by_env(), "plugins": items, "user_dir": user_dir()}


def s_type(p, key):
    return next((s["type"] for s in p.settings_schema if s["key"] == key), "string")
