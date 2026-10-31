# jmod-polars-mirror

Free-threaded (`cp314t`) wheels of `polars-runtime-32`, for running
[JMod](https://github.com/ParallelSquared/JMod) on free-threaded Python 3.14.

## Why

PyPI has no free-threaded `polars-runtime-32` wheels, and polars does not plan
any before Python 3.15 (pola-rs/polars#27955, #28068). conda-forge builds them.
`repack.py` takes conda-forge's `cp314t` builds and repacks them as wheels that
uv can install. The compiled extension is byte-identical to conda-forge's.
The `polars` package itself is pure Python and still comes from PyPI.

## Platforms

These are the platforms that both peppy_sage and conda-forge build for:

| conda-forge subdir | wheel platform tag |
|---|---|
| linux-64 | `manylinux_2_17_x86_64.manylinux2014_x86_64` |
| linux-aarch64 | `manylinux_2_17_aarch64.manylinux2014_aarch64` |
| osx-64 | `macosx_11_0_x86_64` |
| osx-arm64 | `macosx_11_0_arm64` |
| win-64 | `win_amd64` |

The builds link only system libraries. On Linux that is glibc 2.17 and
libgcc_s. On Windows it is `VCRUNTIME140`, which CPython ships. `repack.py`
stops if a build declares a newer glibc or macOS than its tag claims.

## Publishing a new polars version

1. Check that conda-forge has `cp314t` builds of the version for every subdir
   above. `repack.py` stops and names any that are missing.
2. Put the version in `POLARS_VERSION` and push to `main`. The **Release**
   workflow repacks the wheels, then tests each one on its own platform:
   `smoke_test.py` in free-threaded Python, plus `auditwheel show` on Linux.
   If every test passes and `v<version>` is not released yet, it publishes
   the wheels and a `SHA256SUMS` file as release `v<version>`, tagging the
   pushed commit. An existing release is never replaced. Pull requests build
   and test without releasing.
3. In JMod's `pyproject.toml`, bump `polars` and `polars-runtime-32` together to
   the new version, update the wheel URLs under `[tool.uv.sources]`, and run
   `uv lock`. `polars` requires `polars-runtime-32` at its own exact version.

To build locally (Python 3.14+, standard library only):

    python repack.py $(cat POLARS_VERSION)          # wheels into dist/

## License

polars is MIT-licensed. Each wheel carries polars' `LICENSE` and SBOM in its
`.dist-info`, unchanged from conda-forge's package.
