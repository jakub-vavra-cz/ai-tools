from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_tools.beetlejuice import (
    apply_dump_overrides,
    dump_filename_for_id,
    find_local_testcase_xmls,
    map_sst_team,
    maybe_decompress,
    parse_directory_index_for_testcase_xmls,
    parse_testcase_xml,
    pairs_to_jira_dump,
    process_cases,
    read_xml_bytes,
)
from ai_tools.dump_polarion_testcase import parse_key_value_file

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "beetlejuice"


class MapTeamTests(unittest.TestCase):
    def test_sst_to_rhel(self) -> None:
        self.assertEqual(map_sst_team("sst_idm_sssd"), "rhel-idm-sssd")
        self.assertEqual(map_sst_team("sst_idm"), "rhel-idm")
        self.assertEqual(map_sst_team("rhel-idm-sssd"), "rhel-idm-sssd")
        self.assertEqual(map_sst_team("other"), "other")


class GzipTests(unittest.TestCase):
    def test_maybe_decompress_plain(self) -> None:
        self.assertEqual(maybe_decompress(b"<x/>"), b"<x/>")

    def test_read_gzipped_fixture(self) -> None:
        data = read_xml_bytes(FIXTURES / "bash-sample.xml.gz")
        self.assertTrue(data.lstrip().startswith(b"<testcases"))


class ParseAdSampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = parse_testcase_xml(
            (FIXTURES / "ad-sample.xml").read_bytes(),
            source="ad-sample.xml",
        )

    def test_document_meta(self) -> None:
        self.assertEqual(self.doc.project_id, "RHEL_IDM")
        self.assertEqual(self.doc.lookup_method, "custom")
        self.assertEqual(self.doc.lookup_field_id, "testCaseID")
        self.assertEqual(len(self.doc.cases), 2)

    def test_uuid_id_and_team_mapping(self) -> None:
        case = self.doc.cases[0]
        self.assertEqual(case["testCaseID"], "31b37c8e-2ea4-45d3-90a6-b0be9deb1599")
        self.assertEqual(case["title"], "Set simple_allow_user to user1")
        self.assertEqual(case["status"], "approved")
        self.assertEqual(case["casecomponent"], "sssd")
        self.assertEqual(case["subsystemteam"], "rhel-idm-sssd")
        self.assertIn("teststep.1.step", case)
        self.assertIn("<p>", case["teststep.1.step"])

    def test_customerscenario_case(self) -> None:
        case = self.doc.cases[1]
        self.assertEqual(case.get("customerscenario", "").lower(), "yes")

    def test_jira_dump_mapping(self) -> None:
        dump = pairs_to_jira_dump(self.doc.cases[0])
        self.assertEqual(dump["summary"], "Set simple_allow_user to user1")
        self.assertEqual(dump["ID"], "31b37c8e-2ea4-45d3-90a6-b0be9deb1599")
        self.assertEqual(dump["components"], "sssd")
        self.assertEqual(dump["AssignedTeam"], "rhel-idm-sssd")
        self.assertEqual(dump["status"], "Active")
        self.assertIn("upstream", dump.get("labels", ""))
        self.assertTrue(dump["URL"].startswith("https://github.com/SSSD/sssd/"))
        self.assertIn("Test steps", dump["description"])

    def test_no_map_sst_team(self) -> None:
        doc = parse_testcase_xml(
            (FIXTURES / "ad-sample.xml").read_bytes(),
            map_team=False,
        )
        self.assertEqual(doc.cases[0]["subsystemteam"], "sst_idm_sssd")


class ParseBashSampleTests(unittest.TestCase):
    def test_name_lookup(self) -> None:
        doc = parse_testcase_xml((FIXTURES / "bash-sample.xml").read_bytes())
        self.assertEqual(doc.lookup_method, "name")
        self.assertEqual(len(doc.cases), 2)
        case = doc.cases[0]
        self.assertEqual(
            case["testCaseID"],
            "IDM-SSSD-TC: sanity: initscript: chkconfig Operations",
        )
        self.assertEqual(case["subsystemteam"], "rhel-idm-sssd")
        dump = pairs_to_jira_dump(case)
        self.assertEqual(dump["ID"], case["testCaseID"])
        self.assertEqual(dump["summary"], case["title"])
        self.assertNotIn("status", dump)


class ParseMhSampleTests(unittest.TestCase):
    def test_pytest_style_id(self) -> None:
        doc = parse_testcase_xml((FIXTURES / "mh-sample.xml").read_bytes())
        self.assertEqual(len(doc.cases), 2)
        case = doc.cases[0]
        self.assertTrue(case["testCaseID"].startswith("idm-sssd-tc::"))
        self.assertIn("(ad)", case["testCaseID"])
        self.assertEqual(case["subsystemteam"], "rhel-idm-sssd")
        self.assertIn("setup", case)
        dump = pairs_to_jira_dump(case)
        self.assertEqual(dump["ID"], case["testCaseID"])
        self.assertEqual(dump["status"], "Active")
        self.assertIn("Setup", dump["description"])


