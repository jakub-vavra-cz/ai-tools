from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from ai_tools.dump_polarion_testcase import parse_key_value_file
from ai_tools.scan_python_testcase import (
    build_polarion_pairs,
    collect_tests,
    dump_filename_for_id,
    expand_parametrize_combinations,
    load_polarion_config,
    parse_docstring_fields,
    parse_numbered_list,
    parse_parametrize_marks,
    scan_and_write,
)


SAMPLE_MODULE = textwrap.dedent(
    '''\
    """Module docs.

    :requirement: IDM-SSSD-REQ: Demo
    """

    import pytest


    @pytest.mark.importance("medium")
    def test_login_offline():
        """
        :title: Authenticate when provider is offline
        :setup:
            1. Create user
            2. Start SSSD
        :steps:
            1. Login as user
            2. Offline login
        :expectedresults:
            1. User can log in
            2. User can log in
        :customerscenario: True
        """
        assert True


    class TestGroup:
        def test_inside_class(self):
            """
            :title: Class method title
            :setup:
                1. Setup
            :steps:
                1. Do thing
            :expectedresults:
                1. Thing done
            :customerscenario: False
            """
            pass
    '''
)

PARAM_MODULE = textwrap.dedent(
    '''\
    """Param samples.

    :requirement: authentication
    """

    import pytest
    from sssd_test_framework.topology import KnownTopology, KnownTopologyGroup


    @pytest.mark.topology(KnownTopologyGroup.AnyProvider)
    @pytest.mark.parametrize("method", ["ssh", "su"])
    @pytest.mark.parametrize("sssd_service_user", ("root", "sssd"))
    @pytest.mark.importance("medium")
    def test_auth_offline(method, sssd_service_user):
        """
        :title: Authenticate with modified PAM when the provider is offline
        :setup:
            1. Create user
        :steps:
            1. Login as user
        :expectedresults:
            1. User can log in
        :customerscenario: True
        """
        assert True


    @pytest.mark.topology(KnownTopology.LDAP)
    @pytest.mark.parametrize("cache", ["users", "groups"], ids=["by-name", "by-group"])
    def test_cache(cache):
        """
        :title: Lookup objects
        :setup:
            1. Start SSSD
        :steps:
            1. Look up
        :expectedresults:
            1. Found
        :customerscenario: False
        """
        pass
    '''
)

POLARION_YAML = textwrap.dedent(
    """\
    testcase:
      required:
        title:
          transform:
            pattern: "^(.*)$"
            replace: "IDM-SSSD-TC: \\\\1"
          validate: "IDM-SSSD-TC: (.+)"
        setup:
          format: pre
        steps:
        expectedresults:
        customerscenario:
        caseimportance:
        requirement:
      optional:
        id:
          default: "idm-sssd-tc::{{ item.id }}"
        caseautomation:
          default: "automated"
        casecomponent:
          default: "sssd"
        status:
          default: "approved"
        subsystemteam:
          default: "rhel-idm-sssd"
        upstream:
          default: "yes"
        automation_script:
          default: "{{ tests_url }}/{{ item.location.file }}#L{{ item.location.line }}"
        testtype:
          default: "functional"
        caselevel:
          default: "system"
    """
)


class DocstringParseTests(unittest.TestCase):
    def test_fields(self) -> None:
        fields = parse_docstring_fields(
            ":title: Hello\n:setup:\n  1. A\n:customerscenario: True\n"
        )
        self.assertEqual(fields["title"], "Hello")
        self.assertIn("1. A", fields["setup"])
        self.assertEqual(fields["customerscenario"], "True")

    def test_numbered_list(self) -> None:
        items = parse_numbered_list("1. First\n2. Second line\n   continued\n")
        self.assertEqual(items[0], (1, "First"))
        self.assertEqual(items[1][0], 2)
        self.assertIn("Second line", items[1][1])


