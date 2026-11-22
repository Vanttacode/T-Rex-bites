"""Looks for new T-Rex Bites versions in the repository's GitHub Releases.

Installing them is done by /opt/trexbites/bin/trexbites-update (as root,
through trexbites-update.service); the panel only checks and starts it.
"""

import re
import time

import httpx

DEFAULT_REPO = "Vanttacode/T-Rex-bites"
CHECK_EVERY = 10 * 60


def repo_from_conf(path):
    try:
        for line in path.read_text().splitlines():
            match = re.match(r'\s*TREX_REPO="([\w.-]+/[\w.-]+)"', line)
            if match:
                return match.group(1)
    except OSError:
        pass
    return DEFAULT_REPO


def version_key(version):
    """Order versions: 0.10.0 > 0.9.0, and 1.0.0 > 1.0.0-beta."""
    main, _, pre = version.lstrip("v").partition("-")
    nums = [int(x) for x in re.findall(r"\d+", main)][:3]
    nums += [0] * (3 - len(nums))
    return nums + [0 if pre else 1, pre]


def is_newer(candidate, current):
    return version_key(candidate) > version_key(current)


class UpdateChecker:

    def __init__(self, fetch=None):
        self._fetch = fetch or self._fetch_releases
        self.latest = None       # {"tag", "name", "notes", "published"}
        self.checked_at = None
        self.error = None
        self._last_check = 0.0

    @staticmethod
    async def _fetch_releases(repo):
        url = f"https://api.github.com/repos/{repo}/releases?per_page=10"
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers={"Accept": "application/vnd.github+json"})
            resp.raise_for_status()
            return resp.json()

    async def refresh(self, repo, force=False):
        if not force and time.monotonic() - self._last_check < 30 and self.checked_at:
            return
        self._last_check = time.monotonic()
        try:
            releases = await self._fetch(repo)
        except (httpx.HTTPError, ValueError) as e:
            self.error = "No se pudo consultar GitHub. ¿La tele tiene internet?"
            return
        self.error = None
        self.checked_at = int(time.time())
        for rel in releases:
            tag = rel.get("tag_name", "")
            names = {a.get("name") for a in rel.get("assets", [])}
            # only versions published with their update package can be installed
            if rel.get("draft") or f"trexbites-update-{tag}.tar.gz" not in names:
                continue
            self.latest = {
                "tag": tag,
                "name": rel.get("name") or tag,
                "notes": (rel.get("body") or "")[:2000],
                "published": rel.get("published_at"),
            }
            return
        self.latest = None
