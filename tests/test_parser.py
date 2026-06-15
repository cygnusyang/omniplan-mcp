"""Tests for omniplan_mcp.parser module — .oplx XML parsing path."""

import os
import tempfile
import zipfile

TEST_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<scenario xmlns="http://www.omnigroup.com/namespace/OmniPlan/v2" id="test">
  <start-date>2025-11-28T00:00:00.000Z</start-date>
  <resource id="r1">
    <name>Alice</name>
    <type>Staff</type>
  </resource>
  <resource id="r2">
    <name>Bob</name>
    <type>Staff</type>
  </resource>
  <task id="t1">
    <title>Phase 1</title>
    <type>group</type>
    <start-date>2025-11-28T00:00:00.000Z</start-date>
    <child-task idref="t2"/>
    <child-task idref="t3"/>
  </task>
  <task id="t2">
    <title>Task A</title>
    <start-date>2025-11-28T00:00:00.000Z</start-date>
    <end-date>2025-12-05T00:00:00.000Z</end-date>
    <percent-complete>100</percent-complete>
    <effort>28800</effort>
  </task>
  <task id="t3">
    <title>Milestone X</title>
    <type>milestone</type>
    <start-date>2025-12-05T00:00:00.000Z</start-date>
    <end-date>2025-12-05T00:00:00.000Z</end-date>
  </task>
</scenario>
'''


def _create_test_oplx() -> str:
    """Create a temporary .oplx file for testing."""
    tmp = tempfile.NamedTemporaryFile(suffix='.oplx', delete=False)
    with zipfile.ZipFile(tmp, 'w') as z:
        z.writestr('Actual.xml', TEST_XML)
    return tmp.name


def test_parse_oplx():
    """Test parsing an .oplx file via read_oplx."""
    from omniplan_mcp.parser import read_oplx

    filepath = _create_test_oplx()
    try:
        projects, resources, tasks, violations, assignments, dependencies = read_oplx(filepath)

        # Project info
        assert len(projects) == 1
        assert projects[0]["start_date"] == "2025-11-28"

        # Resources
        assert len(resources) == 2
        assert resources[0]["name"] == "Alice"
        assert resources[1]["name"] == "Bob"

        # Tasks
        assert len(tasks) == 3

        task_map = {t["id"]: t for t in tasks}
        assert task_map["t1"]["name"] == "Phase 1"
        assert task_map["t1"]["task_type"] == "group"

        assert task_map["t2"]["name"] == "Task A"
        assert task_map["t2"]["percent_complete"] == 100.0
        assert task_map["t2"]["task_type"] == "task"

        assert task_map["t3"]["name"] == "Milestone X"
        assert task_map["t3"]["task_type"] == "milestone"

    finally:
        os.unlink(filepath)


def test_get_resources_staff():
    """Test filtering staff resources."""
    from omniplan_mcp.parser import get_resources_staff

    resources = [
        {"type": "resource", "name": "Alice", "resource_type": "person"},
        {"type": "resource", "name": "Bob", "resource_type": "person"},
        {"type": "resource", "name": "3D Printer", "resource_type": "equipment"},
    ]
    staff = get_resources_staff(resources)
    assert len(staff) == 2
    assert staff[0]["name"] == "Alice"
    assert staff[1]["name"] == "Bob"


def test_build_task_tree():
    """Test building hierarchical task tree."""
    from omniplan_mcp.parser import build_task_tree

    tasks = [
        {"id": "t1", "name": "Phase 1", "task_type": "group", "parent_id": -1},
        {"id": "t2", "name": "Task A", "task_type": "task", "parent_id": "t1"},
        {"id": "t3", "name": "Milestone X", "task_type": "milestone", "parent_id": "t1"},
    ]

    tree = build_task_tree(tasks)
    assert len(tree) == 1
    assert tree[0]["name"] == "Phase 1"
    assert len(tree[0]["children"]) == 2
    assert tree[0]["children"][0]["name"] == "Task A"
    assert tree[0]["children"][1]["name"] == "Milestone X"


def test_build_task_tree_string_parent():
    """Test build_task_tree with string parent IDs (.oplx style)."""
    from omniplan_mcp.parser import build_task_tree

    tasks = [
        {"id": "t1", "name": "Group", "task_type": "group", "parent_id": ""},
        {"id": "t2", "name": "Child", "task_type": "task", "parent_id": "t1"},
        {"id": "t3", "name": "Orphan", "task_type": "task", "parent_id": "nonexistent"},
        {"id": "t-1", "name": "Root", "task_type": "group", "parent_id": ""},
    ]
    tree = build_task_tree(tasks)
    assert len(tree) == 3  # t1, t3 (parent not found), t-1 are roots
    root_names = {t["name"] for t in tree}
    assert root_names == {"Group", "Orphan", "Root"}


def test_percent_compute_from_effort():
    """Test .oplx style percent-complete from effort-done/effort."""
    from omniplan_mcp.parser import parse_file
    import tempfile, zipfile

    xml = '''<?xml version="1.0" encoding="UTF-8"?>
