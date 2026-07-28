"""Unit tests for transition-screen field routing (resolution / VEX)."""

from __future__ import annotations

from io import StringIO

from jira_cli.commands.edit_issue import (
    coerce_resolution_value,
    split_transition_screen_fields,
)


def test_coerce_resolution_value():
    assert coerce_resolution_value("Not a Bug") == {"name": "Not a Bug"}
    assert coerce_resolution_value("  Done  ") == {"name": "Done"}
    assert coerce_resolution_value("") is None
    assert coerce_resolution_value("   ") is None


def test_split_resolution_requires_transition():
    err = StringIO()
    batch = {"resolution": {"name": "Not a Bug"}, "summary": "keep"}
    fields, rc = split_transition_screen_fields(
        batch,
        transition=None,
        resolution=None,
        vex_field_id=None,
        err=err,
    )
    assert rc == 2
    assert fields == {}
    assert "Resolution can only be set" in err.getvalue()
    assert "resolution" in batch  # not consumed on error


def test_split_resolution_flag_requires_transition():
    err = StringIO()
    batch: dict = {}
    fields, rc = split_transition_screen_fields(
        batch,
        transition=None,
        resolution="Not a Bug",
        vex_field_id=None,
        err=err,
    )
    assert rc == 2
    assert "Resolution can only be set" in err.getvalue()


def test_split_moves_resolution_and_vex_on_transition():
    err = StringIO()
    batch = {
        "resolution": "Not a Bug",
        "customfield_10873": {"value": "Component not Present"},
        "summary": "keep me",
    }
    fields, rc = split_transition_screen_fields(
        batch,
        transition="Closed",
        resolution=None,
        vex_field_id="customfield_10873",
        err=err,
    )
    assert rc == 0
    assert fields == {
        "resolution": {"name": "Not a Bug"},
        "customfield_10873": {"value": "Component not Present"},
    }
    assert batch == {"summary": "keep me"}


def test_split_resolution_flag_overrides_on_transition():
    err = StringIO()
    batch: dict = {}
    fields, rc = split_transition_screen_fields(
        batch,
        transition="Closed",
        resolution="Duplicate",
        vex_field_id="customfield_10873",
        err=err,
    )
    assert rc == 0
    assert fields == {"resolution": {"name": "Duplicate"}}
