"""Офлайн-препроцессинг: морские клетки (см. АРХИТЕКТУРА_МОРСКИХ_КЛЕТОК.md).

Шаг 1 из плана в этом документе — только геометрия + соседство, без типов
воды/глубин/ресурсов (добавляются позже без переделки геометрии, см. §13
документа).

Источник суши — assets/provinces.json (build_provinces.py, слой "Области",
клавиша 8), по явному решению пользователя (не land_sea.json, как было
раньше). ВАЖНО: provinces.json НЕ включает мелкие острова — там порог
отсечения ISLAND_DROP_KM2=300 км² (мягче, 100 км², для Карибов/Мальдив),
тогда как land_sea.json учитывает острова от 1 км². Значит для генератора
морских клеток мелкие острова физически не существуют — море может лечь
поверх них. Формат тот же ({"world_px":...,"cells":[{"rings":...}]}),
взаимозаменяемо с land_sea.json без изменений кода загрузки.

Пайплайн (см. §0 документа):
  land_sea.json -> водная маска -> адаптивные seed-точки (гуще у берега,
  реже в открытом море, плавный рост, см. §6) -> Voronoi -> обрезка по воде
  -> чистка геометрии (мелкие куски сливаются с соседом) -> граф соседства
  -> assets/generated/sea_cells.json + assets/generated/sea_cell_graph.json

Плотность seed-точек ищется через квадродерево (а не готовый Poisson-disk
пакет, которого нет в зависимостях проекта): блок квадродерева делится на 4,
пока его физический размер (км, с поправкой на cos(lat) для Mercator)
больше локального целевого размера клетки; целевой размер и "есть ли тут
вообще море" читаются из растровой маски (PIL rasterize + scipy
distance_transform_edt на расстояние до берега) — задача сведена к тому же
классу, что и растровые проверки в build_land_sea.py, но с шагом растра
покрупнее (тут не нужна точность контура, только плотность точек).

neighbor_land_ids из документа (§12.2) НЕ заполняем: в проекте пока нет
слоя клеток СУШИ со стабильными id (слой "8" — провинции, это
административные единицы, не игровые клетки, см. TODO.md) — заполнить
честным списком id нечем. Вместо этого — простой boolean "coast" (клетка
касается берега или нет), список id проставим отдельным шагом, когда
появится сам слой клеток суши.

Не запускается в Godot — отдельный шаг подготовки данных.
"""
import json
import math
import random
import time

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from scipy.spatial import Voronoi
from shapely.geometry import Polygon, MultiPolygon, LineString, MultiLineString, box, Point
from shapely.ops import unary_union
from shapely.strtree import STRtree

LAND_SRC = "assets/provinces.json"
OUT_CELLS = "assets/generated/sea_cells.json"
OUT_GRAPH = "assets/generated/sea_cell_graph.json"

WORLD_PX = 8192.0
R_KM = 6371.0

# Те же полярные пороги, что у build_land_sea.py/build_continents.py и др.
LAT_NORTH = 76.0
LAT_SOUTH = -58.0

RASTER_PX = 4096  # world_px 8192 -> raster 4096, 2 мировых px на растровый px
SCALE = WORLD_PX / RASTER_PX

# Квадродерево seed-точек: от MAX (открытый океан) до MIN (у самого берега).
MAX_QUAD_PX = 512.0
MIN_QUAD_PX = 16.0

# Целевой размер клетки (км) от расстояния до берега (км) — плавная кривая
# по точкам, заданным пользователем: 0->100, 100->200, 300->300, 500->400.
# За пределами последней точки (500 км) размер дальше не растёт — 400 км
# потолок для открытого океана.
SIZE_DIST_KM = [0.0, 100.0, 300.0, 500.0]
SIZE_TARGET_KM = [100.0, 200.0, 300.0, 400.0]

# Порог "слишком мелкая клетка -> присоединить к соседу" (§9): доля от
# ЛОКАЛЬНОЙ целевой площади (target_size_km в точке центра клетки в квадрат).
MIN_AREA_RATIO = 0.25
# Совсем крошечные обрезки (артефакты клипа) выбрасываем без объединения.
MIN_ABSOLUTE_AREA_KM2 = 3.0

# Порог "касаются только точкой -> не соседи" (§12.1), мировые px.
MIN_SHARED_BORDER_PX = 0.4