<scenario xmlns="http://www.omnigroup.com/namespace/OmniPlan/v2" id="test">
  <start-date>2025-01-01T00:00:00.000Z</start-date>
  <task id="t1">
    <title>Task with effort</title>
    <effort>288000</effort>
    <effort-done>144000</effort-done>
  </task>
  <task id="t2">
    <title>Group</title>
    <type>group</type>
    <child-task idref="t3"/>
    <child-task idref="t4"/>
  </task>
  <task id="t3">
    <title>Sub A</title>
    <effort>144000</effort>
    <effort-done>144000</effort-done>
  </task>
  <task id="t4">
    <title>Sub B</title>
    <effort>144000</effort>
    <effort-done>72000</effort-done>
  </task>
</scenario>'''
    tmp = tempfile.NamedTemporaryFile(suffix='.oplx', delete=False)
    with zipfile.ZipFile(tmp, 'w') as z:
        z.writestr('Actual.xml', xml)
    try:
        proj, res, tasks, violations, assignments, deps = parse_file(tmp.name)
        task_map = {t["id"]: t for t in tasks}
        assert task_map["t1"]["percent_complete"] == 50.0  # 144000/288000
        assert task_map["t3"]["percent_complete"] == 100.0  # 144000/144000
        assert task_map["t4"]["percent_complete"] == 50.0  # 72000/144000
        # Group should be average of children: (100+50)/2 = 75
        assert task_map["t2"]["percent_complete"] == 75.0
    finally:
        os.unlink(tmp.name)


def test_outline_depth():
    """Test outline_depth computation from parent-child relationships."""
    from omniplan_mcp.parser import parse_file
    import tempfile, zipfile

    xml = '''<?xml version="1.0" encoding="UTF-8"?>
<scenario xmlns="http://www.omnigroup.com/namespace/OmniPlan/v2" id="test">
  <start-date>2025-01-01T00:00:00.000Z</start-date>
  <task id="t1">
    <title>Level 0</title>
    <type>group</type>
    <child-task idref="t2"/>
  </task>
  <task id="t2">
    <title>Level 1</title>
    <type>group</type>
    <child-task idref="t3"/>
  </task>
  <task id="t3">
    <title>Level 2</title>
    <effort>28800</effort>
  </task>
</scenario>'''
    tmp = tempfile.NamedTemporaryFile(suffix='.oplx', delete=False)
    with zipfile.ZipFile(tmp, 'w') as z:
        z.writestr('Actual.xml', xml)
    try:
        proj, res, tasks, violations, assignments, deps = parse_file(tmp.name)
        task_map = {t["id"]: t for t in tasks}
        assert task_map["t1"]["outline_depth"] == 0
        assert task_map["t2"]["outline_depth"] == 1
        assert task_map["t3"]["outline_depth"] == 2
    finally:
        os.unlink(tmp.name)


def test_task_status():
    """Test task_status computation for .oplx tasks."""
    from omniplan_mcp.parser import parse_file
    import tempfile, zipfile

    xml = '''<?xml version="1.0" encoding="UTF-8"?>
<scenario xmlns="http://www.omnigroup.com/namespace/OmniPlan/v2" id="test">
  <start-date>2025-01-01T00:00:00.000Z</start-date>
  <task id="t1">
    <title>Finished</title>
    <effort>28800</effort>
    <effort-done>28800</effort-done>
  </task>
  <task id="t2">
    <title>Not started</title>
    <effort>28800</effort>
  </task>
