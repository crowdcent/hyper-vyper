"""Exercise the guard against source patterns implicated by compiler advisories."""

import pytest

from hyper_vyper.check_source import check_source


@pytest.mark.parametrize(
    "bad",
    [
        b"\x0b",
        b"\x0c",
        b"\x1c",
        b"\x1d",
        b"\x1e",
        b"\x7f",
        "\u0085".encode(),
        "\u2028".encode(),
        "\u2029".encode(),
        "\ufeff".encode(),
        "\u200b".encode(),
    ],
)
def test_bad_bytes_rejected_even_in_comments(bad):
    with pytest.raises(ValueError, match="ASCII"):
        check_source(b"# harmless looking comment" + bad + b"\nA: constant(uint256) = 1\n")


@pytest.mark.parametrize(
    "source,reason",
    [
        ("@external\ndef f(flag: bool) -> uint256:\n    return 1 if flag else 2\n", "Conditional"),
        ("@external\ndef f(x: uint256 = 1):\n    pass\n", "default"),
        ("A: constant(uint256) = lib.A\n", "Constants"),
        ("@external\ndef f(target: address):\n    create_from_blueprint(target)\n", "blueprint"),
    ],
)
def test_disallowed_constructs(source, reason):
    with pytest.raises(ValueError, match=reason):
        check_source(source.encode())


def test_literal_constants_and_normal_branch_are_allowed():
    check_source(
        b"A: constant(uint32) = max_value(uint32)\n@external\ndef f(flag: bool) -> uint256:\n    if flag:\n        return 1\n    return 2\n"
    )
