"""robots.txt checks that fail closed and are cached per host for a day."""
from __future__ import annotations

import time
import urllib.robotparser
from typing import Callable
from urllib.parse import urlsplit

Fetch = Callable[[str], str]


class RobotsPolicy:
    def __init__(self, user_agent: str, fetch: Fetch, ttl_seconds: float = 86_400,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.user_agent = user_agent
        self._fetch = fetch
        self._ttl = ttl_seconds
        self._clock = clock
        self._cache: dict[str, tuple[float, urllib.robotparser.RobotFileParser | None]] = {}

    def _parser(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        parts = urlsplit(url)
        if parts.scheme != 'https' or not parts.netloc:
            return None
        host = f'{parts.scheme}://{parts.netloc}'
        cached = self._cache.get(host)
        if cached and self._clock() - cached[0] < self._ttl:
            return cached[1]
        parser: urllib.robotparser.RobotFileParser | None
        try:
            parser = urllib.robotparser.RobotFileParser()
            parser.parse(self._fetch(host + '/robots.txt').splitlines())
        except Exception:
            parser = None   # unreachable or malformed robots.txt: do not crawl
        self._cache[host] = (self._clock(), parser)
        return parser

    def allowed(self, url: str) -> bool:
        parser = self._parser(url)
        return bool(parser and parser.can_fetch(self.user_agent, url))

    def crawl_delay(self, url: str) -> float | None:
        parser = self._parser(url)
        if parser is None:
            return None
        delay = parser.crawl_delay(self.user_agent)
        return float(delay) if delay is not None else None