# Берег vs sea-sea граница (§10): "береговой" разрез — это буквально кусок
# контура суши, скопированный операцией difference() при обрезке клетки, то
# есть совпадает с ним почти до пикселя. Порог должен быть ТУГИМ (как
# BOUNDARY_TOL=0.05 у build_cells_test.py, где источник геометрии похожий),
# иначе волнистые (после _wavify_polygon) sea-sea рёбра, которые у берега
# случайно проходят близко к суше, ошибочно принимаются за побережье и
# режут открытую цепочку раньше, чем она реально доходит до берега (баг,
# найден по скриншоту — "контуры не достигают суши" при старом пороге 1.2).
COAST_EPS_PX = 0.1
# Радиус поиска БЛИЗКИХ кусков суши через STRtree (мировые px) — отдельно от
# порога классификации выше: нужен запас, чтобы не пропустить сушу, которая
# рядом, но чуть дальше чем ожидаемая точность разреза.
COAST_PROBE_PX = 20.0

MAX_MERGE_PASSES = 12


def project(lon: float, lat: float) -> tuple:
    lat = max(-85.05112878, min(85.05112878, lat))
    x = (lon + 180.0) / 360.0 * WORLD_PX
    lat_rad = math.radians(lat)
    y = (0.5 - math.log(math.tan(math.pi / 4 + lat_rad / 2)) / (2 * math.pi)) * WORLD_PX
    return x, y


def unproject_lat(y: float) -> float:
    n = math.pi - 2.0 * math.pi * y / WORLD_PX
    return math.degrees(math.atan(math.sinh(n)))


def km_per_world_px(y: float) -> float:
    """Локальный масштаб (км на 1 мировой px) в точке с мировой y-координатой
    — Mercator растягивает x/y одинаково (конформная проекция), масштаб
    зависит только от широты через cos(lat)."""
    lat = unproject_lat(y)
    return (2.0 * math.pi * R_KM / WORLD_PX) * math.cos(math.radians(lat))


def target_size_km(dist_km: float) -> float:
    return float(np.interp(dist_km, SIZE_DIST_KM, SIZE_TARGET_KM))


def _explode(geom) -> list:
    if geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return list(geom.geoms)
    if geom.geom_type == "GeometryCollection":
        out = []
        for g in geom.geoms:
            out.extend(_explode(g))
        return out
    return []


def load_land_pieces() -> list:
    """НЕ склеенные куски суши (по одному на исходную запись JSON, до
    unary_union) — специально НЕ объединяем соседние провинции здесь.

    ВАЖНО (найдено при первом прогоне на весь мир — 5+ минут зависания на
    clip_and_explode без единого прогресс-принта, хотя локальный STRtree по
    идее должен быть быстрым): unary_union() соседних провинций Евразии
    склеивает их в ОДИН полигон на 28216 точек с bbox почти во весь мир.
    После этого STRtree перестаёт быть локальным — для любой морской клетки
    рядом с Евразией индекс находит именно этот гигантский кусок, и
    difference() считается против него целиком, тот же квадратичный по
    стоимости баг, что был раньше с sea_mask, просто с другой стороны.
    Держим куски НЕ склеенными (провинция размером с область/штат — bbox
    на порядки меньше континента) — STRtree тогда реально локален.

    GAP_FIX_PX: соседние провинции в provinces.json не всегда идеально
    стыкуются (обычное дело для реальных административных векторных
    данных, в отличие от land_sea.json — единой склеенной маски без швов).
    Найдено на побережье Франции/Испании: сотни "морских" клеток площадью
    1-2 км² с нулём соседей — это микро-щели МЕЖДУ провинциями, которые
    generate_sea_cells.py принимает за море. Небольшой буфер на каждый
    кусок ДО того, как куски используются для вычитания, закрывает щели
    без склейки в один гигантский полигон (буфер применяется к каждому
    куску отдельно, они остаются раздельными записями для STRtree)."""
    GAP_FIX_PX = 0.5
    data = json.load(open(LAND_SRC, encoding="utf-8"))
    polys = []
    for c in data["cells"]:
        rings = c["rings"]
        if len(rings[0]) < 3:
            continue
        try:
            p = Polygon(rings[0], rings[1:])
            if not p.is_valid:
                p = p.buffer(0)
            p = p.buffer(GAP_FIX_PX)
            for part in _explode(p):
                if not part.is_empty:
                    polys.append(part)
        except Exception:
            continue
    return polys


