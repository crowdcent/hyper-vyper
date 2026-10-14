"""Build the wheel and use it from a fresh uv project, as a user would.

Slow, and needs `uv` on PATH. uv fetches vyper and titanoboa unless its cache has
them (set UV_OFFLINE=1 to forbid the network). Excluded by default. Run it with:

    uv run --locked pytest -m packaging
"""

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"

pytestmark = pytest.mark.packaging

WHEEL_FILES = {
    "hyper_vyper/bridge.vy",
    "hyper_vyper/constants.vy",
    "hyper_vyper/conversions.vy",
    "hyper_vyper/core_writer.vy",
    "hyper_vyper/precompiles.vy",
    "hyper_vyper/check_source.py",
    "hyper_vyper/testing/__init__.py",
    "hyper_vyper/testing/_precompiles.py",
    "hyper_vyper/testing/live.py",
    "hyper_vyper/testing/measured.py",
    "hyper_vyper/testing/sim.py",
    "hyper_vyper/testing/data/live_replies.json",
}


def run(args, cwd, env):
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, f"{args}\n{result.stdout}\n{result.stderr}"
    return result.stdout


@pytest.fixture(scope="module")
def uv_env():
    if shutil.which("uv") is None:
        pytest.skip("uv is not on PATH")
    env = dict(os.environ)
    # Do not let the outer `uv run` environment leak into the fresh project.
    for name in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "PYTHONPATH"):
        env.pop(name, None)
    return env


@pytest.fixture(scope="module")
def wheel(tmp_path_factory, uv_env):
    out = tmp_path_factory.mktemp("dist")
    run(["uv", "build", "--wheel", "--out-dir", str(out), str(ROOT)], ROOT, uv_env)
    (path,) = out.glob("hyper_vyper-*.whl")
    return path


@pytest.fixture(scope="module")
def project(tmp_path_factory, uv_env, wheel):
    path = tmp_path_factory.mktemp("consumer")
    python = f"{sys.version_info.major}.{sys.version_info.minor}"
    run(["uv", "init", "--bare", "--no-workspace", "--python", python, str(path)], path, uv_env)
    run(["uv", "add", "--project", str(path), f"{wheel}[testing]", "pytest"], path, uv_env)
    for name in ("spot_round_trip.vy", "test_spot_round_trip.py"):
        shutil.copy(EXAMPLES / name, path / name)
    return path


def test_wheel_contains_only_the_package(wheel):
    with zipfile.ZipFile(wheel) as archive:
        names = {name for name in archive.namelist() if ".dist-info/" not in name}
    assert names == WHEEL_FILES


def test_vyper_cli_finds_the_installed_modules(project, uv_env):
    # No -p option: Vyper searches sys.path, where the wheel installed hyper_vyper.
    contract = "spot_round_trip.vy"
    for module in ("bridge", "constants", "conversions", "core_writer", "precompiles"):
        assert f"from hyper_vyper import {module}\n" in (project / contract).read_text()
    abi = run(["uv", "run", "vyper", contract, "-f", "abi"], project, uv_env)
    assert '"name": "deposit_to_spot"' in abi
    version = run(["uv", "run", "vyper", "--version"], project, uv_env)
    assert version.startswith("0.4.3")


def test_source_checker_command_is_installed(project, uv_env):
    # Users run the advisory checks on their own contracts with this command.
    out = run(["uv", "run", "hyper-vyper-check-source", "spot_round_trip.vy"], project, uv_env)
    assert "passed for 1 files" in out


def test_testing_quick_start_runs_from_the_wheel(project, uv_env):
    # The test shown in docs/testing/quick-start.md, run in the fresh project.
    run(["uv", "run", "pytest", "-q", "-p", "no:cacheprovider"], project, uv_env)
