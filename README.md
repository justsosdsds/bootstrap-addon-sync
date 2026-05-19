# Bootstrap Addon Sync for Anki

A small bootstrap add-on that syncs an add-on manifest through Anki media sync.

## Core workflow

1. Install this bootstrap add-on manually on each desktop Anki profile.
2. On the source computer, run `Tools > Bootstrap Addon Sync > Export manifest to media`.
3. Choose whether to include non-sensitive add-on config values.
4. Run normal Anki sync, including media sync.
5. On the target computer, run normal Anki sync.
6. Use the Bootstrap Addon Sync menu to check missing add-ons, install AnkiWeb-code add-ons, apply enabled/disabled states, and optionally apply configs.

## Safety model

- The manifest is JSON, not executable code.
- Automatic installation is limited to numeric AnkiWeb add-on IDs and asks first.
- Manual/local add-ons are reported but not installed automatically.
- Config sync asks before export and before apply.
- Config sync skips keys that look like tokens, passwords, API keys, local paths, caches, or other machine-local/sensitive data.

## Version

0.5.0


## v0.5.0

Adds a checkbox-based config field selector. Sensitive or machine-local-looking keys are unchecked by default, including token, secret, password, passwd, api_key, apikey, key, auth, credential, cookie, session, local_path, path, cache, folder, directory, dir, and email. Explicitly checked fields are exported and can be applied on the target computer after confirmation.
