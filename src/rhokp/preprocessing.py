"""Query preprocessing with Red Hat synonym expansion.

Expands well-known abbreviations and acronyms to their canonical product
names before the query hits Solr, improving recall for users who type
short-hand like "OCP" instead of "OpenShift Container Platform".

The synonym dictionary is intentionally small and curated. Overly broad
expansion degrades precision, so each entry should map an unambiguous
abbreviation to its official Red Hat product name.
"""

from __future__ import annotations

import re

_SYNONYMS: dict[str, str] = {
    "OCP": "OpenShift Container Platform",
    "RHEL": "Red Hat Enterprise Linux",
    "RHOSP": "Red Hat OpenStack Platform",
    "RHOAI": "Red Hat OpenShift AI",
    "RHODS": "Red Hat OpenShift Data Science",
    "RHACS": "Red Hat Advanced Cluster Security",
    "RHACM": "Red Hat Advanced Cluster Management",
    "AAP": "Ansible Automation Platform",
    "ACM": "Advanced Cluster Management",
    "ACS": "Advanced Cluster Security",
    "ARO": "Azure Red Hat OpenShift",
    "ROSA": "Red Hat OpenShift Service on AWS",
    "ODF": "OpenShift Data Foundation",
    "OVN": "Open Virtual Networking",
    "SDN": "Software Defined Networking",
    "CNV": "OpenShift Virtualization",
    "k8s": "Kubernetes",
    "OOM": "Out of Memory",
    "SELinux": "Security-Enhanced Linux",
    "RBAC": "role-based access control",
    "CRI-O": "CRI-O container runtime",
    "FIPS": "Federal Information Processing Standards",
    "LDAP": "Lightweight Directory Access Protocol",
    "IdM": "Identity Management",
    "IPA": "Identity Policy Audit",
    "EUS": "Extended Update Support",
    "E4S": "Update Services for SAP Solutions",
    "TUS": "Telecommunications Update Service",
}

_WORD_BOUNDARY = re.compile(r"\b(" + "|".join(re.escape(k) for k in _SYNONYMS) + r")\b")


def expand_query(query: str) -> str:
    """Expand known Red Hat abbreviations in *query* to their full names.

    Replacement is case-sensitive and only matches whole words.
    The original abbreviation is kept alongside the expansion so that
    exact-match boosts in Solr still fire::

        >>> expand_query("install OCP 4.16")
        'install OCP (OpenShift Container Platform) 4.16'
    """
    return _WORD_BOUNDARY.sub(lambda m: f"{m.group(0)} ({_SYNONYMS[m.group(0)]})", query)
