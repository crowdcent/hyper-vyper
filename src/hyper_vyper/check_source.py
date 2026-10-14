"""Source restrictions for the pinned Vyper compiler. They are not an audit.

The checks reject non-ASCII bytes and the source patterns that the advisories
describe, before the compiler sees the file. See docs/security.md for the
advisories and the limits of these checks. Check your own contracts and their
full import graph too:

    uv run hyper-vyper-check-source contracts/
"""

import sys
from pathlib import Path

from vyper import ast as vy_ast
from vyper.exceptions import VyperException


def check_source(source: bytes):
    if any(byte not in (9, 10, 13) and not 32 <= byte <= 126 for byte in source):
        raise ValueError("Only printable ASCII, tabs and ordinary newlines are allowed")
    tree = vy_ast.parse_to_ast(source.decode("ascii"))
    if tree.get_descendants(vy_ast.IfExp):
        raise ValueError("Conditional expressions are disallowed on this compiler")
    for call in tree.get_descendants(vy_ast.Call):
        if isinstance(call.func, vy_ast.Name) and call.func.id == "create_from_blueprint":
            raise ValueError("create_from_blueprint is disallowed on this compiler")
    for function in tree.get_descendants(vy_ast.FunctionDef):
        if function.args.defaults:
            raise ValueError("Function default arguments are disallowed on this compiler")
    for declaration in tree.get_descendants(vy_ast.VariableDecl):
        if not declaration.is_constant:
            continue
        value = declaration.value
        literal = isinstance(
            value, (vy_ast.Int, vy_ast.Hex, vy_ast.Bytes, vy_ast.Str, vy_ast.NameConstant)
        )
        # The only non-literal declaration needed is max_value(uint32),
        # a compiler-folded builtin with no reference to an imported symbol.
        max_uint32 = (
            isinstance(value, vy_ast.Call)
            and isinstance(value.func, vy_ast.Name)
            and value.func.id == "max_value"
            and len(value.args) == 1
            and isinstance(value.args[0], vy_ast.Name)
            and value.args[0].id == "uint32"
            and not value.keywords
        )
        if not literal and not max_uint32:
            raise ValueError("Constants must be literals or max_value(uint32)")


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: hyper-vyper-check-source PATH [PATH ...] (files or directories)")
    paths = [Path(path) for path in sys.argv[1:]]
    files = sorted(
        {file for path in paths for file in (path.rglob("*.vy") if path.is_dir() else [path])}
    )
    if not files:
        raise SystemExit("No Vyper source files found")
    for path in files:
        try:
            check_source(path.read_bytes())
        except (OSError, ValueError, VyperException) as exc:
            raise SystemExit(f"{path}: {exc}") from exc
    print(f"Compiler source restrictions passed for {len(files)} files (not an audit).")


if __name__ == "__main__":
    main()
