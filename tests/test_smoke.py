"""Smoke test so the suite is never empty (pytest exits with code 5 when no tests run)."""


def test_src_package_imports() -> None:
    import src

    assert src is not None
