"""Route discovery between X and the existing publisher sources."""

from . import xsource
from .references import ReferenceClient
from .xsource import XReferenceClient


class DiscoveryRouter:
    """Share one search/page budget while changing routes only when needed."""

    def __init__(self, config, sources):
        self.config = config
        self.publishers = ReferenceClient(config, sources)
        self.x = XReferenceClient(config) if xsource.X_ENABLED else None
        self.routes = {"publisher": self.publishers}
        if self.x is not None:
            self.routes["x"] = self.x
            self.order = ["x", "publisher"]
        else:
            self.order = ["publisher"]
        self.cursor = 0
        self.searches = []
        self.page_priorities = {}

    @property
    def calls(self) -> int:
        """Count Tavily calls across every route."""
        return self.publishers.calls + (self.x.calls if self.x else 0)

    @property
    def pages(self) -> int:
        """Count resolved work pages across every route."""
        return self.publishers.pages + (self.x.pages if self.x else 0)

    def _next_route(self) -> str:
        if self.cursor < len(self.order):
            name = self.order[self.cursor]
            self.cursor += 1
            return name
        return self.order[-1]

    async def search(self, query: str, *, sources=None):
        """Run one search on the next route and return (page, route) pairs."""
        if self.calls >= self.config.limits.search_budget:
            return []
        name = self._next_route()
        route = self.routes[name]
        before = len(route.searches)
        try:
            if name == "publisher":
                pages = await route.search(query, sources=sources)
            else:
                pages = await route.search(query)
        finally:
            if len(route.searches) > before:
                trace = route.searches[-1]
                trace.setdefault("route", name)
                self.searches.append(trace)
            self.page_priorities.update(route.page_priorities)
        return [(page, name) for page in pages]

    async def candidate(self, page_url: str, number: int, route_name: str):
        """Resolve a page through the same route that discovered it."""
        route = self.routes.get(route_name)
        if route is None:
            raise KeyError(route_name)
        return await route.candidate(page_url, number)
