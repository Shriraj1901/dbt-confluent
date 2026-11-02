"""Unit tests for `_enforce_schema_drift`, the one place `on_schema_drift` is consumed.

Renders the real helpers.sql with plain jinja2 and stand-ins for the dbt context the macro
touches, and checks what it asks the adapter to do for each setting.
"""

from pathlib import Path
from unittest.mock import MagicMock

import jinja2
import pytest

from tests.unit._helpers import relation

MACRO_FILE = (
    Path(__file__).resolve().parents[2]
    / "dbt/include/confluent/macros/materializations/models/helpers.sql"
)


class _Config:
    def __init__(self, values):
        self._values = values

    def get(self, key, default=None):
        return self._values.get(key, default)


def _enforce(on_schema_drift, *, restart):
    """Render `_enforce_schema_drift` for an existing relation; return the adapter mock."""
    adapter = MagicMock()
    check = MagicMock()
    env = jinja2.Environment(extensions=["jinja2.ext.do"])
    env.globals.update(
        adapter=adapter,
        this=relation("my_model"),
        execute=True,
        config=_Config({"on_schema_drift": on_schema_drift}),
        check=check,
    )
    # Redefine the drift check after the real one so the macro under test calls the recorder.
    template = env.from_string(
        MACRO_FILE.read_text()
        + "{% macro check_for_schema_drift(existing, has_select_query, enforce='all') %}"
        + "{% do check(enforce) %}{% endmacro %}"
        + "{{ _enforce_schema_drift(existing, true, restart) }}"
    )
    template.render(existing=relation("my_model"), restart=restart)
    return adapter, check


def test_ignore_still_refuses_a_materialized_table():
    """Skipping the drift check must not let a materialized table be adopted as a regular
    one, so the skip path asks the adapter to rule it out."""
    adapter, check = _enforce("ignore", restart=False)
    adapter.raise_if_materialized_table.assert_called_once()
    check.assert_not_called()


def test_ignore_on_restart_runs_the_columns_check():
    """That check already refuses a materialized table, so no separate probe is needed."""
    adapter, check = _enforce("ignore", restart=True)
    adapter.raise_if_materialized_table.assert_not_called()
    check.assert_called_once_with("columns")


@pytest.mark.parametrize("restart", [False, True])
def test_fail_runs_the_full_check(restart):
    adapter, check = _enforce("fail", restart=restart)
    adapter.raise_if_materialized_table.assert_not_called()
    check.assert_called_once_with("all")
