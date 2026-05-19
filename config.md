# Bootstrap Addon Sync configuration

This add-on syncs a declarative add-on manifest through Anki's media sync. It does not execute Python from cards or media files.

## Options

- `manifest_filename`: JSON file written to the collection media folder. Default: `_addon_sync_manifest.json`.
- `exclude_self`: Do not include Bootstrap Addon Sync itself in the exported manifest.
- `auto_export_after_anki_sync`: Export the manifest after Anki collection sync finishes. Automatic export does **not** include configs by default, because it cannot ask you.
- `auto_check_after_anki_sync`: Check for missing add-ons after Anki collection sync finishes. Default is `false` to avoid a pop-up after every normal sync.
- `copy_codes_separator`: Separator used when copying missing AnkiWeb codes.
- `allow_auto_install`: Show the confirmed auto-install option for missing numeric AnkiWeb IDs. Set to `false` to force copy-only mode.

## Enabled/disabled state sync

The manifest stores whether each add-on is enabled. Use:

`Tools > Bootstrap Addon Sync > Apply enabled/disabled states from manifest`

This writes the target state into each installed add-on's `meta.json`. Restart Anki afterwards so already-loaded add-ons can fully load/unload.

```json
"enabled_state_sync": {
  "enabled": true,
  "apply_after_install": true
}
```

## Config sync

v0.5.0 can sync add-on config values. On manual export, it asks whether to include configs. On the target computer, use:

`Tools > Bootstrap Addon Sync > Apply add-on configs from manifest`

It will ask again before writing anything.

```json
"config_sync": {
  "enabled": true,
  "prompt_on_export": true,
  "prompt_on_apply": true,
  "apply_on_import": false,
  "include_all_non_sensitive": true,
  "whitelist": {},
  "deny_key_hints": ["token", "password", "api_key", "path", "cache"]
}
```

Behavior:

- If `include_all_non_sensitive` is true, manual export can include all top-level config keys except keys whose names match `deny_key_hints`.
- If `whitelist` has entries for an add-on folder/ID, only those keys are exported for that add-on.
- Existing target-side config keys not present in the manifest are preserved.
- Sensitive or machine-local keys are skipped even if they appear in a whitelist.

Use config sync for UI preferences and ordinary settings, not for credentials or local paths.


## v0.5.0

Adds a checkbox-based config field selector. Sensitive or machine-local-looking keys are unchecked by default, including token, secret, password, passwd, api_key, apikey, key, auth, credential, cookie, session, local_path, path, cache, folder, directory, dir, and email. Explicitly checked fields are exported and can be applied on the target computer after confirmation.
