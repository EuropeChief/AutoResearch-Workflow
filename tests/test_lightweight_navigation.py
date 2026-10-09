"""轻入口的可迁移引用与覆盖合同；不运行题目、模型或旧状态机。"""
import json
import re
import unittest
from pathlib import Path
from urllib.parse import unquote


FLOW = Path(__file__).resolve().parents[1]
CAPABILITIES = (
    "autoresearch-research", "autoresearch-task-implementation",
    "autoresearch-experiment-validation", "autoresearch-agent-iteration",
    "autoresearch-delivery",
)
ENTRY = ("AGENTS.md", "README.md", "START_HERE.md", "docs/stages.md",
         "skills/autoresearch-workflow/SKILL.md")
RULE_IDS = {f"M{i:02}" for i in range(1, 14)} | {f"C{i:02}" for i in range(1, 8)}


def targets(text):
    """新阅读面的内联链接和引用式链接定义，不尝试解析整个 Markdown 语法。"""
    return (re.findall(r"\]\(([^)]+)\)", text)
            + re.findall(r"^\[[^\]]+\]:\s+(\S+)", text, re.M))


def coverage_rows(text):
    table = text.split("## QA 项目到本页的映射", 1)[1]
    rows = []
    for line in table.splitlines():
        if line.startswith("| ") and re.search(r"\b(?:QA\d{2}|[BGH]\d{2})\b", line):
            cells = line.split("|")
            rows.append((re.findall(r"\b(?:QA\d{2}|[BGH]\d{2})\b", cells[1]),
                         set(re.findall(r"\b[MC]\d{2}\b", cells[2]))))
    return rows


class LightweightNavigationTests(unittest.TestCase):
    def setUp(self):
        self.rules = (FLOW / "rules/README.md").read_text()
        self.guides = [FLOW / p for p in ENTRY]
        self.guides += [FLOW / "skills" / name / "SKILL.md" for name in CAPABILITIES]
        self.guides += [FLOW / "rules/README.md"]

    def test_all_five_capabilities_are_reachable_from_entry_and_stages(self):
        for relative in ("START_HERE.md", "docs/stages.md"):
            source = FLOW / relative
            paths = {(source.parent / unquote(t.split("#")[0])).resolve()
                     for t in targets(source.read_text()) if not t.startswith("#")}
            for name in CAPABILITIES:
                self.assertIn((FLOW / "skills" / name / "SKILL.md").resolve(), paths)

    def test_links_are_package_local_and_rule_fragments_resolve(self):
        for guide in self.guides:
            for target in targets(guide.read_text()):
                if target.startswith(("https:", "http:", "mailto:")):
                    continue
                filename, _, fragment = unquote(target.strip("<>")).partition("#")
                resolved = (guide.parent / filename).resolve() if filename else guide
                self.assertTrue(resolved.is_relative_to(FLOW), (guide, target))
                self.assertTrue(resolved.exists(), (guide, target))
                if fragment and resolved == FLOW / "rules/README.md":
                    self.assertIn(fragment.upper(), RULE_IDS, (guide, target))
                    self.assertRegex(self.rules, rf"(?m)^## {fragment.upper()}$")

    def test_current_requirements_have_sources_and_complete_qa_mapping(self):
        sections = dict(re.findall(r"(?ms)^## ([MC]\d{2})\n(.*?)(?=^## |\Z)", self.rules))
        self.assertEqual(set(sections), RULE_IDS)
        definitions = set(re.findall(r"^\[([A-Z])\]:", self.rules, re.M))
        for key, text in sections.items():
            citations = set(re.findall(r"\[([A-Z])\]", text))
            self.assertTrue(citations, key)
            self.assertTrue(citations <= definitions, key)
        expected = set(json.loads((FLOW / "rules/manifest.json").read_text())["qa_checks"])
        rows = coverage_rows(self.rules)
        ids = [check for checks, _ in rows for check in checks]
        self.assertEqual(set(ids), expected)
        self.assertEqual(len(ids), len(expected), "每个当前 QA 项只映射一次")
        for checks, refs in rows:
            self.assertTrue(refs and refs <= RULE_IDS, checks)

    def test_new_reading_path_has_no_state_commands_or_legacy_interface_routes(self):
        for guide in self.guides:
            text = guide.read_text()
            self.assertNotRegex(text, r"cli\.py[^\n]*(?:task init|stage (?:record|check|finish))")
            for target in targets(text):
                self.assertNotIn("docs/interfaces/", target)
                self.assertNotIn("AutoResearch新流程设计", target)

    def test_five_skills_are_self_named_and_have_distinct_descriptions(self):
        descriptions = []
        for name in CAPABILITIES:
            text = (FLOW / "skills" / name / "SKILL.md").read_text()
            self.assertTrue(text.startswith("---\n"))
            header = text.split("---", 2)[1]
            self.assertRegex(header, rf"(?m)^name: {name}$")
            descriptions.append(re.search(r"(?m)^description: (.+)$", header)[1])
        self.assertEqual(len(set(descriptions)), len(CAPABILITIES))


if __name__ == "__main__":
    unittest.main()