class CollectTests(unittest.TestCase):
    def test_collects_function_and_class_methods(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "test_sample.py"
            path.write_text(SAMPLE_MODULE, encoding="utf-8")
            tests = collect_tests(path, relative_to=root)
            names = {t.name for t in tests}
            self.assertEqual(names, {"test_login_offline", "test_inside_class"})
            offline = next(t for t in tests if t.name == "test_login_offline")
            self.assertEqual(offline.nodeid, "test_sample.py::test_login_offline")
            self.assertEqual(offline.fields["title"], "Authenticate when provider is offline")
            self.assertEqual(offline.markers.get("importance"), ["medium"])
            self.assertEqual(offline.fields["requirement"], "IDM-SSSD-REQ: Demo")


class ParametrizeExpandTests(unittest.TestCase):
    def test_stacked_parametrize_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "test_param.py"
            path.write_text(PARAM_MODULE, encoding="utf-8")
            source = path.read_text(encoding="utf-8")
            import ast

            mod = ast.parse(source)
            func = next(
                n
                for n in mod.body
                if getattr(n, "name", None) == "test_auth_offline"
            )
            marks = parse_parametrize_marks(func.decorator_list)
            combos = expand_parametrize_combinations(marks)
            ids = [param_id for _, param_id in combos]
            self.assertEqual(
                ids,
                ["root-ssh", "root-su", "sssd-ssh", "sssd-su"],
            )

    def test_expands_parametrize_and_topology(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "test_param.py"
            path.write_text(PARAM_MODULE, encoding="utf-8")
            tests = collect_tests(path, relative_to=root)
            auth = [t for t in tests if t.name == "test_auth_offline"]
            # 4 param combos × 4 topologies (AnyProvider)
            self.assertEqual(len(auth), 16)
            nodeids = {t.nodeid for t in auth}
            self.assertIn(
                "test_param.py::test_auth_offline[root-ssh] (ad)",
                nodeids,
            )
            self.assertIn(
                "test_param.py::test_auth_offline[sssd-su] (samba)",
                nodeids,
            )
            sample = next(
                t for t in auth if t.nodeid.endswith("[root-ssh] (ad)")
            )
            self.assertEqual(sample.params["sssd_service_user"], "root")
            self.assertEqual(sample.params["method"], "ssh")
            self.assertEqual(sample.topology, "ad")
            self.assertIn("sssd_service_user=root", sample.fields["title"])
            self.assertIn("method=ssh", sample.fields["title"])
            self.assertIn("topology=ad", sample.fields["title"])

            cache = [t for t in tests if t.name == "test_cache"]
            self.assertEqual(len(cache), 2)
            self.assertEqual(
                {t.nodeid for t in cache},
                {
                    "test_param.py::test_cache[by-name] (ldap)",
                    "test_param.py::test_cache[by-group] (ldap)",
                },
            )


class BuildPairsTests(unittest.TestCase):
    def test_without_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "test_sample.py"
            path.write_text(SAMPLE_MODULE, encoding="utf-8")
            test = collect_tests(path, relative_to=root)[0]
            pairs = build_polarion_pairs(
                test,
                id_prefix="idm-sssd-tc",
                title_prefix="IDM-SSSD-TC: ",
                overrides={"casecomponent": "sssd", "subsystemteam": "rhel-idm-sssd"},
                tests_url="https://example.com/tree/main",
            )
            self.assertEqual(
                pairs["testCaseID"],
                "idm-sssd-tc::test_sample.py::test_login_offline",
            )
            self.assertTrue(pairs["title"].startswith("IDM-SSSD-TC: "))
            self.assertEqual(pairs["caseimportance"], "medium")
            self.assertEqual(pairs["casecomponent"], "sssd")
            self.assertEqual(pairs["teststep.1.step"], "Login as user")
            self.assertEqual(pairs["teststep.1.expectedResult"], "User can log in")
            self.assertIn("https://example.com/tree/main/", pairs["automation_script"])

    def test_with_polarion_yaml(self) -> None:
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("PyYAML not installed")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "test_sample.py"
            path.write_text(SAMPLE_MODULE, encoding="utf-8")
            cfg_path = root / "polarion.yaml"
            cfg_path.write_text(POLARION_YAML, encoding="utf-8")
            cfg = load_polarion_config(cfg_path)
            test = next(
                t
                for t in collect_tests(path, relative_to=root)
                if t.name == "test_login_offline"
            )
            pairs = build_polarion_pairs(
                test,
                config=cfg,
                tests_url="https://github.com/SSSD/sssd/tree/master/src/tests/system",
            )
            self.assertEqual(
                pairs["testCaseID"],
                "idm-sssd-tc::test_sample.py::test_login_offline",
            )
            self.assertEqual(
                pairs["title"],
                "IDM-SSSD-TC: Authenticate when provider is offline",
            )
            self.assertEqual(pairs["casecomponent"], "sssd")
            self.assertEqual(pairs["subsystemteam"], "rhel-idm-sssd")
            self.assertEqual(pairs["upstream"], "yes")
            self.assertTrue(pairs["setup"].startswith("<pre>"))
            self.assertIn("Create user", pairs["setup"])

    def test_param_variant_id_and_summary(self) -> None:
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("PyYAML not installed")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "test_param.py"
            path.write_text(PARAM_MODULE, encoding="utf-8")
            cfg_path = root / "polarion.yaml"
            cfg_path.write_text(POLARION_YAML, encoding="utf-8")
            cfg = load_polarion_config(cfg_path)
            test = next(
                t
                for t in collect_tests(path, relative_to=root)
                if t.nodeid.endswith("[root-ssh] (ad)")
            )
            pairs = build_polarion_pairs(
                test,
                config=cfg,
                tests_url="https://example.com/system",
            )
            self.assertEqual(
                pairs["testCaseID"],
                "idm-sssd-tc::test_param.py::test_auth_offline[root-ssh] (ad)",
            )
            self.assertIn("IDM-SSSD-TC:", pairs["title"])
            self.assertIn("sssd_service_user=root", pairs["title"])
            self.assertIn("method=ssh", pairs["title"])
            self.assertIn("topology=ad", pairs["title"])
            self.assertIn("Parametrized arguments", pairs["description"])
            self.assertIn("Topology: ad", pairs["description"])


    def test_defaults_for_missing_setup_importance_customerscenario(self) -> None:
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("PyYAML not installed")
        module = textwrap.dedent(
            '''\
            """Mod.

            :requirement: demo
            """

            def test_bare():
                """
                :title: Bare test without optional fields
                :steps:
                    1. Run
                :expectedresults:
                    1. Ok
                """
                assert True
            '''
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "test_bare.py"
            path.write_text(module, encoding="utf-8")
            cfg_path = root / "polarion.yaml"
            cfg_path.write_text(POLARION_YAML, encoding="utf-8")
            cfg = load_polarion_config(cfg_path)
            test = collect_tests(path, relative_to=root)[0]
            pairs = build_polarion_pairs(test, config=cfg, tests_url="https://ex/t")
            self.assertNotIn("setup", pairs)
            self.assertEqual(pairs["caseimportance"], "medium")
            self.assertEqual(pairs["customerscenario"], "false")
            jira = __import__(
                "ai_tools.dump_polarion_testcase",
                fromlist=["polarion_pairs_to_jira"],
            ).polarion_pairs_to_jira(pairs, polarion_url="")
            self.assertNotIn("customerscenario", jira.get("labels", ""))
            self.assertNotIn("incomplete", jira.get("labels", ""))

    def test_missing_steps_adds_incomplete_label(self) -> None:
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("PyYAML not installed")
        from ai_tools.dump_polarion_testcase import polarion_pairs_to_jira

        module = textwrap.dedent(
            '''\
            """Mod.

            :requirement: demo
            """

            def test_no_steps():
                """
                :title: Test without steps
                """
                assert True
            '''
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "test_nosteps.py"
            path.write_text(module, encoding="utf-8")
            cfg_path = root / "polarion.yaml"
            cfg_path.write_text(POLARION_YAML, encoding="utf-8")
            cfg = load_polarion_config(cfg_path)
            test = collect_tests(path, relative_to=root)[0]
            pairs = build_polarion_pairs(test, config=cfg, tests_url="https://ex/t")
            self.assertIn("incomplete", pairs.get("tags", "").split(","))
            jira = polarion_pairs_to_jira(pairs, polarion_url="")
            self.assertIn("incomplete", jira.get("labels", "").split(","))

    def test_missing_requirement_adds_label(self) -> None:
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("PyYAML not installed")
        from ai_tools.dump_polarion_testcase import polarion_pairs_to_jira

        module = textwrap.dedent(
            '''\
            def test_no_req():
                """
                :title: Test without requirement
                :steps:
                    1. Run
                :expectedresults:
                    1. Ok
                """
                assert True
            '''
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "test_noreq.py"
            path.write_text(module, encoding="utf-8")
            cfg_path = root / "polarion.yaml"
            cfg_path.write_text(POLARION_YAML, encoding="utf-8")
            cfg = load_polarion_config(cfg_path)
            test = collect_tests(path, relative_to=root)[0]
            pairs = build_polarion_pairs(test, config=cfg, tests_url="https://ex/t")
            self.assertNotIn("requirement", pairs)
            self.assertIn("missing_requirement", pairs.get("tags", "").split(","))
            jira = polarion_pairs_to_jira(pairs, polarion_url="")
            self.assertIn("missing_requirement", jira.get("labels", "").split(","))


class WriteDumpTests(unittest.TestCase):
    def test_scan_and_write_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "src"
            src.mkdir()
            (src / "test_sample.py").write_text(SAMPLE_MODULE, encoding="utf-8")
            out = root / "dumps"
            results = scan_and_write(
                src,
                out,
                relative_to=src,
                auto_polarion_config=False,
                id_prefix="idm-sssd-tc",
                title_prefix="IDM-SSSD-TC: ",
                overrides={
                    "casecomponent": "sssd",
                    "subsystemteam": "rhel-idm-sssd",
                    "upstream": "yes",
                },
                tests_url="https://example.com/t",
            )[0]
            self.assertEqual(len(results), 2)
            dump_path = Path(results[0]["path"])
            self.assertTrue(dump_path.is_file())
            dump = parse_key_value_file(dump_path)
            self.assertIn("summary", dump)
            self.assertTrue(dump["summary"].startswith("IDM-SSSD-TC:"))
            self.assertEqual(dump["components"], "sssd")
            self.assertEqual(dump["AssignedTeam"], "rhel-idm-sssd")
            self.assertIn("customerscenario", dump.get("labels", ""))
            self.assertIn("upstream", dump.get("labels", ""))
            self.assertEqual(dump["status"], "Active")
            self.assertIn("ID=", dump_path.read_text(encoding="utf-8"))

    def test_unique_dump_files_for_params(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "test_param.py").write_text(PARAM_MODULE, encoding="utf-8")
            out = root / "dumps"
            results = scan_and_write(
                root / "test_param.py",
                out,
                relative_to=root,
                auto_polarion_config=False,
                id_prefix="idm-sssd-tc",
            )[0]
            ids = [r["id"] for r in results]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertTrue(all(Path(r["path"]).is_file() for r in results))
            auth = [r for r in results if "test_auth_offline" in r["id"]]
            self.assertEqual(len(auth), 16)
            dump = parse_key_value_file(Path(auth[0]["path"]))
            self.assertIn("=", dump["summary"])  # has param assignments
            self.assertIn("[", dump["ID"])

    def test_filename_sanitized(self) -> None:
        name = dump_filename_for_id(
            "idm-sssd-tc::tests/test_a.py::test_x[root-ssh] (ad)"
        )
        self.assertTrue(name.endswith(".properties"))
        self.assertNotIn("/", name)
        self.assertNotIn(":", name)


if __name__ == "__main__":
    unittest.main()
