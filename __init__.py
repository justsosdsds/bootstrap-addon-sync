# Bootstrap Addon Sync for Anki
# Safe manifest-based add-on synchronizer.
# Version: 0.5.1

from __future__ import annotations

import json
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from aqt import mw
from aqt.qt import QAction, QMenu, QApplication, QMessageBox, QDialog, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem, QPushButton, QLabel, Qt
from aqt.utils import askUser, showInfo, showWarning, tooltip, openFolder

try:
    from aqt import gui_hooks
except Exception:  # pragma: no cover
    gui_hooks = None

ADDON_NAME = "Bootstrap Addon Sync"
ADDON_VERSION = "0.5.1"
MANIFEST_SCHEMA = 1
MANIFEST_FILE_DEFAULT = "_addon_sync_manifest.json"

SENSITIVE_KEY_HINTS = (
    "token", "secret", "password", "passwd", "api_key", "apikey", "key",
    "auth", "credential", "cookie", "session", "local_path", "path",
    "cache", "folder", "directory", "dir", "email",
)


def _default_config() -> Dict[str, Any]:
    return {
        "manifest_filename": MANIFEST_FILE_DEFAULT,
        "exclude_self": True,
        "auto_export_after_anki_sync": False,
        "auto_check_after_anki_sync": False,
        "copy_codes_separator": " ",
        "allow_auto_install": True,
        "enabled_state_sync": {
            "enabled": True,
            "apply_after_install": True,
        },
        "config_sync": {
            "enabled": True,
            "prompt_on_export": True,
            "prompt_on_apply": True,
            "apply_on_import": False,
            "include_all_non_sensitive": True,
            "prompt_field_selection": True,
            "whitelist": {},
            "deny_key_hints": list(SENSITIVE_KEY_HINTS),
        },
    }


def get_config() -> Dict[str, Any]:
    cfg = mw.addonManager.getConfig(__name__) if mw and mw.addonManager else None
    base = _default_config()
    if isinstance(cfg, dict):
        # shallow merge plus config_sync merge
        merged = dict(base)
        merged.update(cfg)
        cs = dict(base.get("config_sync", {}))
        if isinstance(cfg.get("config_sync"), dict):
            cs.update(cfg["config_sync"])
        merged["config_sync"] = cs
        ss = dict(base.get("enabled_state_sync", {}))
        if isinstance(cfg.get("enabled_state_sync"), dict):
            ss.update(cfg["enabled_state_sync"])
        merged["enabled_state_sync"] = ss
        return merged
    return base


def addons_root() -> Path:
    # addonsFolder() exists in modern Anki. Some older builds only accept a module name.
    try:
        return Path(mw.addonManager.addonsFolder())
    except TypeError:
        return Path(mw.addonManager.addonsFolder(__name__)).parent


def this_addon_folder_name() -> str:
    return Path(__file__).resolve().parent.name


def media_dir() -> Path:
    if not mw or not mw.col:
        raise RuntimeError("No Anki collection is currently open.")
    return Path(mw.col.media.dir())


def manifest_path() -> Path:
    filename = str(get_config().get("manifest_filename") or MANIFEST_FILE_DEFAULT)
    if not filename.endswith(".json"):
        filename += ".json"
    # Keep it in the collection media folder so AnkiWeb media sync carries it.
    return media_dir() / filename


def read_json_file(path: Path, default: Any = None) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(str(tmp), str(path))


def is_sensitive_key(key: str) -> bool:
    deny = get_config().get("config_sync", {}).get("deny_key_hints", list(SENSITIVE_KEY_HINTS))
    lowered = key.lower()
    return any(str(hint).lower() in lowered for hint in deny)



