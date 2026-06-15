"""Tests for the CLI module."""

import json
import zipfile
import io
from unittest.mock import patch

from click.testing import CliRunner

from omniplan_mcp.cli import cli, _parse_duration_seconds


# ── Sample .oplx data ───────────────────────────────────────────────────────

SAMPLE_ACTUAL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<scenario xmlns="http://www.omnigroup.com/namespace/OmniPlan/v2" id="test">
  <start-date>2024-01-01T00:00:00.000Z</start-date>
  <resource id="r1">
    <name>Alice</name>
    <type>Staff</type>
  </resource>
  <resource id="r2">
    <name>Bob</name>
    <type>Staff</type>
  </resource>
  <task id="t1">
    <title>Design</title>
    <start-date>2024-01-01T00:00:00.000Z</start-date>
    <end-date>2024-01-10T00:00:00.000Z</end-date>
    <effort>28800</effort>
  </task>
  <task id="t2">
    <title>Implementation</title>
    <start-date>2024-01-11T00:00:00.000Z</start-date>
    <end-date>2024-01-20T00:00:00.000Z</end-date>
    <effort>43200</effort>
    <effort-done>14400</effort-done>
  </task>
  <task id="t3">
    <title>Review</title>
    <start-date>2024-01-21T00:00:00.000Z</start-date>
    <end-date>2024-01-25T00:00:00.000Z</end-date>
    <effort>43200</effort>
    <effort-done>43200</effort-done>
  </task>
  <task id="t4">
    <title>Done Milestone</title>
    <type>milestone</type>
    <start-date>2024-01-25T00:00:00.000Z</start-date>
    <end-date>2024-01-25T00:00:00.000Z</end-date>
    <effort>0</effort>
  </task>
</scenario>"""

SAMPLE_TOC_XML = """<?xml version="1.0"?>
<OmniPlanTOC>
  <setting id="viewOption">list</setting>
</OmniPlanTOC>
"""


def _make_oplx_bytes(actual_xml: str = SAMPLE_ACTUAL_XML,
                     toc_xml: str = SAMPLE_TOC_XML) -> bytes:
    """Create an in-memory .oplx ZIP and return its bytes."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr("Actual.xml", actual_xml)
        zf.writestr("__TOC.xml", toc_xml)
    return buf.getvalue()


def _write_temp_oplx(tmp_path, data: bytes = None) -> str:
    """Write an .oplx file to a temp directory and return its path."""
    if data is None:
        data = _make_oplx_bytes()
    filepath = tmp_path / "test.oplx"
    filepath.write_bytes(data)
    return str(filepath)


# ── CLI tests ───────────────────────────────────────────────────────────────

