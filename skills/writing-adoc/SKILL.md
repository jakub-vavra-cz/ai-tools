---
name: writing-adoc
description: >-
  Writes and edits AsciiDoc for docs-idmci-style portals (identity-management/docs-idmci
  and local forks such as idmcidoc-*). Escapes literal braces, follows project guidelines,
  and after any .adoc change runs the repo Makefile build (same flags as CI) until clean.
  Use when creating or modifying .adoc files, designs, user_docs, maintainer_docs, or
  docs-idmci build/Makefile issues.
---

# AsciiDoc (docs-idmci): author and verify build


## Hostnames (`~/git/ai-tools.env`)

Resolve `${GITLAB_HOST}`, `${JENKINS_URL}`, `${DOCS_IDMCI_URL}`, and other Scope A
hosts from `~/git/ai-tools.env` (see [ai-tools README](../../README.md#internal-hostnames-gitai-toolsenvironment)).
Do not invent or hardcode internal hostnames in commands or tracked files.

## Scope

Applies to [docs-idmci](https://${GITLAB_HOST}/identity-management/docs-idmci)
and worktrees that share its layout (`Makefile` with `index` / `user_docs` /
`maintainer_docs`, `macros/source-url.rb`, `common/`).

After **any** `.adoc` edit in such a tree, finish with a successful local build
before considering the task done. CI fails the job on AsciiDoc **warnings**
(`--failure-level=info`).

## Local toolchain

Install (Fedora / host playbook):

```bash
# From jvavra-test-tools playbooks/
ansible-playbook idmci.yml --tags docs
# or: make install-deps  # in the docs repo
# or: dnf install -y rubygem-asciidoctor make findutils buildah podman
```

Confirm: `asciidoctor --version` and `make -C <docs-root> -n all`.

## Authoring rules (docs-idmci)

Match [README.md](https://${GITLAB_HOST}/identity-management/docs-idmci/-/blob/main/README.md)
and nearby pages:

1. **Owner header** on new pages — set `:owner:` / `:owner-id:` and
   `include::{section-header-relpath}[]` after the section title.
2. **Custom section IDs** — `[#my_id]` / `[[my_id]]`; use `<<my_id>>` /
   `xref:` for links (not bare `link:` for internal refs).
3. **Index** — register new pages in the directory index (and designs table
   for design docs).
4. **Images** — under `images/`; `image::file.png[]`.
5. **Literal braces** — AsciiDoc expands `{name}` as attributes. CI uses
   `-a attribute-missing=warn` and **fails on warnings**. For placeholders
   that are **not** defined attributes, escape like the rest of the tree:

   ```asciidoc
   \{prefix}/\{project}/\{version.name}/
   `$\{NAME}`
   ```

   Real attributes (`{section-header-relpath}`, values from `common/`) stay
   unescaped. Prefer rewriting prose (`project + version.name`) when braces
   are only decorative.

6. Do not leave unresolved `WARNING: skipping reference to missing attribute`
   in build output.

## After any `.adoc` change — build gate

1. Find the **docs root** (directory with this repo’s `Makefile` that defines
   `all` / `user_docs` / `maintainer_docs` and `macros/source-url.rb`). Walk up
   from the edited file if needed.
2. Prefer a **scoped** target when only one tree changed:
   - edits under `maintainer_docs/` → `make maintainer_docs`
   - edits under `user_docs/` → `make user_docs`
   - edits under `index/` or cross-cutting → `make all`
3. Run from the docs root with the same semantics as CI / Makefile:

   ```bash
   cd "$DOCS_ROOT"
   make clean   # optional; use if a prior html/ is stale or root-owned
   make maintainer_docs   # or user_docs / all
   ```

   Underlying flags (do not weaken):  
   `asciidoctor … -a attribute-missing=warn --warnings --verbose --failure-level=info`

4. **Fail the task** if make exits non-zero or the log contains
   `missing attribute` / `WARNING:` from asciidoctor. Fix the `.adoc` and
   rebuild until clean.
5. If host `asciidoctor` / `make` is missing, install via `--tags docs` (above)
   or the docs container image used by the project; do not skip the gate.

Container fallback (when host packages are unavailable):

```bash
cd "$DOCS_ROOT"
podman run --rm --user root -v "$PWD:/docs:Z" -w /docs \
  quay.io/idmops/docs-idmci-base:latest make maintainer_docs
```

(Use `user_docs` / `all` as appropriate. Ensure the bind mount is writable.)

## Quick checklist

- [ ] Braces escaped or real attributes only
- [ ] New page indexed / owner header present when required
- [ ] `make <scoped|all>` succeeds with no asciidoctor warnings
