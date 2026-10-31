"""Check an installed repacked polars on free-threaded Python: it imports
without turning the GIL back on, and works from several threads at once.

    python smoke_test.py 1.44.2
"""

import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import polars as pl


def work(seed):
    df = pl.DataFrame({"key": [i % 7 for i in range(10_000)], "value": range(seed, seed + 10_000)})
    out = df.group_by("key").agg(pl.col("value").sum()).sort("key")
    return out["value"].to_list()


def main():
    expected_version = sys.argv[1]
    assert pl.__version__ == expected_version, f"polars {pl.__version__}, expected {expected_version}"
    assert sysconfig_gil_disabled(), "not a free-threaded Python"
    assert not sys._is_gil_enabled(), "importing polars turned the GIL back on"

    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(work, range(32)))
    assert results == [work(seed) for seed in range(32)]

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "t.parquet"
        df = pl.DataFrame({"a": [1, 2, 3], "b": ["x", "y", None]})
        df.write_parquet(path)
        assert pl.read_parquet(path).equals(df)

    assert not sys._is_gil_enabled(), "the GIL was turned back on while running"
    print(f"polars {pl.__version__} on Python {sys.version.split()[0]} free-threaded: ok")


def sysconfig_gil_disabled():
    import sysconfig
    return bool(sysconfig.get_config_var("Py_GIL_DISABLED"))


if __name__ == "__main__":
    main()
