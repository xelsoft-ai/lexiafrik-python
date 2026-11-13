# Releasing the SDK

How a new version of `lexiafrik` reaches PyPI. Publishing uses **Trusted Publishing**: GitHub proves its identity
to PyPI, so there is **no API token** to create, store or rotate.

## One-time setup (already done for the first release)

| Where | What |
|---|---|
| pypi.org and test.pypi.org | One account each (2FA enabled, recovery codes stored offline). Add a second maintainer to the project. |
| pypi.org → Account → Publishing | Publisher for project `lexiafrik`: owner `xelsoft-ai`, repository `lexiafrik-python`, workflow `publish.yml`, environment `pypi`. |
| test.pypi.org → Publishing | Same values, environment `testpypi`. |
| GitHub → Settings → Environments | Environments `pypi` and `testpypi`. On `pypi`, add **Required reviewers** so each real publication waits for a human approval. |

The workflow is `.github/workflows/publish.yml`. Do not rename it or the environments without updating the
publishers on PyPI: a mismatch makes the upload fail with an authentication error.

## Releasing a version

Versions are **immutable**: a number published on PyPI can never be reused, even after deleting the file. Fix a
mistake by publishing the next number (`2.0.1`), never by editing a published one.

1. **Choose the number** ([semantic versioning](https://semver.org)): `2.0.1` for fixes, `2.1.0` for new
   features, `3.0.0` for breaking changes.
2. **Bump it in both places** and keep them equal: `lexiafrik/__init__.py` (`__version__`) and `setup.py` (`version`).
3. **Update `CHANGELOG.md`** (and the documentation site if the API surface changed).
4. **Check locally:**
   ```bash
   python -m unittest discover -s tests
   python -m pip install build twine
   python -m build && python -m twine check dist/*
   ```
5. **Commit and push to `main`.** The workflow publishes what is on the tagged commit, so push first.
6. **(Optional) dry run on TestPyPI.** Use a pre-release number (`2.1.0rc1`) because TestPyPI also refuses
   reused numbers. GitHub → Actions → *Publication* → *Run workflow* → target `testpypi`. Then, in a clean
   environment:
   ```bash
   pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ lexiafrik
   lexiafrik --help
   ```
   Set the final number back before the real release.
7. **Publish for real:** GitHub → Releases → *Draft a new release* → new tag `vX.Y.Z` on `main` → *Publish
   release*. The workflow runs the tests, builds, then waits for approval.
8. **Approve:** Actions → the *Publication* run → *Review deployments* → tick `pypi` → *Approve and deploy*.
9. **Verify** in a clean environment:
   ```bash
   pip install --upgrade lexiafrik
   python -c "import lexiafrik; print(lexiafrik.__version__)"
   lexiafrik --help
   ```
   and open https://pypi.org/project/lexiafrik/.

## If something goes wrong

| Symptom | Cause / fix |
|---|---|
| Upload fails with an authentication / "invalid-publisher" error | The publisher on PyPI does not match exactly (owner, repository, workflow file name, environment). Compare each field with the table above. |
| "File already exists" | That version number was already uploaded. Bump the number. |
| The run never asks for approval | The tests or the build failed (red step), or the environment has no required reviewer. Read the failing step. |
| A published version is broken | Do not delete it. On PyPI, *Manage* → the release → **Yank** (it stays installable by exact pin but is skipped by default), then publish the fix. |
| Locked out of the PyPI account | Use the stored recovery codes. This is why a second maintainer and offline codes matter. |

## Rules

- Never create or commit an API token; Trusted Publishing needs none. If one exists, revoke it.
- Publish only from `main`, through the workflow, never from a laptop.
- After each release, update `docs.lexiafrik.com` (SDK page, changelog) so the documentation matches.