</scenario>'''
    tmp = tempfile.NamedTemporaryFile(suffix='.oplx', delete=False)
    with zipfile.ZipFile(tmp, 'w') as z:
        z.writestr('Actual.xml', xml)
    try:
        proj, res, tasks, violations, assignments, deps = parse_file(tmp.name)
        task_map = {t["id"]: t for t in tasks}
        assert task_map["t1"]["task_status"] == "finished"
        assert task_map["t2"]["task_status"] == "ok"
    finally:
        os.unlink(tmp.name)


def test_actual_xml_preferred():
    """Test that Actual.xml is preferred over backup XML files."""
    from omniplan_mcp.parser import parse_file
    import tempfile, zipfile

    # Create a .oplx with both Actual.xml (correct) and a backup (stale)
    xml_actual = '''<?xml version="1.0" encoding="UTF-8"?>
<scenario xmlns="http://www.omnigroup.com/namespace/OmniPlan/v2" id="test">
  <start-date>2025-01-01T00:00:00.000Z</start-date>
  <task id="t1"><title>Actual</title><effort>28800</effort></task>
</scenario>'''
    xml_stale = '''<?xml version="1.0" encoding="UTF-8"?>
<scenario xmlns="http://www.omnigroup.com/namespace/OmniPlan/v2" id="test">
  <start-date>2025-01-01T00:00:00.000Z</start-date>
  <task id="t1"><title>Stale</title><effort>28800</effort></task>
</scenario>'''
    tmp = tempfile.NamedTemporaryFile(suffix='.oplx', delete=False)
    with zipfile.ZipFile(tmp, 'w') as z:
        z.writestr('Actual.xml', xml_actual)
        z.writestr('AAAAA.xml', xml_stale)  # Sorts before Actual.xml alphabetically
    try:
        proj, res, tasks, violations, assignments, deps = parse_file(tmp.name)
        assert tasks[0]["name"] == "Actual", f"Expected Actual, got {tasks[0]['name']}"
    finally:
        os.unlink(tmp.name)


def test_parse_oplx_assignments_dependencies_and_leveled_dates():
    """Parse scheduling data stored directly under .oplx task elements."""
    from omniplan_mcp.parser import parse_file

    xml = '''<?xml version="1.0" encoding="UTF-8"?>
<scenario xmlns="http://www.omnigroup.com/namespace/OmniPlan/v2" id="test">
  <start-date>2026-06-14T00:00:00.000Z</start-date>
  <resource id="r1"><name>Alice</name><type>Staff</type></resource>
  <task id="t1">
    <title>Prerequisite</title>
    <leveled-start>2026-06-15T00:00:00.000Z</leveled-start>
    <leveled-end>2026-06-16T00:00:00.000Z</leveled-end>
    <effort>28800</effort>
    <assignment idref="r1"/>
  </task>
  <task id="t2">
    <title>Dependent</title>
    <effort>28800</effort>
    <prerequisite-task idref="t1"/>
  </task>