class TestCliBasic:
    """Basic CLI structure tests."""

    def test_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "OmniPlan schedule reader and writer" in result.output
        assert "serve" in result.output
        assert "read" in result.output
        assert "summary" in result.output
        assert "search" in result.output
        assert "tasks" in result.output

    def test_version(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "omniplan-mcp" in result.output


class TestCliReadCommands:
    """Test read-only commands that work from .oplx files."""

    def test_read(self, tmp_path):
        filepath = _write_temp_oplx(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["read", filepath])
        assert result.exit_code == 0, result.output
        assert "Design" in result.output
        assert "Implementation" in result.output
        assert "Review" in result.output
        assert "Alice" in result.output
        assert "Bob" in result.output

    def test_read_json(self, tmp_path):
        filepath = _write_temp_oplx(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["read", filepath, "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert len(data["tasks"]) == 4
        assert data["tasks"][0]["name"] == "Design"
        assert len(data["resources"]) == 2

    def test_summary(self, tmp_path):
        filepath = _write_temp_oplx(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["summary", filepath])
        assert result.exit_code == 0, result.output
        assert "Total tasks" in result.output

    def test_summary_json(self, tmp_path):
        filepath = _write_temp_oplx(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["summary", filepath, "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["tasks"] == 4
        assert data["resources"] == 2
        assert data["dependencies"] == 0

    def test_search(self, tmp_path):
        filepath = _write_temp_oplx(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["search", filepath, "Design"])
        assert result.exit_code == 0, result.output
        assert "Design" in result.output

    def test_search_no_match(self, tmp_path):
        filepath = _write_temp_oplx(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["search", filepath, "Nonexistent"])
        assert result.exit_code == 0
        assert "No tasks matching" in result.output

    def test_search_json(self, tmp_path):
        filepath = _write_temp_oplx(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["search", filepath, "Implementation", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["name"] == "Implementation"

    def test_tasks(self, tmp_path):
        filepath = _write_temp_oplx(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["tasks", filepath])
        assert result.exit_code == 0, result.output
        assert "Design" in result.output
        assert "Implementation" in result.output
        assert "Review" in result.output

    def test_tasks_tree(self, tmp_path):
        filepath = _write_temp_oplx(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["tasks", filepath, "--tree"])
        assert result.exit_code == 0, result.output
        assert "Design" in result.output

    def test_tasks_json(self, tmp_path):
        filepath = _write_temp_oplx(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["tasks", filepath, "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert len(data) == 4

    def test_resources(self, tmp_path):
        filepath = _write_temp_oplx(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["resources", filepath])
        assert result.exit_code == 0, result.output
        assert "Alice" in result.output
        assert "Bob" in result.output

    def test_resources_json(self, tmp_path):
        filepath = _write_temp_oplx(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["resources", filepath, "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert len(data) == 2

    def test_resources_none(self, tmp_path):
        """Empty resources list."""
        actual_xml = """<?xml version="1.0" encoding="UTF-8"?>
<scenario xmlns="http://www.omnigroup.com/namespace/OmniPlan/v2" id="test">
  <start-date>2024-01-01T00:00:00.000Z</start-date>
  <task id="t1">
    <title>Task</title>
    <effort>28800</effort>
  </task>
</scenario>"""
        filepath = _write_temp_oplx(tmp_path, _make_oplx_bytes(actual_xml))
        runner = CliRunner()
        result = runner.invoke(cli, ["resources", filepath])
        assert result.exit_code == 0
        assert "No resources found" in result.output

    def test_dependencies(self, tmp_path):
        """Test dependencies display with actual dependencies in XML."""
        actual_xml = """<?xml version="1.0" encoding="UTF-8"?>
<scenario xmlns="http://www.omnigroup.com/namespace/OmniPlan/v2" id="test">
  <start-date>2024-01-01T00:00:00.000Z</start-date>
  <task id="t1">
    <title>Task A</title>
    <effort>28800</effort>
    <prerequisite-task idref="t2"/>
  </task>
  <task id="t2">
    <title>Task B</title>
    <effort>28800</effort>
  </task>
</scenario>"""
        filepath = _write_temp_oplx(tmp_path, _make_oplx_bytes(actual_xml))
        runner = CliRunner()
        result = runner.invoke(cli, ["dependencies", filepath])
        assert result.exit_code == 0, result.output
        assert "No dependencies found" not in result.output

    def test_dependencies_none(self, tmp_path):
        """Empty dependencies list."""
        actual_xml = """<?xml version="1.0" encoding="UTF-8"?>
<scenario xmlns="http://www.omnigroup.com/namespace/OmniPlan/v2" id="test">
  <start-date>2024-01-01T00:00:00.000Z</start-date>
  <task id="t1">
    <title>Solo</title>
    <effort>28800</effort>
  </task>
</scenario>"""
        filepath = _write_temp_oplx(tmp_path, _make_oplx_bytes(actual_xml))
        runner = CliRunner()
        result = runner.invoke(cli, ["dependencies", filepath])
        assert result.exit_code == 0
        assert "No dependencies found" in result.output

    def test_dependencies_json(self, tmp_path):
        filepath = _write_temp_oplx(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["dependencies", filepath, "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert len(data) == 0


class TestDurationParsing:
    """Test the _parse_duration_seconds helper."""

    def test_plain_seconds(self):
        assert _parse_duration_seconds("3600") == 3600

    def test_days(self):
        assert _parse_duration_seconds("3d") == 86400

    def test_hours(self):
        assert _parse_duration_seconds("4h") == 14400

    def test_minutes(self):
        assert _parse_duration_seconds("30m") == 1800

    def test_human_days(self):
        assert _parse_duration_seconds("2 days") == 57600

    def test_human_hours(self):
        assert _parse_duration_seconds("1 hour") == 3600

    def test_human_minutes(self):
        assert _parse_duration_seconds("15 minutes") == 900

    def test_float_days(self):
        assert _parse_duration_seconds("0.5d") == 14400


class TestCliWriteCommands:
    """Test write commands that call parser functions (mocked)."""

    @patch("omniplan_mcp.parser.lookup_task")
    def test_lookup(self, mock_lookup):
        mock_lookup.return_value = "Task ID: 42"
        runner = CliRunner()
        result = runner.invoke(cli, ["lookup", "Design"])
        assert result.exit_code == 0
        assert "Task ID: 42" in result.output

    @patch("omniplan_mcp.parser.set_task_completed")
    def test_set_done(self, mock_set_done):
        mock_set_done.return_value = "Task 258 marked as 100% complete."
        runner = CliRunner()
        result = runner.invoke(cli, ["set-done", "258"])
        assert result.exit_code == 0
        assert "100% complete" in result.output
        mock_set_done.assert_called_once_with("258", include_subtree=False)

    @patch("omniplan_mcp.parser.set_task_completed")
    def test_set_done_subtree(self, mock_set_done):
        mock_set_done.return_value = "Done."
        runner = CliRunner()
        result = runner.invoke(cli, ["set-done", "258", "--subtree"])
        assert result.exit_code == 0
        mock_set_done.assert_called_once_with("258", include_subtree=True)

    @patch("omniplan_mcp.parser.set_task_completed_by_name")
    def test_set_done_by_name(self, mock_set_done):
        mock_set_done.return_value = "Done."
        runner = CliRunner()
        result = runner.invoke(cli, ["set-done-by-name", "Design"])
        assert result.exit_code == 0

    @patch("omniplan_mcp.parser.add_dependency")
    def test_add_dep(self, mock_add_dep):
        mock_add_dep.return_value = "Dependency added."
        runner = CliRunner()
        result = runner.invoke(cli, ["add-dep", "260", "258"])
        assert result.exit_code == 0
        mock_add_dep.assert_called_once_with("260", "258")

    @patch("omniplan_mcp.parser.remove_dependency")
    def test_rm_dep(self, mock_rm_dep):
        mock_rm_dep.return_value = "Dependency removed."
        runner = CliRunner()
        result = runner.invoke(cli, ["rm-dep", "260", "258"])
        assert result.exit_code == 0

    @patch("omniplan_mcp.parser.set_task_duration")
    def test_set_duration(self, mock_set_dur):
        mock_set_dur.return_value = "Duration set."
        runner = CliRunner()
        result = runner.invoke(cli, ["set-duration", "258", "3d"])
        assert result.exit_code == 0
        mock_set_dur.assert_called_once_with("258", 86400)

    @patch("omniplan_mcp.parser.clear_constraint_date")
    def test_clear_constraint(self, mock_clear):
        mock_clear.return_value = "Constraint cleared."
        runner = CliRunner()
        result = runner.invoke(cli, ["clear-constraint", "258"])
        assert result.exit_code == 0

    @patch("omniplan_mcp.parser.rename_task")
    def test_rename(self, mock_rename):
        mock_rename.return_value = "Task renamed."
        runner = CliRunner()
        result = runner.invoke(cli, ["rename", "258", "New Name"])
        assert result.exit_code == 0

    @patch("omniplan_mcp.parser.delete_task")
    def test_delete(self, mock_delete):
        mock_delete.return_value = "Task deleted."
        runner = CliRunner()
        result = runner.invoke(cli, ["delete", "258"])
        assert result.exit_code == 0

    @patch("omniplan_mcp.parser.add_task")
    def test_add_task(self, mock_add):
        mock_add.return_value = "Task added."
        runner = CliRunner()
        result = runner.invoke(cli, ["add-task", "258", "Subtask", "2d"])
        assert result.exit_code == 0
        mock_add.assert_called_once_with("258", "Subtask", 57600)

    @patch("omniplan_mcp.parser.add_resource")
    def test_add_resource(self, mock_add):
        mock_add.return_value = "Resource added."
        runner = CliRunner()
        result = runner.invoke(cli, ["add-resource", "Charlie"])
        assert result.exit_code == 0

    @patch("omniplan_mcp.parser.set_task_estimate")
    def test_set_estimate(self, mock_est, tmp_path):
        mock_est.return_value = "Estimate set."
        filepath = _write_temp_oplx(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["set-estimate", filepath, "t258", "1d", "3d"])
        assert result.exit_code == 0, result.output
        mock_est.assert_called_once_with(filepath, "t258", 28800, 86400)

    @patch("omniplan_mcp.parser.save_document")
    def test_save(self, mock_save):
        mock_save.return_value = "Document saved."
        runner = CliRunner()
        result = runner.invoke(cli, ["save"])
        assert result.exit_code == 0

    @patch("omniplan_mcp.parser.evaluate_javascript")
    def test_eval_script_js(self, mock_eval):
        mock_eval.return_value = "document.name"
        runner = CliRunner()
        result = runner.invoke(cli, ["eval-script", "--js", "document.name"])
        assert result.exit_code == 0
        assert "document.name" in result.output

    @patch("omniplan_mcp.parser.set_task_note")
    def test_set_note_task(self, mock_note):
        mock_note.return_value = "Set note for: Task A"
        runner = CliRunner()
        result = runner.invoke(cli, ["set-note", "258", "My task note"])
        assert result.exit_code == 0
        assert "Set note for" in result.output

    @patch("omniplan_mcp.parser.set_resource_note")
    def test_set_note_resource(self, mock_note):
        mock_note.return_value = "Set note for resource: Alice"
        runner = CliRunner()
        result = runner.invoke(cli, ["set-note", "--resource", "r1", "My resource note"])
        assert result.exit_code == 0
        assert "resource" in result.output.lower()


class TestCliNoteReadCommands:
    """Test get-note command that reads notes from .oplx files."""

    def test_get_note_task_with_note(self, tmp_path):
        """Read a task note from .oplx."""
        actual_xml = """<?xml version="1.0" encoding="UTF-8"?>
<scenario xmlns="http://www.omnigroup.com/namespace/OmniPlan/v2" id="test">
  <start-date>2026-01-01T00:00:00.000Z</start-date>
  <task id="t1">
    <title>Task A</title>
    <effort>28800</effort>
    <note>This is a task note</note>
  </task>
</scenario>"""
        filepath = _write_temp_oplx(tmp_path, _make_oplx_bytes(actual_xml))
        runner = CliRunner()
        result = runner.invoke(cli, ["get-note", filepath, "t1"])
        assert result.exit_code == 0, result.output
        assert "This is a task note" in result.output

    def test_get_note_task_no_note(self, tmp_path):
        """Task with no note shows appropriate message."""
        actual_xml = """<?xml version="1.0" encoding="UTF-8"?>
<scenario xmlns="http://www.omnigroup.com/namespace/OmniPlan/v2" id="test">
  <start-date>2026-01-01T00:00:00.000Z</start-date>
  <task id="t1">
    <title>Task A</title>
    <effort>28800</effort>
  </task>
</scenario>"""
        filepath = _write_temp_oplx(tmp_path, _make_oplx_bytes(actual_xml))
        runner = CliRunner()
        result = runner.invoke(cli, ["get-note", filepath, "t1"])
        assert result.exit_code == 0
        assert "has no note" in result.output

    def test_get_note_resource(self, tmp_path):
        """Read a resource note from .oplx."""
        actual_xml = """<?xml version="1.0" encoding="UTF-8"?>
<scenario xmlns="http://www.omnigroup.com/namespace/OmniPlan/v2" id="test">
  <start-date>2026-01-01T00:00:00.000Z</start-date>
  <resource id="r1">
    <name>Alice</name>
    <type>Staff</type>
    <note>Resource note text</note>
  </resource>
  <task id="t1">
    <title>Task</title>
    <effort>28800</effort>
  </task>
</scenario>"""
        filepath = _write_temp_oplx(tmp_path, _make_oplx_bytes(actual_xml))
        runner = CliRunner()
        result = runner.invoke(cli, ["get-note", filepath, "--resource", "r1"])
        assert result.exit_code == 0, result.output
        assert "Resource note text" in result.output

    def test_get_note_not_found(self, tmp_path):
        """Non-existent task ID returns error."""
        actual_xml = """<?xml version="1.0" encoding="UTF-8"?>
<scenario xmlns="http://www.omnigroup.com/namespace/OmniPlan/v2" id="test">
  <start-date>2026-01-01T00:00:00.000Z</start-date>
  <task id="t1">
    <title>Task</title>
    <effort>28800</effort>
  </task>
</scenario>"""
        filepath = _write_temp_oplx(tmp_path, _make_oplx_bytes(actual_xml))
        runner = CliRunner()
        result = runner.invoke(cli, ["get-note", filepath, "t999"])
        assert result.exit_code != 0
        assert "not found" in result.output


class TestErrorHandling:
    """Test error handling."""

    def test_nonexistent_file(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["read", "/nonexistent/file.oplx"])
        assert result.exit_code != 0

    def test_invalid_duration(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["set-duration", "258", "invalid"])
        assert result.exit_code != 0
        assert "Could not parse duration" in result.output

    def test_nonexistent_file_summary(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["summary", "/nonexistent/file.oplx"])
        assert result.exit_code != 0