def rasterize_land(land_union) -> np.ndarray:
    """True = суша, на растре RASTER_PX x RASTER_PX (мировые px / SCALE)."""
    img = Image.new("L", (RASTER_PX, RASTER_PX), 0)
    draw = ImageDraw.Draw(img)
    for piece in _explode(land_union):
        ext = [(x / SCALE, y / SCALE) for x, y in piece.exterior.coords]
        if len(ext) >= 3:
            draw.polygon(ext, fill=255)
        for hole in piece.interiors:
            hole_pts = [(x / SCALE, y / SCALE) for x, y in hole.coords]
            if len(hole_pts) >= 3:
                draw.polygon(hole_pts, fill=0)
    arr = np.array(img) > 127

    # Полосы вне разрешённых широт (Антарктида/Крайний Север) считаем "сушей"
    # для целей маски — там просто не должно быть seed-точек, а не потому что
    # это физически суша.
    north_y, _ = project(0.0, LAT_NORTH)
    south_y, _ = project(0.0, LAT_SOUTH)
    north_row = int(project(0.0, LAT_NORTH)[1] / SCALE)
    south_row = int(project(0.0, LAT_SOUTH)[1] / SCALE)
    arr[:max(0, north_row), :] = True
    arr[min(RASTER_PX, south_row):, :] = True
    return arr, (project(0.0, LAT_NORTH)[1], project(0.0, LAT_SOUTH)[1])


def build_target_km_grid(land_arr: np.ndarray) -> np.ndarray:
    """dist_km[row,col] = расстояние (км) до ближайшей суши, потом переводим
    в целевой размер клетки (км) через target_size_km."""
    sea_bool = ~land_arr
    dist_px = ndimage.distance_transform_edt(sea_bool)  # растровые px
    rows = np.arange(RASTER_PX)
    world_y = rows * SCALE
    kmpx_row = np.array([km_per_world_px(y) * SCALE for y in world_y])  # км на растровый px, по строке
    dist_km = dist_px * kmpx_row[:, None]
    target_km = np.interp(dist_km, SIZE_DIST_KM, SIZE_TARGET_KM)
    return target_km, kmpx_row


def generate_seeds(land_arr: np.ndarray, target_km_grid: np.ndarray, bbox: tuple, rng: random.Random) -> list:
    west_x, north_y, east_x, south_y = bbox
    sea_i32 = (~land_arr).astype(np.int32)
    # Интегральное изображение (с нулевой рамкой сверху/слева) для O(1)
    # запроса "есть ли море в прямоугольнике [r0:r1, c0:c1]".
    cum = np.zeros((RASTER_PX + 1, RASTER_PX + 1), dtype=np.int64)
    cum[1:, 1:] = np.cumsum(np.cumsum(sea_i32, axis=0), axis=1)

    def sea_count(c0, r0, c1, r1) -> int:
        c0 = max(0, c0); r0 = max(0, r0)
        c1 = min(RASTER_PX, c1); r1 = min(RASTER_PX, r1)
        if c1 <= c0 or r1 <= r0:
            return 0
        return int(cum[r1, c1] - cum[r0, c1] - cum[r1, c0] + cum[r0, c0])

    def target_at(x, y) -> float:
        col = min(RASTER_PX - 1, max(0, int(x / SCALE)))
        row = min(RASTER_PX - 1, max(0, int(y / SCALE)))
        return float(target_km_grid[row, col])

    seeds = []

    def recurse(x0, y0, size):
        x1, y1 = x0 + size, y0 + size
        c0, r0 = int(x0 / SCALE), int(y0 / SCALE)
        c1, r1 = int(x1 / SCALE), int(y1 / SCALE)
        if sea_count(c0, r0, c1, r1) == 0:
            return
        cx, cy = x0 + size / 2.0, y0 + size / 2.0
        target = min(target_at(x0, y0), target_at(x1, y0), target_at(x0, y1),
                     target_at(x1, y1), target_at(cx, cy))
        block_km = size * km_per_world_px(cy)
        if block_km > target * 1.4 and size > MIN_QUAD_PX:
            half = size / 2.0
            recurse(x0, y0, half)
            recurse(x0 + half, y0, half)
            recurse(x0, y0 + half, half)
            recurse(x0 + half, y0 + half, half)
            return
        jitter = size * 0.35
        for _ in range(6):
            px = cx + rng.uniform(-jitter, jitter)
            py = cy + rng.uniform(-jitter, jitter)
            col, row = int(px / SCALE), int(py / SCALE)
            if 0 <= row < RASTER_PX and 0 <= col < RASTER_PX and not land_arr[row, col]:
                seeds.append((px, py))
                return
        col, row = int(cx / SCALE), int(cy / SCALE)
        if 0 <= row < RASTER_PX and 0 <= col < RASTER_PX and not land_arr[row, col]:
            seeds.append((cx, cy))

    x = west_x
    while x < east_x:
        y = north_y
        while y < south_y:
            recurse(x, y, MAX_QUAD_PX)
            y += MAX_QUAD_PX
        x += MAX_QUAD_PX
    return seeds


