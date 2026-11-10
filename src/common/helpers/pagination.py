"""Pagination helpers."""

from __future__ import annotations

from dataclasses import dataclass

MAX_PAGE_SIZE = 100


@dataclass(frozen=True, slots=True)
class Page:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (max(self.page, 1) - 1) * self.page_size

    @property
    def limit(self) -> int:
        return min(max(self.page_size, 1), MAX_PAGE_SIZE)


def build_page(page: int, page_size: int) -> Page:
    return Page(page=max(page, 1), page_size=min(max(page_size, 1), MAX_PAGE_SIZE))
