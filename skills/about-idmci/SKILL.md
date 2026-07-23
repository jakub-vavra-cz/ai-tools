---
name: about-idmci
description: >-
  Answers questions about IdM-CI (LTE, te, metadata, Jenkins, labs, QEW,
  phases/steps, envvars, artifacts) by looking up docs-idmci AsciiDoc.
  Use when the user asks what IdM-CI is, how something works, where a feature
  is documented, or any conceptual/how-to question about idm-ci — not when
  authoring metadata, running te campaigns, or debugging a Jenkins failure URL.
---

# About IdM-CI

Answer IdM-CI questions from **docs-idmci**, not from memory inventing APIs or YAML shapes.

## Sources of truth

| Source | Location |
|--------|----------|
| **GitLab (upstream)** | https://gitlab.cee.redhat.com/identity-management/docs-idmci |
| **Published HTML** | https://docs-idmci.psi.redhat.com/ |
| **Local clone (preferred)** | `~/git/idmcidoc-fork-main/` (repo code `IDMCIDOC`) |

Prefer the **local clone**. Refresh when the answer may be stale or the clone is missing:

```text
MCP user-git-worktrees → worktree_refresh(repo="IDMCIDOC")
```

If the clone is still missing, create/update via `create_worktree_branch` / `list_repos`, or fall back to fetching HTML from docs-idmci.psi.redhat.com (same path with `.html` instead of `.adoc` under `/user_docs/...` or `/maintainer_docs/...`).

## Related skills (hand off)

| Need | Skill |
|------|-------|
| Author `metadata.yaml` / test-plan jobs | [create-idmci-metadata](../create-idmci-metadata/SKILL.md) |
| Run `te` / `@TESTRUNS` campaigns | [run-sssd-tests-idmci](../run-sssd-tests-idmci/SKILL.md) |
| Diagnose a Jenkins build URL | [analyze-jenkins-failure](../analyze-jenkins-failure/SKILL.md) |

This skill is for **understanding and explaining** IdM-CI. After answering, suggest the hand-off skill only if the user wants to implement or run something.

## Workflow

1. **Map the question** to topics in [reference.md](reference.md) (topic → AsciiDoc path).
2. **Read** the matching `.adoc` file(s) under `~/git/idmcidoc-fork-main/`. Use Grep across `user_docs/` (and `maintainer_docs/` only for maintainer/infra questions) when the map is incomplete.
3. **Answer from the docs**: concise, user-facing, with steps/examples from the source. Quote short YAML/CLI snippets when the doc has them.
4. **Cite**: give the relative path under the clone and the published URL when useful, e.g.  
   `user_docs/guides/workflow_and_architecture/job_files.adoc` →  
   https://docs-idmci.psi.redhat.com/user_docs/guides/workflow_and_architecture/job_files.html
5. If docs conflict with local code in `idmci-fork-master`, prefer **docs for concepts**; note the discrepancy and point at the code path only when necessary.

## Answer style

- Lead with the direct answer; no chatbot preamble.
- User perspective (how to use IdM-CI), not “change the framework”.
- Prefer `user_docs/` for end-user questions; use `maintainer_docs/` for designs, release, mrack packaging, service tools, runners.
- If the doc is silent, say so and suggest the closest page or a related skill — do not invent metadata keys or envvars.

## Quick orientation

IdM-CI runs multihost jobs two ways:

- **LTE (local)** — `te` on a controller with a job metadata YAML
- **CI** — Jenkins (or similar) running the same LTE path in parallel jobs

Core concepts live under `user_docs/guides/workflow_and_architecture/` (domains, phases/steps, test plans, modifier, envvars). Getting started: `user_docs/guides/intro/user_getting_started.adoc`.
