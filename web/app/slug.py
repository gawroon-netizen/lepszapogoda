"""URL slugs for place names (SPEC §0 pt 8: slug matches [a-z0-9-]{1,80})."""

import re
import unicodedata

SLUG_RE = re.compile(r"^[a-z0-9-]{1,80}$")
_POLISH = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFKD", name.translate(_POLISH)).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:80].strip("-") or "punkt"


def is_valid(slug: str) -> bool:
    return bool(SLUG_RE.match(slug))
