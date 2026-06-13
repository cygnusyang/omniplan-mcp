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