class DirectoryAndIndexTests(unittest.TestCase):
    def test_find_local_file(self) -> None:
        one = find_local_testcase_xmls(FIXTURES / "bash-sample.xml")
        self.assertEqual(one, [FIXTURES / "bash-sample.xml"])

    def test_find_dir_with_import_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "import-testcase.xml"
            target.write_text(
                (FIXTURES / "bash-sample.xml").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            (root / "alltest-critical_import-testcase.xml").write_text(
                (FIXTURES / "mh-sample.xml").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            found = find_local_testcase_xmls(root)
            self.assertEqual(len(found), 2)

    def test_find_dir_empty(self) -> None:
        with self.assertRaises(Exception):
            find_local_testcase_xmls(FIXTURES)

    def test_parse_index(self) -> None:
        html = """
        <a href="/path/polarion/import-testcase.xml">import-testcase.xml</a>
        <a href="alltest-critical_import-testcase.xml">x</a>
        """
        urls = parse_directory_index_for_testcase_xmls(
            html,
            "https://example.com/path/polarion/",
        )
        self.assertEqual(
            urls,
            [
                "https://example.com/path/polarion/import-testcase.xml",
                "https://example.com/path/polarion/alltest-critical_import-testcase.xml",
            ],
        )


class ProcessDumpTests(unittest.TestCase):
    def test_write_dumps(self) -> None:
        doc = parse_testcase_xml((FIXTURES / "bash-sample.xml").read_bytes())
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            results = process_cases(
                [doc],
                output_dir=out,
                do_import=False,
                jira_config=None,
                project_key="RHELTEST",
                issue_type="Test Case",
                dry_run=False,
                skip_assignee=True,
                skip_components=True,
                limit=1,
            )
            self.assertEqual(len(results), 1)
            self.assertIsNone(results[0].error)
            dump_path = Path(results[0].dump_path or "")
            self.assertTrue(dump_path.is_file())
            parsed = parse_key_value_file(dump_path)
            self.assertEqual(parsed["ID"], results[0].test_case_id)

    def test_overrides(self) -> None:
        dump = apply_dump_overrides(
            {"summary": "x", "labels": "a"},
            tier="1",
            architecture="x86_64",
            labels_extra="b,a",
        )
        self.assertEqual(dump["Tier"], "1")
        self.assertEqual(dump["Architecture"], "x86_64")
        self.assertEqual(dump["labels"], "a,b")

    def test_dump_filename(self) -> None:
        name = dump_filename_for_id("idm-sssd-tc::tests/foo.py::test_x (ad)")
        self.assertTrue(name.endswith(".properties"))
        self.assertNotIn(":", name)
        self.assertNotIn("/", name)

    def test_import_dry_run_mocked(self) -> None:
        doc = parse_testcase_xml((FIXTURES / "bash-sample.xml").read_bytes())
        fake = type(
            "R",
            (),
            {
                "to_dict": staticmethod(
                    lambda: {
                        "action": "dry-run-create",
                        "issue_key": None,
                        "match": "none",
                        "browse_url": None,
                    }
                )
            },
        )()
        with patch("ai_tools.beetlejuice.import_testcase", return_value=fake):
            results = process_cases(
                [doc],
                output_dir=None,
                do_import=True,
                jira_config=object(),  # type: ignore[arg-type]
                project_key="RHELTEST",
                issue_type="Test Case",
                dry_run=True,
                skip_assignee=True,
                skip_components=True,
                limit=1,
            )
        self.assertEqual(results[0].import_result["action"], "dry-run-create")


class CliSubcommandTests(unittest.TestCase):
    def test_test_case_dump(self) -> None:
        from ai_tools.beetlejuice import main

        with tempfile.TemporaryDirectory() as tmp:
            code = main(
                [
                    "test-case",
                    str(FIXTURES / "bash-sample.xml"),
                    "-o",
                    tmp,
                    "--limit",
                    "1",
                ]
            )
            self.assertEqual(code, 0)
            self.assertTrue(any(Path(tmp).glob("*.properties")))

    def test_test_run_not_implemented(self) -> None:
        from ai_tools.beetlejuice import main

        code = main(["test-run"])
        self.assertEqual(code, 1)

    def test_requires_subcommand(self) -> None:
        from ai_tools.beetlejuice import main

        code = main([])
        self.assertEqual(code, 2)

    def test_test_case_requires_action(self) -> None:
        from ai_tools.beetlejuice import main

        code = main(["test-case", str(FIXTURES / "bash-sample.xml")])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
