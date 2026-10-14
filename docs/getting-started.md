# Install and quick start

hyper-vyper is a Python package of Vyper modules. You install it like any other
Python package, and the Vyper compiler finds the modules on the Python path, so
you don't need a `-p` option.

You need Python 3.11 or later. The examples use [`uv`](https://docs.astral.sh/uv/).

## Installation

Install the package from PyPI:

```bash
uv add hyper-vyper
```

With pip: `pip install hyper-vyper`.

Vyper searches the Python path last, so a directory you pass with `-p` takes
priority. The `--disable-sys-path` option turns off the Python path search. If
you use it, pass the `site-packages` directory with `-p`.

If your project uses Moccasin, see
[the Moccasin section](#if-your-project-uses-moccasin).

To try changes that aren't released yet, install from Git:

```bash
uv add git+https://github.com/crowdcent/hyper-vyper
```

To work on the library itself, add your local copy as an editable dependency, so
your project sees each change straight away:

```bash
uv add --editable /path/to/hyper-vyper
```

### The testing extra

The `testing` extra adds `CoreSim`, a HyperCore simulator for Titanoboa tests,
and its dependencies, Titanoboa and eth-abi. Add it to your test environment
only:

```bash
uv add --dev "hyper-vyper[testing]"
```

The [testing quick start](testing/quick-start.md) walks through a complete test.

### Compiler version

The package installs exactly **Vyper 0.4.3**. Every module starts with
`# pragma version 0.4.3`, so other compiler versions refuse to compile the
modules. The library is also tested only on 0.4.3, and [security](security.md)
lists the compiler advisories for that version. Use the Cancun EVM version.

## Quick start

1. Make a new project and install the library:

    ```bash
    uv init my-contracts
    cd my-contracts
    uv add hyper-vyper
    ```

2. Save this contract as `read_core.vy`. It is the same as
   [`examples/read_core.vy`](https://github.com/crowdcent/hyper-vyper/blob/main/examples/read_core.vy).

    ```vyper
    --8<-- "examples/read_core.vy"
    ```

3. Compile the contract:

    ```bash
    uv run vyper read_core.vy -f abi,bytecode
    ```

`balance.total` is the Core **spot** USDC balance in 8-decimal units, including
funds held by open orders. It is neither the EVM token balance nor the perp
balance, and [Concepts](concepts.md) explains why that difference matters.

## Import the modules

Import the modules you need:

```vyper
from hyper_vyper import bridge
from hyper_vyper import constants
from hyper_vyper import conversions
from hyper_vyper import core_writer
from hyper_vyper import precompiles
```

- [Modules](modules/index.md) explains each module line by line.
- [Security](security.md) lists the checks your contract must add, such as
  access control and records of pending transfers.

## If your project uses Moccasin

If you build your own contracts with [Moccasin](https://cyfrin.github.io/moccasin/),
add hyper-vyper to your project with `mox install hyper-vyper`. Your contracts can
then import the modules, and your `mox test` tests can use `CoreSim`, with no
`testing` extra and no path settings. Set up two things first:

1. Moccasin installs the latest Vyper, but the library needs exactly 0.4.3, so
   install Moccasin with Vyper pinned:

    ```bash
    uv tool install moccasin==0.4.4 --with vyper==0.4.3 --with titanoboa==0.2.8
    ```

2. Add a `pytest.ini` next to `moccasin.toml`. Without it, `mox test` also
   collects test files that ship inside Vyper's dependencies in `lib/pypi`, and
   fails:

    ```ini
    [pytest]
    testpaths = tests
    ```

## Next steps

Read [concepts](concepts.md) next. The [home page](index.md#where-to-start) lists
the other pages.