</scenario>'''
    tmp = tempfile.NamedTemporaryFile(suffix=".oplx", delete=False)
    with zipfile.ZipFile(tmp, "w") as z:
        z.writestr("Actual.xml", xml)
    try:
        _, _, tasks, _, assignments, dependencies = parse_file(tmp.name)
        task_map = {t["id"]: t for t in tasks}
        assert task_map["t1"]["start_date"] == "2026-06-15"
        assert task_map["t1"]["end_date"] == "2026-06-16"
        assert assignments == [{
            "type": "assignment",
            "task_id": "t1",
            "resource_id": "r1",
        }]
        assert dependencies == [{
            "type": "dependency",
            "task_id": "t2",
            "prerequisite_task_id": "t1",
        }]
    finally:
        os.unlink(tmp.name)


def test_set_task_progress_validation_and_script(monkeypatch):
    """Allow arbitrary valid progress and reject values outside 0..100."""
    from omniplan_mcp import parser

    captured = {}

    def fake_run(script):
        captured["script"] = script
        return "ok"

    monkeypatch.setattr(parser, "_run_as", fake_run)
    assert parser.set_task_progress("t258", 42.5) == "ok"
    assert "if id of t = 258" in captured["script"]
    assert "set completed of t to 0.425" in captured["script"]

    for invalid in (-1, 101, True, "50"):
        try:
            parser.set_task_progress("t258", invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Expected ValueError for {invalid!r}")


def test_task_id_validation_blocks_applescript_injection():
    """Only numeric task IDs, optionally prefixed with t, are accepted."""
    from omniplan_mcp.parser import _normalize_task_id

    assert _normalize_task_id("t258") == "258"
    assert _normalize_task_id("258") == "258"
    for invalid in ("", "task258", "258 then delete document 1", "t-1"):
        try:
            _normalize_task_id(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Expected ValueError for {invalid!r}")


def test_applescript_string_escaping():
    """Backslashes must be escaped before quotes."""
    from omniplan_mcp.parser import _escape_applescript_string

    assert _escape_applescript_string('a\\b"c') == 'a\\\\b\\"c'


def test_parse_applescript_task_record_field_positions():
    """Parse optional task fields without shifting note and count columns."""
    from omniplan_mcp.parser import _parse_as_record

    line = (
        "task|12|Task A|standard task|2026年6月1日|2026年6月2日|28800|0.5|"
        "57600|28800|28800|2|1.2|10|500|ok|1|2|3|note text|4|5|6|7|"
        "2026年6月1日|2026年6月2日"
    )
    task = _parse_as_record(line)
    assert task["percent_complete"] == 50.0
    assert task["remaining_effort_hours"] == "8.0"
    assert task["completed_effort_hours"] == "8.0"
    assert task["note"] == "note text"
    assert task["child_task_count"] == 4
    assert task["assignment_count"] == 5
    assert task["prerequisite_count"] == 6
    assert task["dependent_count"] == 7


def test_live_read_script_refreshes_task_id_for_relations():
    """Assignment and dependency records must use their own task's ID."""
    from omniplan_mcp.parser import _READ_OPEN_DOC

    assignments = _READ_OPEN_DOC.split("-- Assignments", 1)[1].split("-- Dependencies", 1)[0]
    dependencies = _READ_OPEN_DOC.split("-- Dependencies", 1)[1]
    assert "set tid to id of t" in assignments
    assert "set tid to id of t" in dependencies


def test_parse_applescript_relation_records():
    """Parse live AppleScript relation and violation records."""
    from omniplan_mcp.parser import _parse_as_record

    assert _parse_as_record("assignment|12|3") == {
        "type": "assignment",
        "task_id": 12,
        "resource_id": 3,
    }
    assert _parse_as_record("dependency|12|8") == {
        "type": "dependency",
        "task_id": 12,
        "prerequisite_task_id": 8,
    }
    assert _parse_as_record("violation|warning|Late task|<p>Late</p>|12") == {
        "type": "violation",
        "violation_type": "warning",
        "description": "Late task",
        "html": "<p>Late</p>",
        "task_id": 12,
    }


def test_parse_applescript_resource_type():
    """Normalize AppleScript resource types to the XML parser vocabulary."""
    from omniplan_mcp.parser import _parse_as_record

    resource = _parse_as_record(
        "resource|3|Alice|staff resource|0|1|1|0|0|0|0|0|||"
    )
    assert resource["resource_type"] == "person"


def test_set_task_estimate_rejects_open_document(monkeypatch, tmp_path):
    """Direct ZIP edits must not race with an open OmniPlan document."""
    from omniplan_mcp import parser

    filepath = tmp_path / "project.oplx"
    filepath.write_bytes(b"not opened because the guard runs first")
    monkeypatch.setattr(
        parser,
        "_open_document_paths",
        lambda: {str(filepath.resolve())},
    )
    try:
        parser.set_task_estimate(str(filepath), "t1", 1, 2)
    except RuntimeError as exc:
        assert "while the document is open" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError for an open document")


def test_document_prelude_requires_explicit_selection_for_multiple_docs():
    """Default selection refuses ambiguity; filepath selection matches by path."""
    from omniplan_mcp.parser import _document_prelude

    default = _document_prelude()
    assert "if docCount > 1 then return" in default
    assert "specify filepath or document_id" in default

    selected = _document_prelude(filepath="/tmp/project.oplx")
    assert f'is "{os.path.realpath("/tmp/project.oplx")}"' in selected
    assert "set doc to candidate" in selected

    try:
        _document_prelude("/tmp/project.oplx", "document-id")
    except ValueError:
        pass
    else:
        raise AssertionError("Expected ValueError for two selectors")


def test_parse_oplx_resolves_historical_dependency_ids():
    """Use the changelog to map retired dependency IDs to current task IDs."""
    from omniplan_mcp.parser import parse_file

    xml = '''<?xml version="1.0" encoding="UTF-8"?>
