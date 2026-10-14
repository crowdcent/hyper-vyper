# Contributing

## Run the tests

You need Python 3.11 or later and [`uv`](https://docs.astral.sh/uv/). You don't
need a wallet, an RPC endpoint or funds.

1. Clone the repository.
2. Install the locked environment. This also installs hyper-vyper itself as an
   editable package, so Vyper and Titanoboa find `hyper_vyper` without `-p`.

    ```bash
    uv sync --locked
    ```

3. Run the tests:

    ```bash
    uv run --locked pytest
    ```

4. Compile an example:

    ```bash
    uv run --locked vyper examples/read_core.vy -f abi,bytecode
    ```

[Repository tests](testing/repository-tests.md) describes each kind of test.

## Checks

CI runs these commands, so run them before you open a pull request.

```bash
uv sync --locked
uv run --locked hyper-vyper-check-source src examples tutorials
uv run --locked ruff check scripts tests tutorials src examples
uv run --locked ruff format --check scripts tests tutorials src examples
uv run --locked pytest
uv run --locked pytest -m packaging
npm ci --prefix tests/reference --ignore-scripts --no-audit --no-fund
uv run --locked scripts/solidity_reference.py --check
```

If you add a revert reason to the library, add it to the table in the
[API reference](reference/api.md#revert-reasons). A test enforces this.

If you intentionally make a function behave differently from Solidity, record
the difference in [compatibility](reference/compatibility.md).

Don't rebuild `tests/reference/artifact.json` only to make a failing comparison
pass.

## Documentation

[Zensical](https://zensical.org/docs/) builds the site from `zensical.toml` and
the Markdown files in `docs/`.

```bash
UV_PROJECT_ENVIRONMENT=.venv-docs uv run --locked --only-group docs zensical serve
UV_PROJECT_ENVIRONMENT=.venv-docs uv run --locked --only-group docs zensical build --strict
```

The site is at http://127.0.0.1:8000 while `serve` runs.

Titanoboa needs an older MkDocs version than Zensical, so the `docs` group and
the test group can't be installed together. `UV_PROJECT_ENVIRONMENT=.venv-docs`
puts the docs group in its own environment and leaves the test environment
intact.

CI deploys the site to GitHub Pages on each push to `main`.

## Release a version

The `Release` workflow publishes to PyPI with
[trusted publishing](https://docs.pypi.org/trusted-publishers/), so the
repository holds no PyPI token. Before it runs, it repeats the checks, builds
the wheel and the sdist, and runs `twine check` on both.

1. Update `version` in `pyproject.toml` and add the release to `CHANGELOG.md`.
2. Run the workflow by hand from the Actions tab. This publishes the build to
   [TestPyPI](https://test.pypi.org/p/hyper-vyper), and you can install it from
   there to check it:

    ```bash
    uv add --index https://test.pypi.org/simple/ --index-strategy unsafe-best-match hyper-vyper
    ```

3. Tag the release commit on `main` and push the tag. The tag must be `v`
   followed by the version in `pyproject.toml`, or the workflow stops:

    ```bash
    git tag v0.1.0
    git push origin v0.1.0
    ```

PyPI doesn't let you upload the same version twice, so a mistake needs a new
version number.
