import unittest

from helpers import ROOT, item  # noqa: F401
from repocast import fmt
from repocast.weight import weighted_len


class TestTemplates(unittest.TestCase):
    def test_unknown_placeholder_rejected(self):
        with self.assertRaisesRegex(fmt.TemplateError, r"unknown placeholder \{nmae\}"):
            fmt.validate_templates({"line": "{nmae} {old}"})
        with self.assertRaisesRegex(fmt.TemplateError, "unknown template"):
            fmt.validate_templates({"headr": "x"})
        with self.assertRaisesRegex(fmt.TemplateError, "unbalanced"):
            fmt.validate_templates({"line": "{name} {old"})

    def test_render_drops_lines_with_only_empty_fields(self):
        self.assertEqual(fmt.render("A\n{url}\nCommit: {commit_url}", {"url": None, "commit_url": "https://c"}), "A\nCommit: https://c")
        self.assertEqual(fmt.render("{{literal}} {name}", {"name": "x"}), "{literal} x")

    def test_default_template_post(self):
        posts = fmt.build(item(), {"project": "Nav2"})
        self.assertEqual(posts, ["Nav2 update (Oct 8): max_speed 0.5 → 0.75 (50% higher)\n\nhttps://github.com/o/r/commit/" + "a" * 40])

    def test_custom_template_with_emoji(self):
        posts = fmt.build(item(), {"project": "Nav2", "templates": {"header": "🤖 {project}: {lead}", "line": "{name} {old}→{new}",
                                                                     "footer": "🔗 {commit_url}"}})
        self.assertEqual(posts[0].splitlines()[0], "🤖 Nav2: max_speed 0.5→0.75")
        self.assertEqual(weighted_len(posts[0]), 2 + len(" Nav2: max_speed 0.5") + 2 + len("0.75") + 1 + 2 + 1 + 23)

    def test_change_wording(self):
        ch = [{"name": "a", "old": "4", "new": "5"}, {"name": "b", "old": "200", "new": "100000"},
              {"name": "c", "old": "0.02", "new": "0.015"}, {"name": "d", "old": "false", "new": "true"},
              {"name": "e", "old": None, "new": "3", "kind": "added"}, {"name": "f", "old": "x", "new": "y"}]
        p = fmt.build(item(changes=ch), {"project": "P", "max_lines": 9, "templates": {"footer": ""}})[0]
        self.assertIn("b 200 → 100,000 (500x higher)", p)
        self.assertIn("- a 4 → 5 (25% higher)", p)
        self.assertIn("- c 0.02 → 0.015 (25% lower)", p)
        self.assertIn("- d switched ON", p)
        self.assertIn("- new: e = 3", p)
        self.assertIn("- f: x → y", p)

    def test_ordering_highlight_then_magnitude(self):
        ch = [{"name": "small", "old": "100", "new": "101"}, {"name": "big", "old": "1", "new": "9"}, {"name": "pin", "old": "1", "new": "2"}]
        self.assertEqual([c["name"] for c in fmt.order(ch)], ["big", "pin", "small"])
        self.assertEqual([c["name"] for c in fmt.order(ch, ["small"])], ["small", "big", "pin"])

    def test_safe_names(self):
        self.assertEqual(fmt.safe_name("params.rs"), "params/rs")
        self.assertEqual(fmt.safe_name("velocity_smoother.max_accel"), "velocity_smoother.max_accel")
        self.assertEqual(fmt.safe_name("a.b", "slash"), "a/b")

    def test_more_line_and_long_values(self):
        ch = [{"name": f"p{i}", "old": str(i), "new": str(i + 1)} for i in range(1, 8)]
        ch.append({"name": "plugins", "old": "[" + "x" * 300 + "]", "new": "[]"})
        p = fmt.build(item(changes=ch), {"project": "P", "max_lines": 3})
        self.assertIn("- +4 more", "\n".join(p))  # 3 shown + lead; 3 not shown + 1 too long

    def test_thread_split(self):
        ch = [{"name": f"some_long_parameter_name_number_{i}", "old": str(i), "new": str(i * 3)} for i in range(1, 9)]
        posts = fmt.build(item(changes=ch), {"project": "Proj", "max_lines": 8})
        self.assertGreater(len(posts), 1)
        for p in posts:
            self.assertLessEqual(weighted_len(p), 280)
        joined = "\n".join(posts)
        for i in range(1, 9):
            self.assertIn(f"_number_{i} ", joined)
        self.assertTrue(posts[-1].rstrip().endswith("a" * 40))
        self.assertGreater(len(posts[-1].splitlines()), 2, "footer should not be stranded alone")

    def test_too_many_posts_is_an_error(self):
        ch = [{"name": f"some_long_parameter_name_number_{i}", "old": str(i), "new": str(i * 3)} for i in range(1, 30)]
        with self.assertRaisesRegex(fmt.TemplateError, "max_posts"):
            fmt.build(item(changes=ch), {"project": "Proj", "max_lines": 30, "max_posts": 2})