def safe_config_subset(
    addon_folder: str,
    meta: Dict[str, Any],
    include_configs: bool = False,
    selected_fields: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, Any]:
    """Return selected top-level add-on config values for the synced manifest.

    v0.5.0 supports an explicit checkbox dialog. When selected_fields is supplied,
    the user's selections are authoritative, including normally-sensitive keys.
    Without selected_fields, the older behavior remains: whitelist, or all
    non-sensitive keys after user confirmation.
    """
    cfg = get_config()
    cs = cfg.get("config_sync", {}) if isinstance(cfg.get("config_sync"), dict) else {}
    if not cs.get("enabled"):
        return {}

    source_config = meta.get("config") if isinstance(meta, dict) else None
    if not isinstance(source_config, dict):
        return {}

    result: Dict[str, Any] = {}

    if selected_fields is not None:
        candidate_keys = selected_fields.get(addon_folder, [])
    else:
        whitelist = cs.get("whitelist") or {}
        if not isinstance(whitelist, dict):
            whitelist = {}
        keys = whitelist.get(addon_folder, [])
        if isinstance(keys, list) and keys:
            candidate_keys = [k for k in keys if isinstance(k, str)]
        elif include_configs and cs.get("include_all_non_sensitive", True):
            candidate_keys = [k for k in source_config.keys() if isinstance(k, str) and not is_sensitive_key(k)]
        else:
            candidate_keys = []

    for key in candidate_keys:
        if not isinstance(key, str):
            continue
        if key in source_config:
            try:
                json.dumps(source_config[key], ensure_ascii=False)
            except Exception:
                continue
            result[key] = source_config[key]
    return result

def addon_display_name(folder: Path, meta: Dict[str, Any]) -> str:
    # Anki add-on meta files vary. Try common locations, then fall back to folder name.
    for key in ("name", "mod", "human_name"):
        val = meta.get(key) if isinstance(meta, dict) else None
        if isinstance(val, str) and val.strip():
            return val.strip()
    manifest = read_json_file(folder / "manifest.json", {})
    if isinstance(manifest, dict):
        val = manifest.get("name")
        if isinstance(val, str) and val.strip():
            return val.strip()
    return folder.name


def list_installed_addons(include_configs: bool = False, selected_fields: Optional[Dict[str, List[str]]] = None) -> List[Dict[str, Any]]:
    root = addons_root()
    cfg = get_config()
    self_folder = this_addon_folder_name()
    addons: List[Dict[str, Any]] = []

    if not root.exists():
        return addons

    for folder in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not folder.is_dir():
            continue
        if not (folder / "__init__.py").exists():
            continue
        if cfg.get("exclude_self", True) and folder.name == self_folder:
            continue

        meta = read_json_file(folder / "meta.json", {})
        if not isinstance(meta, dict):
            meta = {}

        addon_id = folder.name if folder.name.isdigit() else None
        entry: Dict[str, Any] = {
            "folder": folder.name,
            "id": addon_id,
            "name": addon_display_name(folder, meta),
            "source": "ankiweb" if addon_id else "manual",
            "enabled": not bool(meta.get("disabled", False)),
        }

        cfg_subset = safe_config_subset(folder.name, meta, include_configs=include_configs, selected_fields=selected_fields)
        if cfg_subset:
            entry["config"] = cfg_subset

        addons.append(entry)

    return addons



def _qt_checked():
    try:
        return Qt.CheckState.Checked
    except Exception:
        return Qt.Checked


def _qt_unchecked():
    try:
        return Qt.CheckState.Unchecked
    except Exception:
        return Qt.Unchecked


def _item_is_checked(item: QTreeWidgetItem) -> bool:
    try:
        return item.checkState(0) == Qt.CheckState.Checked
    except Exception:
        return item.checkState(0) == Qt.Checked


def collect_config_candidates() -> List[Dict[str, Any]]:
    """Collect JSON-serializable top-level config keys for the selection dialog."""
    root = addons_root()
    cfg = get_config()
    self_folder = this_addon_folder_name()
    candidates: List[Dict[str, Any]] = []

    if not root.exists():
        return candidates

    whitelist = cfg.get("config_sync", {}).get("whitelist") or {}
    if not isinstance(whitelist, dict):
        whitelist = {}

    for folder in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not folder.is_dir() or not (folder / "__init__.py").exists():
            continue
        if cfg.get("exclude_self", True) and folder.name == self_folder:
            continue
        meta = read_json_file(folder / "meta.json", {})
        if not isinstance(meta, dict):
            continue
        source_config = meta.get("config")
        if not isinstance(source_config, dict) or not source_config:
            continue

        keys = []
        whitelist_keys = whitelist.get(folder.name, [])
        whitelist_set = {str(k) for k in whitelist_keys} if isinstance(whitelist_keys, list) else set()
        for key in sorted(source_config.keys(), key=lambda x: str(x).lower()):
            if not isinstance(key, str):
                continue
            try:
                json.dumps(source_config[key], ensure_ascii=False)
            except Exception:
                continue
            sensitive = is_sensitive_key(key)
            default_checked = (key in whitelist_set) or (not sensitive and cfg.get("config_sync", {}).get("include_all_non_sensitive", True))
            keys.append({
                "key": key,
                "sensitive": sensitive,
                "default_checked": bool(default_checked),
            })
        if keys:
            candidates.append({
                "folder": folder.name,
                "id": folder.name if folder.name.isdigit() else None,
                "name": addon_display_name(folder, meta),
                "keys": keys,
            })
    return candidates


