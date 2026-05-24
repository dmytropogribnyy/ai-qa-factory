"""
Version constants for the Guided QA Automation Workbench.

APP_VERSION
    Increment when CLI behaviour, documented commands, workflow sequences,
    or output formats change — regardless of state schema changes.

STATE_SCHEMA_VERSION
    Increment ONLY when QAFactoryState adds, removes, or renames persisted
    fields. Kept separate from APP_VERSION so saved state files remain
    loadable across app upgrades without migration.

RELEASE_LABEL
    Human-readable label for changelogs, docs headers, and release notes.
    Does not follow semver — it describes the character of the release.
"""

APP_VERSION = "5.1.0"

# No new state fields introduced in this release.
# Keep in sync with SCHEMA_VERSION in core/state.py when that changes.
STATE_SCHEMA_VERSION = "5.0.5"

RELEASE_LABEL = "workbench-alpha"
