"""
Pytest configuration and shared fixtures.

Skips LangChain retriever tests when langchain-core is not installed
so the default CI matrix can still run core tests.
"""

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "langchain: tests that require rhokp[langchain] (langchain-core).",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list) -> None:
    try:
        import langchain_core  # noqa: F401

        has_langchain = True
    except ImportError:
        has_langchain = False

    for item in items:
        path = str(getattr(item, "path", None) or getattr(item, "fspath", None) or "")
        if "test_retrievers" in path:
            if not has_langchain:
                item.add_marker(
                    pytest.mark.skip(
                        reason="langchain-core not installed; pip install rhokp[langchain,dev]"
                    )
                )
            else:
                item.add_marker(pytest.mark.langchain)