def choose_config_fields_dialog() -> Optional[Dict[str, List[str]]]:
    """Return {addon_folder: [selected config keys]} or None when cancelled."""
    candidates = collect_config_candidates()
    if not candidates:
        showInfo("No JSON add-on config fields were found to export.")
        return {}

    dialog = QDialog(mw)
    dialog.setWindowTitle(f"{ADDON_NAME} - Select config fields")
    dialog.resize(820, 620)

    layout = QVBoxLayout(dialog)
    label = QLabel(
        "Choose which add-on config fields to sync.\n"
        "Fields that look sensitive or machine-specific are shown unchecked by default. "
        "You may still check them explicitly if you accept the risk."
    )
    label.setWordWrap(True)
    layout.addWidget(label)

    tree = QTreeWidget(dialog)
    tree.setHeaderLabels(["Sync", "Add-on / config field", "Risk"])
    try:
        tree.setSelectionMode(QTreeWidget.SelectionMode.NoSelection)
    except Exception:
        pass
    tree.setColumnWidth(0, 70)
    tree.setColumnWidth(1, 520)
    layout.addWidget(tree)

    parent_items: Dict[str, QTreeWidgetItem] = {}
    child_items: List[Tuple[str, str, QTreeWidgetItem]] = []

    for addon in candidates:
        title = f"{addon.get('id') or 'manual'} — {addon.get('name') or addon.get('folder')}"
        parent = QTreeWidgetItem(tree, ["", title, ""])
        parent.setExpanded(True)
        parent_items[str(addon["folder"])] = parent
        any_checked = False
        for info in addon.get("keys", []):
            key = str(info["key"])
            sensitive = bool(info.get("sensitive"))
            risk = "unchecked by default: sensitive/local-looking" if sensitive else "normal"
            child = QTreeWidgetItem(parent, ["", key, risk])
            child.setCheckState(0, _qt_checked() if info.get("default_checked") else _qt_unchecked())
            any_checked = any_checked or bool(info.get("default_checked"))
            child_items.append((str(addon["folder"]), key, child))
        parent.setCheckState(0, _qt_checked() if any_checked else _qt_unchecked())

    def set_all(state):
        for _folder, _key, child in child_items:
            child.setCheckState(0, state)
        for parent in parent_items.values():
            parent.setCheckState(0, state)

    buttons = QHBoxLayout()
    btn_safe = QPushButton("Select safe defaults", dialog)
    btn_all = QPushButton("Select all", dialog)
    btn_none = QPushButton("Select none", dialog)
    btn_ok = QPushButton("Export selected", dialog)
    btn_cancel = QPushButton("Cancel", dialog)
    buttons.addWidget(btn_safe)
    buttons.addWidget(btn_all)
    buttons.addWidget(btn_none)
    buttons.addStretch(1)
    buttons.addWidget(btn_ok)
    buttons.addWidget(btn_cancel)
    layout.addLayout(buttons)

    def select_safe_defaults():
        for addon in candidates:
            folder = str(addon["folder"])
            any_checked = False
            for info in addon.get("keys", []):
                key = str(info["key"])
                for f, k, child in child_items:
                    if f == folder and k == key:
                        checked = bool(info.get("default_checked"))
                        child.setCheckState(0, _qt_checked() if checked else _qt_unchecked())
                        any_checked = any_checked or checked
                        break
            parent_items[folder].setCheckState(0, _qt_checked() if any_checked else _qt_unchecked())

    btn_safe.clicked.connect(select_safe_defaults)
    btn_all.clicked.connect(lambda: set_all(_qt_checked()))
    btn_none.clicked.connect(lambda: set_all(_qt_unchecked()))
    btn_ok.clicked.connect(dialog.accept)
    btn_cancel.clicked.connect(dialog.reject)

    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None

    selected: Dict[str, List[str]] = {}
    sensitive_selected: List[str] = []
    for folder, key, child in child_items:
        if _item_is_checked(child):
            selected.setdefault(folder, []).append(key)
            if is_sensitive_key(key):
                sensitive_selected.append(f"{folder}: {key}")

    if sensitive_selected:
        if not askUser(
            "You selected fields that look sensitive or machine-specific.\n\n"
            + "\n".join(sensitive_selected[:60])
            + (f"\n...and {len(sensitive_selected) - 60} more" if len(sensitive_selected) > 60 else "")
            + "\n\nExport these values anyway?"
        ):
            return None

    return selected

