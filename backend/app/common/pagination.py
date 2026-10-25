"""Paginación en servidor (regla REP): la grilla nunca recibe la tabla entera."""

from typing import Annotated

from fastapi import Depends, Query
from pydantic import BaseModel


class PageParams(BaseModel):
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def _page_params(
    page: Annotated[int, Query(ge=1, description="Página, desde 1")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="Filas por página")] = 25,
) -> PageParams:
    return PageParams(page=page, page_size=page_size)


PageParamsDep = Annotated[PageParams, Depends(_page_params)]


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int
