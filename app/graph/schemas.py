from __future__ import annotations

from pydantic import BaseModel


class GraphNode(BaseModel):
    id: int | str
    title: str
    space_key: str
    slug: str | None = None
    color: str | None = None


class GraphEdge(BaseModel):
    source: int | str
    target: int | str
    type: str


class GraphPayload(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