def build_manifest(include_configs: bool = False, selected_fields: Optional[Dict[str, List[str]]] = None) -> Dict[str, Any]:
    notes = [
        "This file is declarative. It is not Python code and should not be executed.",
        "Only AnkiWeb numeric add-on IDs are suitable for one-click/manual code installation.",
    ]
    if include_configs:
        notes.append(
            "Some add-on config values are included. Exported keys were selected explicitly in the checkbox dialog when config_selection_mode is explicit."
        )
    return {
        "schema": MANIFEST_SCHEMA,
        "source": "bootstrap-addon-sync",
        "addon_version": ADDON_VERSION,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "profile": getattr(mw.pm, "name", None) if mw and mw.pm else None,
        "config_included": bool(include_configs),
        "config_selection_mode": "explicit" if selected_fields is not None else "filtered",
        "addons": list_installed_addons(include_configs=include_configs, selected_fields=selected_fields),
        "notes": notes,
    }


def ask_include_configs_on_export() -> bool:
    cs = get_config().get("config_sync", {})
    if not isinstance(cs, dict) or not cs.get("enabled", True):
        return False
    if not cs.get("prompt_on_export", True):
        return bool(cs.get("auto_include_on_export", False))
    return askUser(
        "Also sync add-on configurations in this manifest?\n\n"
        "Next you will see a checkbox list of config fields. Fields that look like token/password/api_key/path/cache/etc. are unchecked by default, but you can explicitly allow them.\n\n"
        "The target computer will still ask before applying them."
    )


def export_manifest(show_message: bool = True, ask_configs: bool = True) -> Optional[Dict[str, Any]]:
    try:
        include_configs = ask_include_configs_on_export() if ask_configs else False
        selected_fields = None
        if include_configs and get_config().get("config_sync", {}).get("prompt_field_selection", True):
            selected_fields = choose_config_fields_dialog()
            if selected_fields is None:
                return None
        data = build_manifest(include_configs=include_configs, selected_fields=selected_fields)
        path = manifest_path()
        atomic_write_json(path, data)
        if show_message:
            showInfo(
                f"Exported {len(data.get('addons', []))} add-ons to:\n\n{path}\n\n"
                + ("Included non-sensitive add-on config values.\n\n" if data.get("config_included") else "")
                + "Run Anki sync so this media file reaches your other computer."
            )
        return data
    except Exception as exc:
        showWarning(f"{ADDON_NAME}: export failed.\n\n{exc}\n\n{traceback.format_exc()}")
        return None


def read_manifest() -> Optional[Dict[str, Any]]:
    path = manifest_path()
    data = read_json_file(path, None)
    if not isinstance(data, dict):
        return None
    if data.get("source") != "bootstrap-addon-sync":
        return None
    return data


def installed_folder_names() -> set:
    return {a.get("folder") for a in list_installed_addons() if a.get("folder")}


def installed_ankiweb_ids() -> set:
    result = set()
    for item in list_installed_addons():
        if item.get("id"):
            result.add(str(item["id"]))
    # Include self as installed even if excluded from list_installed_addons().
    sf = this_addon_folder_name()
    if sf.isdigit():
        result.add(sf)
    return result


