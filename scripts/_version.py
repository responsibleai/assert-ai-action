"""Single source of truth for the version stamped into gate reports.

This used to be a hand-maintained constant duplicated in compare_runs.py and
detect_test_set_drift.py. Both still said "v1.0.0-rc1" after v1.0.0, v1.0.1 and
v1.0.2 shipped, so every gate report a customer produced was stamped with a
version that was never released -- which is exactly the field you would rely on
when someone reports a bug against a run you cannot reproduce.

Bump this when cutting a release; docs/release-procedure.md says so, and
tests/test_action_version.py fails if the two consumers ever disagree again.
"""

ACTION_VERSION = "v1.0.3"
