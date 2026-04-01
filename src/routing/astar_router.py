"""
routing/astar_router.py — A* 走廊布线器

在模块矩形之间的间隙（走廊）中用 A* 寻路。
模块矩形视为不可通行的障碍。

输出：每条网络的走线路径（坐标点列表），可直接用于 KiCad 写入走线。
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from geometry.core import Rect


@dataclass
class RoutePath:
    """单条走线路径"""
    net_name: str
    from_module: str
    to_module: str
    points: list[tuple[float, float]]  # 路径点序列 [(x,y), ...]
    length_mm: float = 0.0
    success: bool = True


@dataclass
class RouteResult:
    """布线结果"""
    routes: list[RoutePath]
    total_nets: int = 0
    routed_nets: int = 0
    failed_nets: list[str] = field(default_factory=list)
    completion_rate: float = 0.0
    total_length_mm: float = 0.0


def astar_route(
    board: Rect,
    obstacles: list[Rect],
    connections: list[tuple[str, tuple[float, float], tuple[float, float], str, str]],
    grid_size_mm: float = 0.5,
    obstacle_margin_mm: float = 0.3,
) -> RouteResult:
    """
    A* 走廊布线。

    board: 板框
    obstacles: 模块矩形列表（不可通行区域）
    connections: [(net_name, start_xy, end_xy, from_module, to_module), ...]
    grid_size_mm: 网格精度（越小越精确，越慢）
    obstacle_margin_mm: 障碍物外扩余量

    返回 RouteResult。
    """
    # 构建障碍膨胀矩形
    expanded = []
    for obs in obstacles:
        expanded.append(Rect(
            obs.x - obstacle_margin_mm,
            obs.y - obstacle_margin_mm,
            obs.w + 2 * obstacle_margin_mm,
            obs.h + 2 * obstacle_margin_mm,
        ))

    routes = []
    total = len(connections)
    routed = 0
    failed = []
    total_length = 0.0

    for net_name, start, end, from_mod, to_mod in connections:
        path = _astar_find_path(board, expanded, start, end, grid_size_mm)
        if path:
            length = _path_length(path)
            routes.append(RoutePath(
                net_name=net_name,
                from_module=from_mod,
                to_module=to_mod,
                points=path,
                length_mm=round(length, 2),
                success=True,
            ))
            routed += 1
            total_length += length
        else:
            routes.append(RoutePath(
                net_name=net_name,
                from_module=from_mod,
                to_module=to_mod,
                points=[start, end],  # 直线 fallback
                length_mm=round(math.hypot(end[0]-start[0], end[1]-start[1]), 2),
                success=False,
            ))
            failed.append(net_name)

    return RouteResult(
        routes=routes,
        total_nets=total,
        routed_nets=routed,
        failed_nets=failed,
        completion_rate=round(routed / max(total, 1) * 100, 1),
        total_length_mm=round(total_length, 2),
    )


def _astar_find_path(
    board: Rect,
    obstacles: list[Rect],
    start: tuple[float, float],
    end: tuple[float, float],
    grid: float,
) -> list[tuple[float, float]] | None:
    """A* 在网格上寻路，绕过矩形障碍"""

    def to_grid(x, y):
        return (round((x - board.x) / grid), round((y - board.y) / grid))

    def from_grid(gx, gy):
        return (board.x + gx * grid, board.y + gy * grid)

    def is_blocked(gx, gy):
        x, y = from_grid(gx, gy)
        if x < board.x or x > board.x2 or y < board.y or y > board.y2:
            return True
        for obs in obstacles:
            if obs.x <= x <= obs.x2 and obs.y <= y <= obs.y2:
                return True
        return False

    def heuristic(a, b):
        return abs(a[0] - b[0]) + abs(a[1] - b[1])  # 曼哈顿距离

    sg = to_grid(*start)
    eg = to_grid(*end)

    # 如果起点/终点在障碍内，直接跳到最近的非障碍点
    if is_blocked(*sg):
        sg = _find_nearest_free(sg, obstacles, board, grid, from_grid)
    if is_blocked(*eg):
        eg = _find_nearest_free(eg, obstacles, board, grid, from_grid)

    if sg is None or eg is None:
        return None

    # A*
    open_set = []
    heapq.heappush(open_set, (0, sg))
    came_from = {}
    g_score = {sg: 0}
    visited = set()

    # 8 方向移动
    dirs = [(1, 0), (-1, 0), (0, 1), (0, -1),
            (1, 1), (1, -1), (-1, 1), (-1, -1)]
    dir_costs = [1, 1, 1, 1, 1.414, 1.414, 1.414, 1.414]

    max_steps = int((board.w / grid) * (board.h / grid) * 0.5)  # 防死循环
    steps = 0

    while open_set and steps < max_steps:
        steps += 1
        _, current = heapq.heappop(open_set)

        if current == eg:
            # 回溯路径
            path = [from_grid(*eg)]
            node = eg
            while node in came_from:
                node = came_from[node]
                path.append(from_grid(*node))
            path.reverse()
            return _simplify_path(path)

        if current in visited:
            continue
        visited.add(current)

        for (dx, dy), cost in zip(dirs, dir_costs):
            nx, ny = current[0] + dx, current[1] + dy
            neighbor = (nx, ny)
            if is_blocked(nx, ny) or neighbor in visited:
                continue
            tentative_g = g_score[current] + cost
            if tentative_g < g_score.get(neighbor, float('inf')):
                g_score[neighbor] = tentative_g
                f = tentative_g + heuristic(neighbor, eg)
                heapq.heappush(open_set, (f, neighbor))
                came_from[neighbor] = current

    return None  # 未找到路径


def _find_nearest_free(gxy, obstacles, board, grid, from_grid_fn):
    """找到离 gxy 最近的非障碍网格点"""
    gx, gy = gxy
    for radius in range(1, 20):
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if abs(dx) != radius and abs(dy) != radius:
                    continue
                nx, ny = gx + dx, gy + dy
                x, y = from_grid_fn(nx, ny)
                if x < board.x or x > board.x2 or y < board.y or y > board.y2:
                    continue
                blocked = False
                for obs in obstacles:
                    if obs.x <= x <= obs.x2 and obs.y <= y <= obs.y2:
                        blocked = True
                        break
                if not blocked:
                    return (nx, ny)
    return None


def _simplify_path(path: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """简化路径：移除共线的中间点"""
    if len(path) <= 2:
        return path
    result = [path[0]]
    for i in range(1, len(path) - 1):
        x0, y0 = result[-1]
        x1, y1 = path[i]
        x2, y2 = path[i + 1]
        # 检查三点是否共线
        cross = (x1 - x0) * (y2 - y0) - (y1 - y0) * (x2 - x0)
        if abs(cross) > 1e-6:
            result.append(path[i])
    result.append(path[-1])
    return result


def _path_length(path: list[tuple[float, float]]) -> float:
    total = 0
    for i in range(1, len(path)):
        total += math.hypot(path[i][0] - path[i-1][0], path[i][1] - path[i-1][1])
    return total


# ---------------------------------------------------------------------------
# 便捷接口：从 BoardMap 直接布线
# ---------------------------------------------------------------------------

def route_board_map(board_map, grid_size_mm: float = 0.5) -> RouteResult:
    """
    从 BoardMap 提取障碍和连接，运行 A* 布线。
    """
    from agents.board_map import BoardMap

    obstacles = [m.rect for m in board_map.modules]
    connections = []

    for link in board_map.links:
        ma = board_map.get_module(link.from_id)
        mb = board_map.get_module(link.to_id)
        if not ma or not mb:
            continue
        start = (ma.rect.cx, ma.rect.cy)
        end = (mb.rect.cx, mb.rect.cy)
        # 每条 link 的每个 net 生成一条连接
        if link.net_names:
            for net in link.net_names:
                connections.append((net, start, end, link.from_id, link.to_id))
        else:
            connections.append((f"{link.from_id}-{link.to_id}", start, end,
                                link.from_id, link.to_id))

    return astar_route(board_map.board, obstacles, connections, grid_size_mm)