def build_voronoi_polygons(seeds: list) -> list:
    """scipy Voronoi + большие точки-обрамление, чтобы все реальные регионы
    были ограничены (без -1 индексов), см. §7 документа. Возвращает список
    (seed_idx, shapely Polygon) для всех РЕАЛЬНЫХ (не обрамляющих) точек."""
    n_real = len(seeds)
    cx, cy = WORLD_PX / 2.0, WORLD_PX / 2.0
    pad_r = WORLD_PX * 3.0
    pad_points = []
    for i in range(24):
        ang = 2.0 * math.pi * i / 24
        pad_points.append((cx + pad_r * math.cos(ang), cy + pad_r * math.sin(ang)))

    points = np.array(seeds + pad_points)
    vor = Voronoi(points)

    out = []
    for i in range(n_real):
        region_idx = vor.point_region[i]
        region = vor.regions[region_idx]
        if not region or -1 in region:
            continue
        verts = [vor.vertices[v] for v in region]
        if len(verts) < 3:
            continue
        try:
            poly = Polygon(verts)
            if not poly.is_valid:
                poly = poly.buffer(0)
            if poly.is_empty:
                continue
            out.append((i, poly))
        except Exception:
            continue
    return out


def clip_and_explode(voronoi_polys: list, land_pieces: list, land_tree: STRtree, crop_box) -> list:
    """[(seed_idx, geom)] -> клетки, обрезанные по морю, MultiPolygon
    разбираем на отдельные куски (§9, п.4).

    ВАЖНО (найдено при первом прогоне — 10+ минут без результата): пересекать
    каждую из десятков тысяч Voronoi-клеток с ОДНИМ гигантским sea_mask
    (весь мир минус вся суша, десятки тысяч точек контура из-за Евразии) —
    квадратичная по стоимости операция, GEOS не индексирует это само по
    себе. Вместо этого через STRtree берём только БЛИЗКИЕ куски суши для
    каждой клетки (обычно 0-3 полигона) и вычитаем только их — на порядки
    дешевле."""
    pieces = []
    for n, (seed_idx, poly) in enumerate(voronoi_polys):
        clipped = poly.intersection(crop_box)
        if clipped.is_empty:
            continue
        cand_idx = land_tree.query(clipped)
        if len(cand_idx) > 0:
            local_land = unary_union([land_pieces[int(ci)] for ci in cand_idx])
            clipped = clipped.difference(local_land)
        if clipped.is_empty:
            continue
        for part in _explode(clipped):
            if part.is_empty or part.area < 0.01:
                continue
            pieces.append({"seed_idx": seed_idx, "geom": part})
        if (n + 1) % 5000 == 0:
            print(f"    clip_and_explode: {n + 1}/{len(voronoi_polys)}", flush=True)
    return pieces


def area_km2_world_px(geom, kmpx_row_lookup) -> float:
    """Площадь через локальный масштаб км/px в центроиде — Mercator
    искажает площадь по широте, но для клеток скромного размера (десятки-
    сотни км) погрешность от использования ОДНОГО масштаба на клетку мала."""
    c = geom.centroid
    kmpx = km_per_world_px(c.y)
    return geom.area * kmpx * kmpx


