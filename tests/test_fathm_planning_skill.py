"""fathm-planning is a real, loadable Agent Skill (agentskills.io spec): validate the SKILL.md
frontmatter shape, not just that the prose reads like one."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

SKILL_DIR = Path(__file__).resolve().parents[1] / "skills" / "fathm-planning"
SKILL_MD = SKILL_DIR / "SKILL.md"

_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _frontmatter_and_body() -> tuple[dict, str]:
    text = SKILL_MD.read_text(encoding="utf-8")
    assert text.startswith("---\n"), "SKILL.md must open with a YAML frontmatter block"
    _, rest = text.split("---\n", 1)
    raw_frontmatter, body = rest.split("---\n", 1)
    return yaml.safe_load(raw_frontmatter), body


def test_skill_folder_and_file_exist():
    assert SKILL_DIR.is_dir()
    assert SKILL_MD.is_file()


def test_frontmatter_has_required_agentskills_fields():
    frontmatter, _ = _frontmatter_and_body()
    assert isinstance(frontmatter, dict)
    assert "name" in frontmatter and frontmatter["name"]
    assert "description" in frontmatter and frontmatter["description"]


def test_name_matches_folder_and_is_kebab_case():
    frontmatter, _ = _frontmatter_and_body()
    assert frontmatter["name"] == SKILL_DIR.name == "fathm-planning"
    assert _NAME_RE.match(frontmatter["name"]), "skill name must be lowercase kebab-case"


def test_description_is_a_single_string_within_spec_length():
    frontmatter, _ = _frontmatter_and_body()
    description = frontmatter["description"]
    assert isinstance(description, str)
    assert 0 < len(description) <= 1024
    # a usable description states *when* to load the skill, not just what it is
    assert "package" in description.lower()


def test_body_documents_the_mcp_server_and_override_workflow():
    _, body = _frontmatter_and_body()
    assert "fathm-ap" in body  # points at the MCP server
    assert "override_record" in body  # the P4 capture tool
    assert "draft_reason_text" in body
    assert "never write" in body.lower() and "overrides.jsonl" in body  # the explicit ban on hand-written rows
    for must_keyword in ("package_check", "output_contract", "chat memory"):
        assert must_keyword in body  # C8 six-MUSTs carried as operating instructions
