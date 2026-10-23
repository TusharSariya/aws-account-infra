"""Resolve reviewed external references to immutable catalog IDs, never display names."""

import re
from urllib.parse import urlsplit

from .api import ContractError


def normalized_alias(value):
    return " ".join(value.casefold().split())


def source_reference(url):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return None
    if parsed.hostname == "forums.iracing.com":
        match = re.match(r"/discussion/(\d+)(?:/|$)", parsed.path)
        return f"forum:{match[1]}" if match else None
    if parsed.hostname == "www.iracing.com":
        path = parsed.path.rstrip("/")
        if not path or path == "/special-events" or path.startswith("/category/"):
            return None
        return f"https://www.iracing.com{path}"
    return None


class IdentityResolver:
    def __init__(self, catalog):
        self.entries = {}
        self.aliases = {}
        self.references = {}
        for entry in catalog["events"]:
            identity = entry["id"]
            if (
                not isinstance(identity, str)
                or not identity
                or identity in self.entries
            ):
                raise ContractError(f"Invalid or duplicate catalog ID: {identity}")
            self.entries[identity] = entry
            for value in entry["aliases"]:
                alias = normalized_alias(value)
                if not alias or self.aliases.get(alias, identity) != identity:
                    raise ContractError(f"Conflicting or empty alias: {value}")
                self.aliases[alias] = identity
            for url in entry["source_urls"]:
                reference = source_reference(url)
                if reference:
                    self.references.setdefault(reference, set()).add(identity)

    def resolve(self, label, urls=(), *, phrase=False):
        text = normalized_alias(label)
        evidence = []
        for url in urls:
            reference = source_reference(url)
            for identity in sorted(self.references.get(reference, ())):
                evidence.append({"id": identity, "kind": "source", "value": reference})
        for alias, identity in self.aliases.items():
            matched = (
                re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", text)
                if phrase
                else alias == text
            )
            if matched:
                evidence.append({"id": identity, "kind": "alias", "value": alias})
        candidates = sorted({item["id"] for item in evidence})
        return {
            "id": candidates[0] if len(candidates) == 1 else None,
            "status": "resolved"
            if len(candidates) == 1
            else "ambiguous"
            if candidates
            else "unknown",
            "candidates": candidates,
            "label": label,
            "sources": sorted(set(urls)),
            "evidence": evidence,
        }
