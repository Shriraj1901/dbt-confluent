"""Unit tests for the action decision made by `decide_action`.

Renders the real helpers.sql with plain jinja2 and stand-ins for the dbt context the macro
touches, and checks which action `_classify_action` picks for the relation already in the
warehouse.
"""

from pathlib import Path
from unittest.mock import MagicMock

import jinja2
import pytest

from dbt.adapters.confluent.impl import ConfluentRelation

MACRO_FILE = (
    Path(__file__).resolve().parents[2]
    / "dbt/include/confluent/macros/materializations/models/helpers.sql"
)


class _MacroReturn(Exception):
    """Stand-in for the exception dbt's `return()` global raises to leave a macro."""

    def __init__(self, value):
        self.value = value


def _return(value):
    raise _MacroReturn(value)


def _classify(existing, *, full_refresh=False, recoverable=False, needs_restart=False):
    adapter = MagicMock()
    adapter.statement_needs_restart.return_value = needs_restart
    env = jinja2.Environment(extensions=["jinja2.ext.do"])
    env.globals.update(
        {
            "return": _return,
            "adapter": adapter,
            "should_full_refresh": lambda: full_refresh,
            "get_statement_name": lambda suffix="": "my-model" + suffix,
        }
    )
    template = env.from_string(
        MACRO_FILE.read_text() + "{{ _classify_action(existing, recoverable) }}"
    )
    try:
        template.render(existing=existing, recoverable=recoverable)
    except _MacroReturn as returned:
        return returned.value
    raise AssertionError("macro did not call return()")


def _relation(relation_type: str) -> ConfluentRelation:
    return ConfluentRelation.create(
        database="env-1", schema="cluster-a", identifier="my_model", type=relation_type
    )


def test_no_existing_relation_creates():
    assert _classify(None) == "create"


def test_existing_table_is_skipped():
    assert _classify(_relation("table")) == "skip"


def test_existing_table_with_dead_statement_restarts():
    assert _classify(_relation("table"), recoverable=True, needs_restart=True) == "restart"


@pytest.mark.parametrize("full_refresh", [False, True])
@pytest.mark.parametrize("recoverable", [False, True])
def test_existing_view_is_replaced(full_refresh, recoverable):
    """A view left over from an earlier `view` materialization is not the table this model
    builds; it must be recreated instead of being treated as up to date."""
    assert _classify(_relation("view"), full_refresh=full_refresh, recoverable=recoverable) == (
        "create"
    )
