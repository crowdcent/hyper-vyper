"""Build the Solidity reference that the tests compare with, from pinned sources.

uv run --locked scripts/solidity_reference.py --fetch  # explicit network refresh
uv run --locked scripts/solidity_reference.py --check  # offline compile and compare
Requires: npm ci --prefix tests/reference --ignore-scripts
"""

import argparse
import hashlib
import json
import posixpath
import re
import subprocess
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / "tests" / "reference"
HL_REV = "4eb7ab044d0a368e0c01ec5b38d5ea48a3e3b427"
OZ_REV = "c64a1edb67b6e3f4a15cca8909c9482ad33a02b0"  # upstream gitlink
SOURCES = REF / "upstream.json"
ARTIFACT = REF / "artifact.json"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_sources():
    pending = ["src/CoreWriterLib.sol", "src/PrecompileLib.sol", "src/common/HLConversions.sol"]
    sources = {}
    while pending:
        path = pending.pop()
        if path in sources:
            continue
        if path.startswith("@openzeppelin/"):
            repo, rev, relative = (
                "OpenZeppelin/openzeppelin-contracts",
                OZ_REV,
                path.removeprefix("@openzeppelin/"),
            )
        else:
            repo, rev, relative = "hyperliquid-dev/hyper-evm-lib", HL_REV, path
        url = f"https://raw.githubusercontent.com/{repo}/{rev}/{relative}"
        with urlopen(url, timeout=30) as response:
            content = response.read().decode()
        sources[path] = {"content": content, "url": url, "sha256": sha(content.encode())}
        for dependency in re.findall(
            r'import\s+(?:[^;]*?from\s+)?["\']([^"\']+)["\']\s*;', content
        ):
            if dependency.startswith("."):
                dependency = posixpath.normpath(posixpath.join(posixpath.dirname(path), dependency))
            pending.append(dependency)
    # Preserve both licenses with the vendored source.
    for label, repo, rev in [
        ("hyper-evm-lib", "hyperliquid-dev/hyper-evm-lib", HL_REV),
        ("openzeppelin", "OpenZeppelin/openzeppelin-contracts", OZ_REV),
    ]:
        with urlopen(
            f"https://raw.githubusercontent.com/{repo}/{rev}/LICENSE", timeout=30
        ) as response:
            (REF / f"LICENSE-{label}").write_bytes(response.read())
    SOURCES.write_text(
        json.dumps(
            {"hyper_evm_lib": HL_REV, "openzeppelin": OZ_REV, "sources": sources},
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def build():
    manifest = json.loads(SOURCES.read_text())
    assert manifest["hyper_evm_lib"] == HL_REV and manifest["openzeppelin"] == OZ_REV
    sources = {}
    for path, entry in manifest["sources"].items():
        assert sha(entry["content"].encode()) == entry["sha256"], (
            f"Modified upstream source: {path}"
        )
        sources[path] = {"content": entry["content"]}
    sources["Reference.sol"] = {"content": (REF / "Reference.sol").read_text()}
    settings = {
        "optimizer": {"enabled": True, "runs": 200},
        "evmVersion": "cancun",
        "outputSelection": {"*": {"*": ["abi", "evm.bytecode.object"]}},
    }
    compiler_input = {"language": "Solidity", "sources": sources, "settings": settings}
    result = subprocess.run(
        ["node", str(REF / "compile.cjs")],
        input=json.dumps(compiler_input),
        text=True,
        capture_output=True,
        check=True,
    )
    compiled = json.loads(result.stdout)
    assert compiled["version"] == "0.8.30+commit.73712a01.Emscripten.clang", compiled["version"]
    errors = [
        e["formattedMessage"]
        for e in compiled["output"].get("errors", [])
        if e["severity"] == "error"
    ]
    if errors:
        raise RuntimeError("\n".join(errors))
    contract = compiled["output"]["contracts"]["Reference.sol"]["Reference"]
    return {
        "compiler": compiled["version"],
        "upstream_sha256": sha(SOURCES.read_bytes()),
        "wrapper_sha256": sha((REF / "Reference.sol").read_bytes()),
        "settings": settings,
        "abi": contract["abi"],
        "bytecode": contract["evm"]["bytecode"]["object"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.fetch:
        fetch_sources()
    content = json.dumps(build(), indent=2, sort_keys=True) + "\n"
    if args.check:
        assert ARTIFACT.read_text() == content, "Reference artifact differs; regenerate and review."
        print("Solidity reference artifact reproduced exactly.")
    else:
        ARTIFACT.write_text(content)
        print(f"Wrote {ARTIFACT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
