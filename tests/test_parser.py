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