def merge_small_pieces(pieces: list, target_km_grid: np.ndarray) -> list:
    """Клетка меньше MIN_AREA_RATIO от локальной целевой площади (или меньше
    MIN_ABSOLUTE_AREA_KM2) присоединяется к соседу с самой длинной общей
    границей — то же правило, что build_provinces.py._merge_small_pieces,
    но критерий мелкости — не тип из датасета, а сравнение с локальным
    таргетом плотности (§9 документа: "< 25% от целевой площади зоны")."""

    def target_area_km2(geom) -> float:
        c = geom.centroid
        col = min(RASTER_PX - 1, max(0, int(c.x / SCALE)))
        row = min(RASTER_PX - 1, max(0, int(c.y / SCALE)))
        t = float(target_km_grid[row, col])
        return t * t

    cluster = {i: p["geom"] for i, p in enumerate(pieces)}

    for _pass in range(MAX_MERGE_PASSES):
        ids = list(cluster.keys())
        buffered = [cluster[i].buffer(0.5) for i in ids]
        tree = STRtree(buffered)
        any_merge = False

        for pos, i in enumerate(ids):
            if i not in cluster:
                continue
            area = area_km2_world_px(cluster[i], None)
            too_small = area < MIN_ABSOLUTE_AREA_KM2 or area < MIN_AREA_RATIO * target_area_km2(cluster[i])
            if not too_small:
                continue
            cand_idx = tree.query(buffered[pos])
            best_j, best_len = None, 0.0
            for ci in cand_idx:
                j = ids[int(ci)]
                if j == i or j not in cluster:
                    continue
                shared = buffered[pos].intersection(cluster[j].buffer(0.5))
                length = getattr(shared, "length", 0.0)
                if length > best_len:
                    best_len, best_j = length, j
            if best_j is not None and best_len > MIN_SHARED_BORDER_PX:
                merged = unary_union([cluster[best_j], cluster[i]])
                if not merged.is_valid:
                    merged = merged.buffer(0)
                cluster[best_j] = merged
                del cluster[i]
                any_merge = True

        print(f"  merge pass {_pass + 1}: {len(ids)} -> {len(cluster)} pieces", flush=True)
        if not any_merge:
            break

    out = []
    for geom in cluster.values():
        for part in _explode(geom):
            if not part.is_empty and part.area > 0.001:
                out.append({"geom": part})
    return out