def diff_manifest(data: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    installed_ids = installed_ankiweb_ids()
    installed_folders = installed_folder_names()
    missing_ankiweb: List[Dict[str, Any]] = []
    missing_manual: List[Dict[str, Any]] = []
    present: List[Dict[str, Any]] = []

    for addon in data.get("addons", []):
        if not isinstance(addon, dict):
            continue
        addon_id = str(addon.get("id")) if addon.get("id") else None
        folder = str(addon.get("folder")) if addon.get("folder") else None
        if addon_id and addon_id in installed_ids:
            present.append(addon)
        elif folder and folder in installed_folders:
            present.append(addon)
        elif addon_id and addon.get("source") == "ankiweb":
            missing_ankiweb.append(addon)
        else:
            missing_manual.append(addon)
    return missing_ankiweb, missing_manual, present


def format_addon_line(addon: Dict[str, Any]) -> str:
    addon_id = addon.get("id") or "manual"
    name = addon.get("name") or addon.get("folder") or "unknown"
    return f"{addon_id} — {name}"



def installed_addon_entries_by_folder() -> Dict[str, Dict[str, Any]]:
    return {str(a.get("folder")): a for a in list_installed_addons() if a.get("folder")}


def resolve_installed_folder(addon: Dict[str, Any]) -> Optional[str]:
    """Resolve a manifest entry to a local add-on folder name, if installed."""
    folder = str(addon.get("folder")) if addon.get("folder") else ""
    if folder and (addons_root() / folder).exists():
        return folder

    addon_id = str(addon.get("id")) if addon.get("id") else ""
    if addon_id and (addons_root() / addon_id).exists():
        return addon_id

    return None


def desired_enabled_changes(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return installed add-ons whose enabled/disabled state differs from the manifest."""
    if not get_config().get("enabled_state_sync", {}).get("enabled", True):
        return []

    current_by_folder = installed_addon_entries_by_folder()
    changes: List[Dict[str, Any]] = []

    for addon in data.get("addons", []):
        if not isinstance(addon, dict) or "enabled" not in addon:
            continue
        folder = resolve_installed_folder(addon)
        if not folder or folder == this_addon_folder_name():
            continue
        current = current_by_folder.get(folder)
        if not current:
            continue
        desired = bool(addon.get("enabled"))
        actual = bool(current.get("enabled"))
        if desired != actual:
            changed = dict(addon)
            changed["folder"] = folder
            changed["current_enabled"] = actual
            changed["desired_enabled"] = desired
            changes.append(changed)

    return changes


def set_addon_enabled_state(folder: str, enabled: bool) -> None:
    """Persist enabled/disabled state by editing Anki's add-on meta.json.

    This mirrors Anki's normal add-on switch: meta.json uses disabled=true for off.
    A restart is usually needed for already-loaded add-ons to actually unload/load.
    """
    meta_path = addons_root() / folder / "meta.json"
    meta = read_json_file(meta_path, {})
    if not isinstance(meta, dict):
        meta = {}
    if enabled:
        meta["disabled"] = False
    else:
        meta["disabled"] = True
    atomic_write_json(meta_path, meta)


def apply_enabled_states(data: Optional[Dict[str, Any]] = None, ask: bool = True, show_message: bool = True) -> int:
    if data is None:
        data = read_manifest()
    if not data:
        if show_message:
            showWarning(
                f"No valid manifest found at:\n\n{manifest_path()}\n\n"
                "Sync media first, or export a manifest from the source computer."
            )
        return 0

    changes = desired_enabled_changes(data)
    if not changes:
        if show_message:
            showInfo("Enabled/disabled add-on states already match the manifest.")
        return 0

    lines = []
    for addon in changes[:80]:
        state = "enable" if addon.get("desired_enabled") else "disable"
        lines.append(f"{state}: {format_addon_line(addon)}")

    if ask and not askUser(
        "Apply enabled/disabled add-on states from the manifest?\n\n"
        + "\n".join(lines)
        + (f"\n...and {len(changes) - 80} more" if len(changes) > 80 else "")
        + "\n\nRestart Anki afterwards so the changes fully take effect."
    ):
        return 0

    applied = 0
    for addon in changes:
        folder = str(addon.get("folder") or "")
        if not folder:
            continue
        set_addon_enabled_state(folder, bool(addon.get("desired_enabled")))
        applied += 1

    if show_message:
        showInfo(f"Applied enabled/disabled state to {applied} add-on(s). Restart Anki.")
    return applied


def manifest_allows_config_key(data: Dict[str, Any], key: str) -> bool:
    """Older manifests used filtered mode; newer explicit manifests already reflect user checkbox consent."""
    if data.get("config_selection_mode") == "explicit":
        return True
    return not is_sensitive_key(key)

def config_changes_from_manifest(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return installed add-ons whose manifest config differs from local config."""
    if not get_config().get("config_sync", {}).get("enabled", True):
        return []

    changes: List[Dict[str, Any]] = []
    root = addons_root()
    for addon in data.get("addons", []):
        if not isinstance(addon, dict) or not isinstance(addon.get("config"), dict):
            continue
        folder = resolve_installed_folder(addon)
        if not folder or folder == this_addon_folder_name():
            continue
        meta_path = root / folder / "meta.json"
        meta = read_json_file(meta_path, {})
        if not isinstance(meta, dict):
            meta = {}
        current = meta.get("config") if isinstance(meta.get("config"), dict) else {}
        if not isinstance(current, dict):
            current = {}
        key_changes = []
        for key, value in addon["config"].items():
            if not isinstance(key, str) or not manifest_allows_config_key(data, key):
                continue
            if current.get(key) != value:
                key_changes.append({"key": key, "old": current.get(key), "new": value})
        if key_changes:
            item = dict(addon)
            item["folder"] = folder
            item["config_changes"] = key_changes
            changes.append(item)
    return changes


def apply_configs_from_manifest(data: Optional[Dict[str, Any]] = None, ask: bool = True, show_message: bool = True) -> int:
    if data is None:
        data = read_manifest()
    if not data:
        if show_message:
            showWarning(
                f"No valid manifest found at:\n\n{manifest_path()}\n\n"
                "Sync media first, or export a manifest from the source computer."
            )
        return 0

    changes = config_changes_from_manifest(data)
    if not changes:
        if show_message:
            showInfo("No applicable add-on config differences found in the manifest.")
        return 0

    lines = []
    total_keys = 0
    for addon in changes[:40]:
        keys = [c["key"] for c in addon.get("config_changes", [])]
        total_keys += len(keys)
        lines.append(f"{format_addon_line(addon)}: " + ", ".join(keys[:20]))
        if len(keys) > 20:
            lines.append(f"  ...and {len(keys) - 20} more keys")

    if ask and not askUser(
        "Apply add-on configuration values from the manifest?\n\n"
        + "\n".join(lines)
        + (f"\n...and {len(changes) - 40} more add-ons" if len(changes) > 40 else "")
        + "\n\nOnly non-sensitive manifest keys will be written. Existing keys not in the manifest are preserved. Restart Anki if needed."
    ):
        return 0

    applied_addons = 0
    applied_keys = 0
    root = addons_root()
    for addon in changes:
        folder = str(addon.get("folder") or "")
        if not folder:
            continue
        meta_path = root / folder / "meta.json"
        meta = read_json_file(meta_path, {})
        if not isinstance(meta, dict):
            meta = {}
        current = meta.get("config") if isinstance(meta.get("config"), dict) else {}
        current = dict(current) if isinstance(current, dict) else {}
        for change in addon.get("config_changes", []):
            key = change.get("key")
            if isinstance(key, str) and manifest_allows_config_key(data, key):
                current[key] = change.get("new")
                applied_keys += 1
        meta["config"] = current
        atomic_write_json(meta_path, meta)
        applied_addons += 1

    if show_message:
        showInfo(f"Applied {applied_keys} config key(s) to {applied_addons} add-on(s). Restart Anki if needed.")
    return applied_addons


def missing_report(data: Dict[str, Any]) -> str:
    missing_ankiweb, missing_manual, present = diff_manifest(data)
    updated = data.get("updated_at", "unknown")
    state_changes = desired_enabled_changes(data)
    config_changes = config_changes_from_manifest(data)
    lines = [
        f"Manifest updated: {updated}",
        f"Config included in manifest: {bool(data.get('config_included'))}",
        f"Installed from manifest already present: {len(present)}",
        f"Missing AnkiWeb add-ons: {len(missing_ankiweb)}",
        f"Missing manual/local add-ons: {len(missing_manual)}",
        f"Enabled/disabled state changes available: {len(state_changes)}",
        f"Config changes available: {len(config_changes)}",
    ]

    if missing_ankiweb:
        lines.append("\nMissing AnkiWeb add-ons:")
        lines.extend("  " + format_addon_line(a) for a in missing_ankiweb)

    if missing_manual:
        lines.append("\nManual/local add-ons not installable by code:")
        lines.extend("  " + format_addon_line(a) for a in missing_manual)

    if state_changes:
        lines.append("\nEnabled/disabled state differences:")
        for addon in state_changes:
            state = "ON" if addon.get("desired_enabled") else "OFF"
            lines.append("  " + format_addon_line(addon) + f" -> {state}")

    if not missing_ankiweb and not missing_manual and not state_changes:
        lines.append("\nNo missing add-ons or state differences found.")

    return "\n".join(lines)


def missing_ankiweb_codes(data: Dict[str, Any]) -> List[int]:
    """Return validated numeric AnkiWeb IDs for missing add-ons."""
    missing_ankiweb, _missing_manual, _present = diff_manifest(data)
    codes: List[int] = []
    for addon in missing_ankiweb:
        raw = str(addon.get("id", "")).strip()
        # Hard safety gate: only AnkiWeb numeric IDs from the declarative manifest.
        if raw.isdigit():
            codes.append(int(raw))
    return codes


def prompt_missing_action(report: str, install_count: int) -> str:
    """Ask whether to install, copy codes, or cancel. Returns install/copy/cancel."""
    box = QMessageBox(mw)
    box.setWindowTitle(ADDON_NAME)
    box.setIcon(QMessageBox.Icon.Question)
    box.setText("Missing AnkiWeb add-ons were found.")
    box.setDetailedText(report)
    install_btn = None
    if install_count and get_config().get("allow_auto_install", True):
        install_btn = box.addButton(
            f"Install {install_count} from AnkiWeb",
            QMessageBox.ButtonRole.AcceptRole,
        )
    copy_btn = box.addButton("Copy codes", QMessageBox.ButtonRole.ActionRole)
    cancel_btn = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(install_btn or copy_btn)
    box.exec()
    clicked = box.clickedButton()
    if install_btn is not None and clicked == install_btn:
        return "install"
    if clicked == copy_btn:
        return "copy"
    if clicked == cancel_btn:
        return "cancel"
    return "cancel"


def install_missing_addons_from_manifest() -> None:
    data = read_manifest()
    if not data:
        showWarning(
            f"No valid manifest found at:\n\n{manifest_path()}\n\n"
            "Sync media first, or export a manifest from the source computer."
        )
        return

    codes = missing_ankiweb_codes(data)
    if not codes:
        showInfo("No missing AnkiWeb add-ons to install.")
        return

    names = []
    missing_ankiweb, _missing_manual, _present = diff_manifest(data)
    for addon in missing_ankiweb:
        if str(addon.get("id", "")).isdigit():
            names.append(format_addon_line(addon))

    if not askUser(
        "Install the following missing add-ons from AnkiWeb?\n\n"
        + "\n".join(names[:60])
        + (f"\n...and {len(names) - 60} more" if len(names) > 60 else "")
        + "\n\nOnly numeric AnkiWeb IDs will be installed. Restart Anki after installation."
    ):
        return

    try:
        from aqt.addons import download_addons, show_log_to_user
    except Exception as exc:
        sep = str(get_config().get("copy_codes_separator", " "))
        QApplication.clipboard().setText(sep.join(str(c) for c in codes))
        showWarning(
            "This Anki version does not expose the add-on downloader API expected by this plugin.\n\n"
            f"Copied the missing codes instead:\n\n{sep.join(str(c) for c in codes)}\n\n"
            f"Technical detail: {exc}"
        )
        return

    def on_done(log: List[Any]) -> None:
        applied_states = 0
        if get_config().get("enabled_state_sync", {}).get("apply_after_install", True):
            applied_states = apply_enabled_states(data, ask=False, show_message=False)

        if log:
            try:
                show_log_to_user(mw, log)
            except Exception:
                showInfo("Add-on download finished. Restart Anki to load newly installed add-ons.")
        else:
            showInfo("No add-ons were installed. They may already be installed or unavailable.")

        if applied_states:
            showInfo(f"Installed add-on download finished and applied enabled/disabled state to {applied_states} add-on(s). Restart Anki.")
        else:
            tooltip(f"{ADDON_NAME}: add-on install finished; restart Anki")

    try:
        tooltip(f"{ADDON_NAME}: installing {len(codes)} add-on(s) from AnkiWeb...")
        download_addons(mw, mw.addonManager, codes, on_done, force_enable=False)
    except Exception as exc:
        sep = str(get_config().get("copy_codes_separator", " "))
        QApplication.clipboard().setText(sep.join(str(c) for c in codes))
        showWarning(
            "Automatic installation failed. Copied the missing codes so you can install manually.\n\n"
            f"Codes:\n{sep.join(str(c) for c in codes)}\n\n"
            f"Error:\n{exc}\n\n{traceback.format_exc()}"
        )


def copy_missing_codes() -> None:
    data = read_manifest()
    if not data:
        showWarning(
            f"No valid manifest found at:\n\n{manifest_path()}\n\n"
            "Sync media first, or export a manifest from the source computer."
        )
        return

    codes = [str(c) for c in missing_ankiweb_codes(data)]
    if not codes:
        showInfo("No missing AnkiWeb add-on codes to copy.")
        return

    sep = str(get_config().get("copy_codes_separator", " "))
    QApplication.clipboard().setText(sep.join(codes))
    showInfo(
        "Copied missing AnkiWeb add-on code(s) to clipboard:\n\n"
        + sep.join(codes)
        + "\n\nPaste them into Tools > Add-ons > Get Add-ons."
    )


def check_missing(show_when_none: bool = True) -> None:
    data = read_manifest()
    if not data:
        if show_when_none:
            showWarning(
                f"No valid manifest found at:\n\n{manifest_path()}\n\n"
                "On the first computer, use Tools > Bootstrap Addon Sync > Export Manifest, then run Anki sync."
            )
        return

    report = missing_report(data)
    missing_ankiweb, missing_manual, _present = diff_manifest(data)
    state_changes = desired_enabled_changes(data)
    config_changes = config_changes_from_manifest(data)

    # Manual checks are interactive. Automatic checks after Anki sync must not nag
    # about manual/local add-ons; those are informational, not actionable by code.
    if missing_ankiweb:
        action = prompt_missing_action(report, len(missing_ankiweb_codes(data)))
        if action == "install":
            install_missing_addons_from_manifest()
        elif action == "copy":
            copy_missing_codes()
    elif state_changes and show_when_none:
        if askUser(report + "\n\nApply these enabled/disabled states now?"):
            apply_enabled_states(data, ask=False, show_message=True)
    elif config_changes and show_when_none:
        if askUser(report + "\n\nApply these add-on config values now?"):
            apply_configs_from_manifest(data, ask=False, show_message=True)
    else:
        if show_when_none:
            showInfo(report)

    cs = get_config().get("config_sync", {})
    if cs.get("apply_on_import") and show_when_none:
        apply_configs_from_manifest(data, ask=cs.get("prompt_on_apply", True), show_message=True)

def open_manifest_folder() -> None:
    try:
        path = manifest_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        openFolder(str(path.parent))
    except Exception as exc:
        showWarning(f"Could not open media folder.\n\n{exc}")


def show_installed_summary() -> None:
    addons = list_installed_addons()
    ankiweb = [a for a in addons if a.get("id")]
    manual = [a for a in addons if not a.get("id")]
    lines = [
        f"Detected installed add-ons: {len(addons)}",
        f"AnkiWeb-code add-ons: {len(ankiweb)}",
        f"Manual/local add-ons: {len(manual)}",
        "",
    ]
    for addon in addons[:80]:
        lines.append(format_addon_line(addon))
    if len(addons) > 80:
        lines.append(f"...and {len(addons) - 80} more")
    showInfo("\n".join(lines))


def on_anki_sync_finish(*args: Any, **kwargs: Any) -> None:
    cfg = get_config()
    if cfg.get("auto_export_after_anki_sync"):
        export_manifest(show_message=False, ask_configs=False)
        tooltip(f"{ADDON_NAME}: manifest exported")
    if cfg.get("auto_check_after_anki_sync"):
        check_missing(show_when_none=False)


def setup_menu() -> None:
    if not mw:
        return

    menu = QMenu("Bootstrap Addon Sync", mw)

    action_export = QAction("Export manifest to media", mw)
    action_export.triggered.connect(lambda: export_manifest(show_message=True))
    menu.addAction(action_export)

    action_check = QAction("Check missing add-ons from manifest", mw)
    action_check.triggered.connect(lambda: check_missing(show_when_none=True))
    menu.addAction(action_check)

    action_copy = QAction("Copy missing AnkiWeb codes", mw)
    action_copy.triggered.connect(copy_missing_codes)
    menu.addAction(action_copy)

    action_install = QAction("Install missing AnkiWeb add-ons", mw)
    action_install.triggered.connect(install_missing_addons_from_manifest)
    menu.addAction(action_install)

    action_apply_states = QAction("Apply enabled/disabled states from manifest", mw)
    action_apply_states.triggered.connect(lambda: apply_enabled_states(None, ask=True, show_message=True))
    menu.addAction(action_apply_states)

    action_apply_configs = QAction("Apply add-on configs from manifest", mw)
    action_apply_configs.triggered.connect(lambda: apply_configs_from_manifest(None, ask=True, show_message=True))
    menu.addAction(action_apply_configs)

    menu.addSeparator()

    action_summary = QAction("Show installed add-on summary", mw)
    action_summary.triggered.connect(show_installed_summary)
    menu.addAction(action_summary)

    action_open = QAction("Open media folder", mw)
    action_open.triggered.connect(open_manifest_folder)
    menu.addAction(action_open)

    mw.form.menuTools.addMenu(menu)


setup_menu()

if gui_hooks is not None and hasattr(gui_hooks, "sync_did_finish"):
    gui_hooks.sync_did_finish.append(on_anki_sync_finish)
