"""Regression tests for scripts/validate.py.

Builds tiny temporary marketplace trees with deliberate violations, runs the
relevant validator function, and asserts the issue is reported. Uses only the
Python standard library — no pytest, no extra deps.

Run from repo root:

    python -m unittest discover -s scripts/tests -t scripts -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

# Make `import validate` work whether we're invoked from repo root
# (`python -m unittest discover -s scripts/tests -t scripts`) or directly.
THIS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = THIS_DIR.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import validate  # noqa: E402


# --- Helpers ------------------------------------------------------------------

def make_minimal_marketplace(root: Path, plugin_name: str = "base-tools") -> Path:
    """Create the minimum on-disk structure validate.py needs to walk.

    Returns the plugin directory so callers can drop additional files into it.
    """
    (root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (root / ".claude-plugin" / "marketplace.json").write_text(json.dumps({
        "name": "coreteam-claude-base",
        "owner": {"name": "test"},
        "plugins": [{"name": plugin_name, "source": plugin_name}],
        "metadata": {"pluginRoot": "./plugins"},
    }))
    plugin_dir = root / "plugins" / plugin_name
    (plugin_dir / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (plugin_dir / ".claude-plugin" / "plugin.json").write_text(json.dumps({
        "name": plugin_name, "version": "0.1.0",
    }))
    return plugin_dir


def has_error_mentioning(issues, *substrings: str) -> bool:
    for sev, _file, _line, msg in issues:
        if sev != validate.ERROR:
            continue
        if all(s in msg for s in substrings):
            return True
    return False


# --- Tests --------------------------------------------------------------------

class FrontmatterParserTests(unittest.TestCase):
    """Bug #1: closing '---' at EOF must be accepted."""

    def test_no_trailing_newline(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "SKILL.md"
            f.write_text("---\ndescription: hello world\n---", encoding="utf-8")
            fm = validate.load_frontmatter(f)
            self.assertEqual(fm.get("description"), "hello world")

    def test_crlf_line_endings(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "SKILL.md"
            # write_text with newline='' preserves CRLF as-is
            f.write_text("---\r\ndescription: foo\r\n---\r\n", encoding="utf-8")
            fm = validate.load_frontmatter(f)
            self.assertEqual(fm.get("description"), "foo")

    def test_bom_stripped(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "SKILL.md"
            f.write_text("﻿---\ndescription: bar\n---\n", encoding="utf-8")
            fm = validate.load_frontmatter(f)
            self.assertEqual(fm.get("description"), "bar")

    def test_missing_close_raises(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "SKILL.md"
            f.write_text("---\ndescription: oops\nno close here\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                validate.load_frontmatter(f)

    def test_invalid_yaml_raises(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "SKILL.md"
            f.write_text("---\nbroken: [unbalanced\n---\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                validate.load_frontmatter(f)


class ParseToolListTests(unittest.TestCase):
    def test_space_separated(self):
        self.assertEqual(
            validate.parse_tool_list("Read Grep Glob"),
            ["Read", "Grep", "Glob"],
        )

    def test_comma_separated(self):
        self.assertEqual(
            validate.parse_tool_list("Read, Grep, Glob"),
            ["Read", "Grep", "Glob"],
        )

    def test_paren_scope_preserved(self):
        self.assertEqual(
            validate.parse_tool_list("Read Grep Bash(git *)"),
            ["Read", "Grep", "Bash(git *)"],
        )

    def test_mixed_comma_and_paren(self):
        self.assertEqual(
            validate.parse_tool_list("Read, Grep, Bash(git *), Bash(npm test*)"),
            ["Read", "Grep", "Bash(git *)", "Bash(npm test*)"],
        )

    def test_list_input(self):
        self.assertEqual(
            validate.parse_tool_list(["Read", "Grep"]),
            ["Read", "Grep"],
        )

    def test_empty_inputs(self):
        self.assertEqual(validate.parse_tool_list(None), [])
        self.assertEqual(validate.parse_tool_list(""), [])
        self.assertEqual(validate.parse_tool_list([]), [])


class ToolPolicyTests(unittest.TestCase):
    """Bug #2: a *present but malformed* policy file must produce an ERROR."""

    def _write_policy(self, root: Path, body: str) -> None:
        (root / "policy").mkdir(parents=True, exist_ok=True)
        (root / "policy" / "allowed-tools.yaml").write_text(body, encoding="utf-8")

    def test_malformed_policy_produces_error(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write_policy(root, "allowed: [unbalanced")
            issues = validate.validate_tool_policy(root)
            self.assertTrue(
                has_error_mentioning(issues, "policy/allowed-tools.yaml"),
                f"expected ERROR mentioning the policy path; got {issues!r}",
            )

    def test_missing_policy_is_warning_not_error(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            issues = validate.validate_tool_policy(root)
            errors = [i for i in issues if i[0] == validate.ERROR]
            self.assertEqual(errors, [], "missing policy should not be an error")
            self.assertTrue(any(i[0] == validate.WARN for i in issues),
                            "missing policy should produce a warning")

    def test_forbidden_bash_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plugin_dir = make_minimal_marketplace(root)
            self._write_policy(root,
                "allowed:\n  - Read\nforbidden:\n  - Bash\n  - Bash(*)\n")
            (plugin_dir / "agents").mkdir(parents=True, exist_ok=True)
            (plugin_dir / "agents" / "bad.md").write_text(
                "---\nname: bad\ndescription: x\ntools: Read, Bash\n---\n",
                encoding="utf-8",
            )
            issues = validate.validate_tool_policy(root)
            self.assertTrue(
                has_error_mentioning(issues, "forbidden tool", "Bash"),
                f"expected forbidden-Bash error; got {issues!r}",
            )

    def test_unlisted_tool_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plugin_dir = make_minimal_marketplace(root)
            self._write_policy(root, "allowed:\n  - Read\nforbidden: []\n")
            (plugin_dir / "agents").mkdir(parents=True, exist_ok=True)
            (plugin_dir / "agents" / "bad.md").write_text(
                "---\nname: bad\ndescription: x\ntools: Read, Write\n---\n",
                encoding="utf-8",
            )
            issues = validate.validate_tool_policy(root)
            self.assertTrue(
                has_error_mentioning(issues, "not in policy/allowed-tools.yaml", "Write"),
                f"expected unlisted-Write error; got {issues!r}",
            )

    def test_mcp_tools_exempt(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plugin_dir = make_minimal_marketplace(root)
            self._write_policy(root, "allowed:\n  - Read\nforbidden: []\n")
            (plugin_dir / "agents").mkdir(parents=True, exist_ok=True)
            (plugin_dir / "agents" / "ok.md").write_text(
                "---\nname: ok\ndescription: x\ntools: Read, mcp__some__tool\n---\n",
                encoding="utf-8",
            )
            issues = validate.validate_tool_policy(root)
            errors = [i for i in issues if i[0] == validate.ERROR]
            self.assertEqual(errors, [],
                             f"mcp__ tools should be exempt; got errors {errors!r}")

    def test_exception_grants_tool_for_specific_artifact(self):
        """A tool not in `allowed:` is OK if granted by an exception entry
        for that specific artifact path."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plugin_dir = make_minimal_marketplace(root)
            self._write_policy(root, (
                "allowed:\n  - Read\n"
                "forbidden: []\n"
                "exceptions:\n"
                "  - artifact: base-tools/skills/special\n"
                "    tools: [Bash(terraform plan)]\n"
                "    justification: 'plan-only; cannot apply'\n"
            ))
            (plugin_dir / "skills" / "special").mkdir(parents=True)
            (plugin_dir / "skills" / "special" / "SKILL.md").write_text(
                "---\nname: special\ndescription: " + ("x" * 60) + "\n"
                "allowed-tools: Read, Bash(terraform plan)\n---\n",
                encoding="utf-8",
            )
            issues = validate.validate_tool_policy(root)
            errors = [i for i in issues if i[0] == validate.ERROR]
            self.assertEqual(errors, [],
                             f"exception should permit Bash(terraform plan) for this skill; got {errors!r}")

    def test_exception_does_not_leak_to_other_artifacts(self):
        """An exception granted to artifact A must not silently permit the
        same tool in artifact B."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plugin_dir = make_minimal_marketplace(root)
            self._write_policy(root, (
                "allowed:\n  - Read\n"
                "forbidden: []\n"
                "exceptions:\n"
                "  - artifact: base-tools/skills/granted\n"
                "    tools: [Bash(terraform plan)]\n"
                "    justification: 'scoped'\n"
            ))
            # Different skill — should NOT inherit the exception.
            (plugin_dir / "skills" / "other").mkdir(parents=True)
            (plugin_dir / "skills" / "other" / "SKILL.md").write_text(
                "---\nname: other\ndescription: " + ("x" * 60) + "\n"
                "allowed-tools: Read, Bash(terraform plan)\n---\n",
                encoding="utf-8",
            )
            issues = validate.validate_tool_policy(root)
            self.assertTrue(
                has_error_mentioning(issues, "not in policy/allowed-tools.yaml", "terraform"),
                f"expected unlisted-tool error for non-excepted skill; got {issues!r}",
            )

    def test_forbidden_overrides_exception(self):
        """Even if an exception lists a forbidden tool, forbidden wins."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plugin_dir = make_minimal_marketplace(root)
            self._write_policy(root, (
                "allowed:\n  - Read\n"
                "forbidden:\n  - Bash\n"
                "exceptions:\n"
                "  - artifact: base-tools/skills/sneaky\n"
                "    tools: [Bash]\n"
                "    justification: 'oh no'\n"
            ))
            (plugin_dir / "skills" / "sneaky").mkdir(parents=True)
            (plugin_dir / "skills" / "sneaky" / "SKILL.md").write_text(
                "---\nname: sneaky\ndescription: " + ("x" * 60) + "\n"
                "allowed-tools: Read, Bash\n---\n",
                encoding="utf-8",
            )
            issues = validate.validate_tool_policy(root)
            self.assertTrue(
                has_error_mentioning(issues, "forbidden tool", "Bash"),
                f"forbidden should override exception; got {issues!r}",
            )

    def test_exception_missing_justification_warns(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            make_minimal_marketplace(root)
            self._write_policy(root, (
                "allowed: [Read]\nforbidden: []\n"
                "exceptions:\n"
                "  - artifact: base-tools/skills/x\n"
                "    tools: [Read]\n"
            ))
            issues = validate.validate_tool_policy(root)
            self.assertTrue(any("justification" in msg for _s, _f, _l, msg in issues),
                            f"expected justification warning; got {issues!r}")


class SchemaTests(unittest.TestCase):
    def test_missing_marketplace_required_fields(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".claude-plugin").mkdir(parents=True)
            (root / ".claude-plugin" / "marketplace.json").write_text("{}")
            issues = validate.validate_marketplace(root)
            self.assertTrue(has_error_mentioning(issues, "name"))
            self.assertTrue(has_error_mentioning(issues, "owner"))
            self.assertTrue(has_error_mentioning(issues, "plugins"))

    def test_plugin_name_must_match_dir(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plugin_dir = root / "plugins" / "my-plugin"
            (plugin_dir / ".claude-plugin").mkdir(parents=True)
            (plugin_dir / ".claude-plugin" / "plugin.json").write_text(json.dumps({
                "name": "different-name", "version": "0.1.0",
            }))
            issues = validate.validate_plugin(root, plugin_dir)
            self.assertTrue(
                has_error_mentioning(issues, "different-name", "my-plugin"),
                f"expected name-mismatch error; got {issues!r}",
            )

    def test_skill_missing_description(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            skill_dir = root / "skill-no-desc"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                "---\nname: skill-no-desc\n---\n# body\n",
                encoding="utf-8",
            )
            issues = validate.validate_skill(root, skill_dir)
            self.assertTrue(has_error_mentioning(issues, "description"))


class HookValidationTests(unittest.TestCase):
    def test_missing_referenced_script_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plugin_dir = make_minimal_marketplace(root)
            (plugin_dir / "hooks.json").write_text(json.dumps({
                "hooks": {
                    "PostToolUse": [{
                        "matcher": "Write",
                        "hooks": [{
                            "type": "command",
                            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/missing.sh",
                        }],
                    }],
                },
            }))
            issues = validate.validate_hooks(plugin_dir)
            self.assertTrue(
                has_error_mentioning(issues, "missing script", "missing.sh"),
                f"expected missing-script error; got {issues!r}",
            )

    def test_shebang_warning(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plugin_dir = make_minimal_marketplace(root)
            (plugin_dir / "hooks").mkdir()
            (plugin_dir / "hooks" / "no-shebang.sh").write_text("echo hi\n", encoding="utf-8")
            (plugin_dir / "hooks.json").write_text(json.dumps({
                "hooks": {
                    "PostToolUse": [{
                        "matcher": "Write",
                        "hooks": [{
                            "type": "command",
                            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/no-shebang.sh",
                        }],
                    }],
                },
            }))
            issues = validate.validate_hooks(plugin_dir)
            self.assertTrue(any("shebang" in msg for _s, _f, _l, msg in issues),
                            f"expected shebang warning; got {issues!r}")


class BehavioralRunnerLintTests(unittest.TestCase):
    """Cover the lint mode of behavioral_runner.py — no API needed."""

    def setUp(self) -> None:
        import importlib
        import sys as _sys
        spath = str(Path(__file__).resolve().parent.parent)
        if spath not in _sys.path:
            _sys.path.insert(0, spath)
        self.runner = importlib.import_module("behavioral_runner")

    def _make_skill(self, root: Path, plugin: str, name: str, cases_yaml: str) -> Path:
        skill_dir = root / "plugins" / plugin / "skills" / name
        (skill_dir / "tests").mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: " + ("x" * 60) + "\n---\nbody\n",
            encoding="utf-8")
        (skill_dir / "tests" / "cases.yaml").write_text(cases_yaml, encoding="utf-8")
        return skill_dir

    def test_valid_cases_lint_clean(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._make_skill(root, "p", "s", (
                "skill: p/s\n"
                "cases:\n"
                "  - name: ok\n"
                "    prompt: hello\n"
                "    expected:\n"
                "      response_must_contain: [hello]\n"
            ))
            suites, errors = self.runner.discover_suites(root, None)
            self.assertEqual(errors, [])
            self.assertEqual(len(suites), 1)
            self.assertEqual(len(suites[0].cases), 1)

    def test_missing_name_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._make_skill(root, "p", "s", (
                "cases:\n"
                "  - prompt: hi\n"
                "    expected: { response_must_contain: [hi] }\n"
            ))
            suites, errors = self.runner.discover_suites(root, None)
            self.assertEqual(suites, [])
            self.assertEqual(len(errors), 1)
            self.assertIn("missing 'name'", errors[0])

    def test_duplicate_name_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._make_skill(root, "p", "s", (
                "cases:\n"
                "  - name: same\n"
                "    prompt: a\n"
                "    expected: { response_must_contain: [a] }\n"
                "  - name: same\n"
                "    prompt: b\n"
                "    expected: { response_must_contain: [b] }\n"
            ))
            suites, errors = self.runner.discover_suites(root, None)
            self.assertEqual(suites, [])
            self.assertEqual(len(errors), 1)
            self.assertIn("duplicate case name", errors[0])

    def test_no_assertions_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._make_skill(root, "p", "s", (
                "cases:\n"
                "  - name: ok\n"
                "    prompt: hi\n"
                "    expected: {}\n"
            ))
            suites, errors = self.runner.discover_suites(root, None)
            self.assertEqual(suites, [])
            self.assertEqual(len(errors), 1)
            self.assertIn("no assertions", errors[0])

    def test_skill_field_mismatch_rejected(self):
        """The optional `skill:` field must match the discovered path."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._make_skill(root, "p", "s", (
                "skill: wrong/path\n"  # discovery yields p/s
                "cases:\n"
                "  - name: ok\n"
                "    prompt: hi\n"
                "    expected: { response_must_contain: [hi] }\n"
            ))
            suites, errors = self.runner.discover_suites(root, None)
            self.assertEqual(suites, [])
            self.assertEqual(len(errors), 1)
            self.assertIn("'skill' field", errors[0])
            self.assertIn("p/s", errors[0])

    def test_multiple_errors_collected(self):
        """All broken cases.yaml files in one walk are reported together."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # Two skills, both broken in different ways
            self._make_skill(root, "p", "skill_a", (
                "cases:\n"
                "  - prompt: hi\n"  # missing name
                "    expected: { response_must_contain: [hi] }\n"
            ))
            self._make_skill(root, "p", "skill_b", (
                "skill: wrong/skill_b\n"  # mismatched field
                "cases:\n"
                "  - name: x\n"
                "    prompt: hi\n"
                "    expected: { response_must_contain: [hi] }\n"
            ))
            suites, errors = self.runner.discover_suites(root, None)
            self.assertEqual(suites, [])
            self.assertEqual(len(errors), 2,
                             f"expected both errors collected; got {errors!r}")


class SecretScanTests(unittest.TestCase):
    """Bug #3: scanner must exclude its own source so SECRET_PATTERNS literals
    don't self-flag, but must still catch real-looking secrets elsewhere."""

    def test_real_aws_key_caught(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # Need a marketplace.json or iter_text_files starts at root anyway,
            # but validate_secrets doesn't need the marketplace. Just drop a
            # file with a fake-but-pattern-matching AWS key.
            bad = root / "config.txt"
            bad.write_text("AWS_ACCESS_KEY=AKIAABCDEFGHIJKL1234\n", encoding="utf-8")
            issues = validate.validate_secrets(root)
            self.assertTrue(
                has_error_mentioning(issues, "AWS access key"),
                f"expected AWS-key error; got {issues!r}",
            )


if __name__ == "__main__":
    unittest.main()