<scenario xmlns="http://www.omnigroup.com/namespace/OmniPlan/v2" id="test">
  <task id="t10"><title>Dependent</title><prerequisite-task idref="t2"/></task>
  <task id="t20"><title>Renumbered task</title></task>
</scenario>'''
    changelog = '''<?xml version="1.0" encoding="UTF-8"?>
<changes xmlns="http://www.omnigroup.com/namespace/OmniPlan/v2">
  <change idref="t2">
    <change idref="t2" attribute="title" type="string" to="Renumbered task"/>
  </change>
</changes>'''
    tmp = tempfile.NamedTemporaryFile(suffix=".oplx", delete=False)
    with zipfile.ZipFile(tmp, "w") as z:
        z.writestr("Actual.xml", xml)
        z.writestr("__changelog.xml", changelog)
    try:
        _, _, _, _, _, dependencies = parse_file(tmp.name)
        assert dependencies == [{
            "type": "dependency",
            "task_id": "t10",
            "prerequisite_task_id": "t20",
        }]
    finally:
        os.unlink(tmp.name)


def test_xml_parsing_extracts_notes():
    """Test that .oplx XML parsing extracts <note> from tasks and resources."""
    from omniplan_mcp.parser import parse_file
    import tempfile, zipfile

    xml = '''<?xml version="1.0" encoding="UTF-8"?>
<scenario xmlns="http://www.omnigroup.com/namespace/OmniPlan/v2" id="test">
  <start-date>2026-01-01T00:00:00.000Z</start-date>
  <resource id="r1">
    <name>Alice</name>
    <type>Staff</type>
    <note>Resource note text</note>
  </resource>
  <task id="t1">
    <title>Task with note</title>
    <effort>28800</effort>
    <note>Task note content</note>
  </task>
  <task id="t2">
    <title>Task without note</title>
    <effort>28800</effort>
  </task>
</scenario>'''
    tmp = tempfile.NamedTemporaryFile(suffix=".oplx", delete=False)
    with zipfile.ZipFile(tmp, "w") as z:
        z.writestr("Actual.xml", xml)
    try:
        _, resources, tasks, _, _, _ = parse_file(tmp.name)
        assert resources[0]["note"] == "Resource note text"
        task_map = {t["id"]: t for t in tasks}
        assert task_map["t1"]["note"] == "Task note content"
        assert task_map["t2"]["note"] == ""
    finally:
        os.unlink(tmp.name)


def test_set_task_note_script(monkeypatch):
    """Verify set_task_note generates correct AppleScript."""
    from omniplan_mcp import parser

    captured = {}

    def fake_run(script):
        captured["script"] = script
        return "ok"

    monkeypatch.setattr(parser, "_run_as", fake_run)
    assert parser.set_task_note("258", "Hello note") == "ok"
    assert 'if id of t = 258' in captured["script"]
    assert 'set note of t to "Hello note"' in captured["script"]


def test_set_resource_note_script(monkeypatch):
    """Verify set_resource_note generates correct AppleScript."""
    from omniplan_mcp import parser

    captured = {}

    def fake_run(script):
        captured["script"] = script
        return "ok"

    monkeypatch.setattr(parser, "_run_as", fake_run)
    assert parser.set_resource_note("r3", "Resource note") == "ok"
    assert 'if id of r = 3' in captured["script"]
    assert 'set note of r to "Resource note"' in captured["script"]


def test_set_task_note_escapes_applescript(monkeypatch):
    """Note text with quotes/backslashes is properly escaped."""
    from omniplan_mcp import parser

    captured = {}

    def fake_run(script):
        captured["script"] = script
        return "ok"

    monkeypatch.setattr(parser, "_run_as", fake_run)
    parser.set_task_note("258", 'Note with "quotes" and \\backslash')
    assert 'Note with \\"quotes\\" and \\\\backslash' in captured["script"]
