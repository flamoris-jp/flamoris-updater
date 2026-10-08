from collections import deque

from .errors import UpdateError
from .models import Manifest


def route(manifest: Manifest, observed: dict[str, str]) -> list[str]:
    if set(observed) != set(manifest.schema_targets):
        raise UpdateError("unsupported_migration", "Resource schema vector is incomplete")

    def key(v):
        return tuple(sorted(v.items()))

    start, target = key(observed), key(manifest.schema_targets)
    edges = manifest.migrations
    # Explore the reachable vector graph, retaining all shortest alternatives.
    adjacency = {}
    queue = deque([start])
    visited = {start}
    while queue:
        node = queue.popleft()
        current = dict(node)
        eligible = []
        for edge in edges:
            if all(current.get(k) == v for k, v in {**edge.source, **edge.requires}.items()):
                result = {**current, **edge.to}
                nxt = key(result)
                eligible.append((nxt, edge.id))
                if nxt not in visited:
                    if len(visited) >= 4096:
                        raise UpdateError("unsupported_migration", "Schema graph exceeds budget")
                    visited.add(nxt)
                    queue.append(nxt)
        adjacency[node] = eligible
    colors = {}

    def acyclic(node):
        if colors.get(node) == 1:
            raise UpdateError("unsupported_migration", "Cyclic schema graph")
        if colors.get(node) == 2:
            return
        colors[node] = 1
        for nxt, _ in adjacency[node]:
            acyclic(nxt)
        colors[node] = 2

    try:
        acyclic(start)
    except RecursionError:
        raise UpdateError("unsupported_migration", "Schema graph depth exceeds budget") from None
    if start == target:
        return []
    distances = {start: 0}
    paths = {start: [[]]}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        for nxt, edge in adjacency[node]:
            distance = distances[node] + 1
            if nxt not in distances:
                distances[nxt] = distance
                paths[nxt] = []
                queue.append(nxt)
            if distances[nxt] == distance:
                paths[nxt] = (paths[nxt] + [p + [edge] for p in paths[node]])[:2]
    candidates = paths.get(target, [])
    if not candidates:
        raise UpdateError("unsupported_migration")
    preferred = [p.edges for p in manifest.preferred_routes if p.source == observed]
    if len(preferred) > 1:
        raise UpdateError("ambiguous_migration_path")
    if preferred:
        current = start
        for identity in preferred[0]:
            next_nodes = [n for n, e in adjacency[current] if e == identity]
            if len(next_nodes) != 1:
                raise UpdateError("unsupported_migration", "Invalid preferred route")
            current = next_nodes[0]
        if current != target:
            raise UpdateError("unsupported_migration")
        return preferred[0]
    if len(candidates) != 1:
        raise UpdateError("ambiguous_migration_path")
    return candidates[0]


def ordered(dependencies: dict[str, set[str]]) -> list[str]:
    pending = {k: set(v) for k, v in dependencies.items()}
    if any(not v <= set(pending) for v in pending.values()):
        raise UpdateError("incompatible_dependency")
    result = []
    while pending:
        ready = sorted(k for k, v in pending.items() if not v)
        if not ready:
            raise UpdateError(
                "incompatible_dependency", "Cycles need an owner-validated group contract"
            )
        for item in ready:
            result.append(item)
            del pending[item]
        for remaining in pending.values():
            remaining.difference_update(ready)
    return result
