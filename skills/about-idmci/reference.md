# IdM-CI docs reference (global map)

Paths are relative to `~/git/idmcidoc-fork-main/`.  
HTML: `https://docs-idmci.psi.redhat.com/<path-without-.adoc>.html`  
Upstream: https://gitlab.cee.redhat.com/identity-management/docs-idmci

Chatbot tone notes (optional): `notebooklm/chatbot-instructions.md`  
Annotated samples: `notebooklm/metadata-samples.txt`, `notebooklm/testplan-samples.txt`

---

## Intro / install / LTE

| Topic | Path |
|-------|------|
| Getting started (LTE vs CI, `te`, controller) | `user_docs/guides/intro/user_getting_started.adoc` |
| Installation | `user_docs/guides/intro/installation.adoc` |
| Communication / support channels | `user_docs/guides/intro/communication.adoc` |
| User guides index | `user_docs/guides/index.adoc` |

---

## Workflow & architecture

| Topic | Path |
|-------|------|
| Job metadata files | `user_docs/guides/workflow_and_architecture/job_files.adoc` |
| Domains / hosts | `user_docs/guides/workflow_and_architecture/pipeline_domains_specifications.adoc` |
| Phases / steps | `user_docs/guides/workflow_and_architecture/pipeline_phases_steps.adoc` |
| Playbooks | `user_docs/guides/workflow_and_architecture/playbooks.adoc` |
| Test plans | `user_docs/guides/workflow_and_architecture/test_plan.adoc` |
| Creating test plans | `user_docs/guides/workflow_and_architecture/creating_testplans.adoc` |
| Metadata modifier / TOKEN_ / IDMCI_* | `user_docs/guides/workflow_and_architecture/metadata_modifier.adoc` |
| Environment variables | `user_docs/guides/workflow_and_architecture/ENVVARS.adoc` |
| Metadata sanity checker | `user_docs/guides/workflow_and_architecture/metadata_sanity_checker.adoc` |
| Random strings in metadata | `user_docs/guides/workflow_and_architecture/random_strings_metadata.adoc` |
| Multidomain support | `user_docs/guides/workflow_and_architecture/multidomain_support.adoc` |
| Artifacts and logs | `user_docs/guides/workflow_and_architecture/artifacts_and_logs.adoc` |
| Artifacts / test results | `user_docs/guides/workflow_and_architecture/artifacts_test_results.adoc` |
| Qualifications | `user_docs/guides/workflow_and_architecture/qualifications.adoc` |
| QEW | `user_docs/guides/workflow_and_architecture/QEW.adoc` |
| Report Portal | `user_docs/guides/workflow_and_architecture/report_portal.adoc` |
| Polarion import | `user_docs/guides/workflow_and_architecture/polarion_import.adoc` |
| Release dashboard | `user_docs/guides/workflow_and_architecture/release_dashboard.adoc` |
| RHEL gating | `user_docs/guides/workflow_and_architecture/rhel_gating.adoc` |
| RHEL on GitLab | `user_docs/guides/workflow_and_architecture/rhel_on_gitlab.adoc` |
| Windows support (overview) | `user_docs/guides/workflow_and_architecture/windows_support.adoc` |
| Windows domains | `user_docs/guides/workflow_and_architecture/windows_support/windows_domains_specifications.adoc` |
| Windows images automation | `user_docs/guides/workflow_and_architecture/windows_support/windows_images_automation.adoc` |
| Windows images playbooks | `user_docs/guides/workflow_and_architecture/windows_support/windows_images_playbooks.adoc` |

---

## Labs

| Topic | Path |
|-------|------|
| Labs overview | `user_docs/guides/labs/labs.adoc` |
| Authentication / clouds | `user_docs/guides/labs/authentication.adoc` |
| Managing VMs | `user_docs/guides/labs/managing_vms.adoc` |
| Lab rules | `user_docs/guides/labs/lab_rules.adoc` |

---

## Jenkins

