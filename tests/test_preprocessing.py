"""Tests for rhokp.preprocessing -- synonym expansion."""

from __future__ import annotations

from rhokp.preprocessing import expand_query


class TestExpandQuery:
    def test_expands_ocp(self) -> None:
        result = expand_query("install OCP 4.16")
        assert "OpenShift Container Platform" in result
        assert "OCP" in result  # original kept

    def test_expands_rhel(self) -> None:
        result = expand_query("upgrade RHEL 9")
        assert "Red Hat Enterprise Linux" in result

    def test_no_expansion_when_no_synonyms(self) -> None:
        query = "install openshift 4.16"
        assert expand_query(query) == query

    def test_multiple_expansions(self) -> None:
        result = expand_query("migrate OCP to RHEL")
        assert "OpenShift Container Platform" in result
        assert "Red Hat Enterprise Linux" in result

    def test_case_sensitive(self) -> None:
        result = expand_query("ocp lowercase")
        assert result == "ocp lowercase"

    def test_word_boundary(self) -> None:
        result = expand_query("RHELING is not RHEL")
        assert result.count("Red Hat Enterprise Linux") == 1

    def test_k8s_expansion(self) -> None:
        result = expand_query("k8s networking")
        assert "Kubernetes" in result

    def test_empty_query(self) -> None:
        assert expand_query("") == ""
