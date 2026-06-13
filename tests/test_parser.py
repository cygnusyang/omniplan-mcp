"""Tests for omniplan_mcp.parser module."""

import os
import xml.etree.ElementTree as ET
import tempfile
import zipfile
from pathlib import Path

# Test XML snippet matching the OmniPlan v2 namespace format
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
  <task id="t-1">
    <type>group</type>
    <child-task idref="t1"/>
  </task>
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
    """Test parsing an .oplx file."""
    from omniplan_mcp.parser import parse_file, build_task_map, get_text

    filepath = _create_test_oplx()
    try:
        root, cleanup = parse_file(filepath)
        assert root is not None

        task_map = build_task_map(root)
        assert len(task_map) >= 4  # t-1, t1, t2, t3

        # Check titles
        phase1 = task_map['t1']
        assert get_text(phase1, 'title') == 'Phase 1'

        task_a = task_map['t2']
        assert get_text(task_a, 'title') == 'Task A'
        assert get_text(task_a, 'percent-complete') == '100'

        milestone = task_map['t3']
        assert get_text(milestone, 'title') == 'Milestone X'
        assert get_text(milestone, 'type') == 'milestone'

    finally:
        os.unlink(filepath)


def test_get_resources():
    """Test extracting resources."""
    from omniplan_mcp.parser import get_resources

    root = ET.fromstring(TEST_XML)
    resources = get_resources(root)
    assert len(resources) == 2
    assert resources[0]['name'] == 'Alice'
    assert resources[1]['name'] == 'Bob'


def test_convert_date():
    """Test date conversion."""
    from omniplan_mcp.parser import convert_date

    assert convert_date('2025-11-28T00:00:00.000Z') == '2025-11-28'
    assert convert_date('') == ''
    assert convert_date('invalid') == 'invalid'


def test_collect_all_tasks():
    """Test recursive task collection."""
    from omniplan_mcp.parser import (
        build_task_map,
        collect_all_tasks,
    )

    root = ET.fromstring(TEST_XML)
    task_map = build_task_map(root)

    all_tasks = collect_all_tasks('t-1', task_map)
    # t-1 + t1 + t2 + t3 = 4
    assert len(all_tasks) == 4

    # Check hierarchy levels
    levels = [t['level'] for t in all_tasks]
    assert levels == [0, 1, 2, 2]  # t-1:0, t1:1, t2:2, t3:2