| Topic | Path |
|-------|------|
| Jenkins overview | `user_docs/guides/jenkins/jenkins.adoc` |
| Add a test plan | `user_docs/guides/jenkins/jenkins_add_test_plan.adoc` |
| Engineer pipelines | `user_docs/guides/jenkins/jenkins_engineer_pipelines.adoc` |
| Run a qualification | `user_docs/guides/jenkins/jenkins_run_qualification.adoc` |
| Trigger tool | `user_docs/guides/jenkins/jenkins_trigger_tool.adoc` |

---

## Use-case examples

| Topic | Path |
|-------|------|
| Examples index | `user_docs/guides/use_case_examples/use_case_examples.adoc` |
| SSSD | `user_docs/guides/use_case_examples/sssd.adoc` |
| IPA pytest | `user_docs/guides/use_case_examples/ipa_pytest.adoc` |
| IPA restraint | `user_docs/guides/use_case_examples/ipa_restraint.adoc` |
| IPA dynamic restraint | `user_docs/guides/use_case_examples/ipa_dynamic_restraint.adoc` |
| IPA XML-RPC | `user_docs/guides/use_case_examples/ipa_xmlrpc.adoc` |
| IPA static Windows | `user_docs/guides/use_case_examples/ipa_static_windows.adoc` |
| IPA dynamic Windows | `user_docs/guides/use_case_examples/ipa_dynamic_windows.adoc` |
| Bootc (user) | `user_docs/guides/use_case_examples/bootc_user.adoc` |
| HSM automation | `user_docs/guides/use_case_examples/hsm_automation.adoc` |
| Upstream tests / git | `user_docs/guides/use_case_examples/upstream_tests_git.adoc` |
| Prebuilt scenarios | `user_docs/guides/use_case_examples/prebuilt_scenarios_for_developers.adoc` |
| Long-running jobs | `user_docs/guides/use_case_examples/long_running_jobs.adoc` |
| JNLP extended agent | `user_docs/guides/use_case_examples/jnlp_extended_agent.adoc` |

---

## Maintainer docs (designs, infra, release)

Use only when the question is about maintaining IdM-CI, designs, packaging, or service tooling.

| Area | Entry |
|------|-------|
| Maintainer guide | `maintainer_docs/guide.adoc` |
| Guides index | `maintainer_docs/guides/index.adoc` |
| Contributing | `maintainer_docs/guides/contributing/` |
| Designs | `maintainer_docs/guides/designs/` |
| mrack | `maintainer_docs/guides/mrack/` |
| Release workflow | `maintainer_docs/guides/release_workflow/` |
| Service tools (runners, secrets, janitor, DNS, …) | `maintainer_docs/guides/service_tools/` |
| Slack automation | `maintainer_docs/guides/slack/slack_automation.adoc` |

---

## Keyword → start here

| Ask about… | Start with |
|-------------|------------|
| What is IdM-CI / how do I start | `intro/user_getting_started.adoc` |
| `te`, LTE, controller, twd | `intro/user_getting_started.adoc` |
| `metadata.yaml`, domains, hosts | `job_files.adoc`, `pipeline_domains_specifications.adoc` |
| phases, steps, playbooks | `pipeline_phases_steps.adoc`, `playbooks.adoc` |
| TOKEN_, IDMCI_*, compose override | `metadata_modifier.adoc`, `ENVVARS.adoc` |
| test-plan / jobs.yaml | `test_plan.adoc`, `creating_testplans.adoc` |
| OpenStack / AWS auth | `labs/authentication.adoc` |
| Jenkins job / qualification | `jenkins/*.adoc`, `qualifications.adoc` |
| Artifacts, logs, junit | `artifacts_and_logs.adoc`, `artifacts_test_results.adoc` |
| Windows / AD | `windows_support*.adoc` |
| QEW / qualifications repos | `QEW.adoc`, `qualifications.adoc` |
| Report Portal / Polarion | `report_portal.adoc`, `polarion_import.adoc` |

When unsure, Grep under `user_docs/` for the keyword, then read the matching `.adoc`.