def compute_brd_open(ring_coords: list, land_pieces: list, land_tree: STRtree) -> tuple:
    """Разбивает замкнутое кольцо клетки на открытые цепочки — только рёбра,
    НЕ лежащие на береговой линии (та уже рисуется слоем "Суша/Море", см.
    §10 документа и build_cells_test.py._split_open_border_chains — тот же
    приём, порог COAST_EPS_PX вместо BOUNDARY_TOL из-за другого источника
    геометрии). Возвращает (chains, coast: bool).

    ВАЖНО: как и clip_and_explode — считать distance() до ГЛОБАЛЬНОГО
    land_union.boundary на каждое ребро каждой клетки было второй причиной
    зависания первого прогона. Берём только близкие куски суши через
    STRtree по bbox кольца."""
    n = len(ring_coords) - 1
    if n < 2:
        return [], False

    xs = [p[0] for p in ring_coords]
    ys = [p[1] for p in ring_coords]
    probe = box(min(xs) - COAST_PROBE_PX, min(ys) - COAST_PROBE_PX,
                max(xs) + COAST_PROBE_PX, max(ys) + COAST_PROBE_PX)
    cand_idx = land_tree.query(probe)
    if len(cand_idx) == 0:
        return [ring_coords[:]], False

    local_boundary = unary_union([land_pieces[int(ci)] for ci in cand_idx]).boundary

    is_open = []
    for i in range(n):
        a, b = ring_coords[i], ring_coords[i + 1]
        mx, my = (a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5
        is_open.append(local_boundary.distance(Point(mx, my)) > COAST_EPS_PX)
    coast = not all(is_open)

    if all(is_open):
        return [ring_coords[:]], coast
    if not any(is_open):
        return [], coast

    start = next(i for i in range(n) if is_open[i] and not is_open[i - 1])
    chains, chain = [], []
    for k in range(n):
        i = (start + k) % n
        if is_open[i]:
            if not chain:
                chain = [ring_coords[i]]
            chain.append(ring_coords[(i + 1) % n])
        else:
            if len(chain) >= 2:
                chains.append(chain)
            chain = []
    if len(chain) >= 2:
        chains.append(chain)
    return chains, coast


# Клетки суши со статусом "потенциальный центр провинции"
# (province_center_status, см. scripts/data/Cell.gd/build_cells_test.py) —
# морская клетка(и), касающиеся её берега, ДОЛЖНЫ слиться в одну, чтобы одна
# морская клетка полностью "обваливала" столичную клетку целиком (запрос
# пользователя после проверки волнистых границ). Это ТЕСТОВАЯ связка с
# cells_test.json (единственный сейчас источник province_center_status) —
# когда появится полноценный слой клеток суши (см. TODO.md), эта функция
# должна брать капитальные клетки оттуда, а не из тестового файла.
CELLS_TEST_SRC = "assets/cells_test.json"
CAPITAL_TOUCH_PX = 0.5  # допуск "касается берега капитальной клетки"


def load_capital_land_polys() -> list:
    import os
    if not os.path.exists(CELLS_TEST_SRC):
        return []
    data = json.load(open(CELLS_TEST_SRC, encoding="utf-8"))
    polys = []
    for c in data["cells"]:
        if c.get("province_center_status", "") == "":
            continue
        rings = c["rings"]
        try:
            p = Polygon(rings[0], rings[1:])
            if not p.is_valid:
                p = p.buffer(0)
            if not p.is_empty:
                polys.append(p)
        except Exception:
            continue
    return polys


def merge_capital_coastal_cells(pieces: list, capital_polys: list) -> list:
    """Для каждой капитальной клетки суши сливает ВСЕ морские клетки,
    касающиеся её берега, в одну — иначе внутреннее sea-sea ребро может
    случайно пройти прямо вдоль её побережья, разрезая "её" море на куски
    разных соседей (см. скриншот пользователя)."""
    if not capital_polys:
        return pieces
    cluster = {i: p["geom"] for i, p in enumerate(pieces)}
    for cap_poly in capital_polys:
        touch_zone = cap_poly.buffer(CAPITAL_TOUCH_PX)
        touching = [i for i, g in cluster.items() if g.intersects(touch_zone)]
        if len(touching) <= 1:
            continue
        merged = unary_union([cluster[i] for i in touching])
        if not merged.is_valid:
            merged = merged.buffer(0)
        keep = touching[0]
        cluster[keep] = merged
        for i in touching[1:]:
            del cluster[i]
        print(f"  merged {len(touching)} sea cells around capital cell "
              f"(bbox {cap_poly.bounds})", flush=True)
    out = []
    for geom in cluster.values():
        for part in _explode(geom):
            if not part.is_empty and part.area > 0.001:
                out.append({"geom": part})
    return out


# Тестовый регион по умолчанию (см. done.md/TODO.md — тот же принцип, что
# cells_test.json: сначала проверить подход на одной небольшой, но реально
# сложной по берегу области, прежде чем гонять на весь мир). Ла-Корунья +
# вход в Бискайский залив — достаточно изрезанный берег (фьорды/эстуарии
# Галисии), чтобы проверить и прибрежную плотность, и brd_open, и merge
# мелких кусков. Полный мир — флагом --full.
#
# Расширено до побережий Франции и Испании целиком (по просьбе пользователя
# — промежуточный шаг перед полным миром: Атлантика, Бискайский залив,
# Ла-Манш, испанское и французское Средиземноморье).
TEST_REGION_LONLAT = (-10.0, 35.0, 8.5, 51.5)


def region_bbox_world_px(lonlat_box: tuple) -> tuple:
    lon0, lat0, lon1, lat1 = lonlat_box
    x0, y0 = project(lon0, lat1)
    x1, y1 = project(lon1, lat0)
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def main() -> None:
    import sys
    t0 = time.time()
    rng = random.Random(20260709)
    full_world = "--full" in sys.argv

    land_pieces = load_land_pieces()
    land_union = unary_union(land_pieces)  # только для растровой маски/дистанс-трансформа
    print(f"[{time.time() - t0:.1f}s] land_pieces loaded ({len(land_pieces)}), union built", flush=True)

    land_arr, y_bounds = rasterize_land(land_union)
    print(f"[{time.time() - t0:.1f}s] land rasterized {RASTER_PX}x{RASTER_PX}", flush=True)

    target_km_grid, _kmpx_row = build_target_km_grid(land_arr)
    print(f"[{time.time() - t0:.1f}s] distance-to-land raster built", flush=True)

    if full_world:
        bx0, by0, bx1, by1 = 0.0, y_bounds[0], WORLD_PX, y_bounds[1]
        print(f"[{time.time() - t0:.1f}s] MODE: FULL WORLD", flush=True)
    else:
        rx0, ry0, rx1, ry1 = region_bbox_world_px(TEST_REGION_LONLAT)
        bx0, by0 = max(rx0, 0.0), max(ry0, y_bounds[0])
        bx1, by1 = min(rx1, WORLD_PX), min(ry1, y_bounds[1])
        print(f"[{time.time() - t0:.1f}s] MODE: TEST REGION {TEST_REGION_LONLAT} "
              f"-> world px [{bx0:.0f},{by0:.0f},{bx1:.0f},{by1:.0f}]", flush=True)

    seeds = generate_seeds(land_arr, target_km_grid, (bx0, by0, bx1, by1), rng)
    print(f"[{time.time() - t0:.1f}s] seeds: {len(seeds)}", flush=True)

    crop_box = box(bx0, by0, bx1, by1)
    land_tree = STRtree(land_pieces)
    print(f"[{time.time() - t0:.1f}s] land_tree built ({len(land_pieces)} pieces)", flush=True)

    voronoi_polys = build_voronoi_polygons(seeds)
    print(f"[{time.time() - t0:.1f}s] voronoi regions: {len(voronoi_polys)}", flush=True)

    pieces = clip_and_explode(voronoi_polys, land_pieces, land_tree, crop_box)
    print(f"[{time.time() - t0:.1f}s] pieces after clip: {len(pieces)}", flush=True)

    pieces = merge_small_pieces(pieces, target_km_grid)
    print(f"[{time.time() - t0:.1f}s] pieces after merge small: {len(pieces)}", flush=True)

    capital_polys = load_capital_land_polys()
    if capital_polys:
        pieces = merge_capital_coastal_cells(pieces, capital_polys)
        print(f"[{time.time() - t0:.1f}s] pieces after capital merge: {len(pieces)}", flush=True)

    # Финальные id + геометрия соседства (по общей границе, не по исходным
    # Voronoi-семенам — после слияний индекс семени уже не 1:1 с клеткой).
    geoms = [p["geom"] for p in pieces]
    ids = [f"sea_{i:06d}" for i in range(len(geoms))]
    buffered = [g.buffer(0.5) for g in geoms]
    tree = STRtree(buffered)

    out_cells = []
    edges = set()
    for i, geom in enumerate(geoms):
        cand_idx = tree.query(buffered[i])
        neighbor_ids = []
        for ci in cand_idx:
            j = int(ci)
            if j == i:
                continue
            shared = buffered[i].intersection(buffered[j])
            if getattr(shared, "length", 0.0) > MIN_SHARED_BORDER_PX:
                neighbor_ids.append(ids[j])
                edges.add((ids[min(i, j)], ids[max(i, j)]) if i < j else (ids[j], ids[i]))

        ext = [[round(x, 2), round(y, 2)] for x, y in geom.exterior.coords]
        rings = [ext]
        for hole in geom.interiors:
            rings.append([[round(x, 2), round(y, 2)] for x, y in hole.coords])
        xs = [p[0] for p in ext]
        ys = [p[1] for p in ext]
        brd_open, coast = compute_brd_open(ext, land_pieces, land_tree)
        center = geom.representative_point()
        out_cells.append({
            "id": ids[i],
            "name": f"Морская клетка {i + 1}",
            "surface": "sea",
            "rings": rings,
            "brd_open": brd_open,
            "bbox": [min(xs), min(ys), max(xs), max(ys)],
            "center": [round(center.x, 2), round(center.y, 2)],
            "area_km2": round(area_km2_world_px(geom, None), 1),
            "neighbor_sea_ids": sorted(neighbor_ids),
            "coast": coast,
        })

    print(f"[{time.time() - t0:.1f}s] cells finalized: {len(out_cells)}", flush=True)

    import os
    os.makedirs("assets/generated", exist_ok=True)
    json.dump({"world_px": WORLD_PX, "cells": out_cells},
               open(OUT_CELLS, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"[{time.time() - t0:.1f}s] wrote {OUT_CELLS}", flush=True)

    json.dump({"version": 1, "edges": [list(e) for e in sorted(edges)]},
               open(OUT_GRAPH, "w", encoding="utf-8"), separators=(",", ":"))
    print(f"[{time.time() - t0:.1f}s] wrote {OUT_GRAPH}", flush=True)


if __name__ == "__main__":
    main()
