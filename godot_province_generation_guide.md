# Генерация провинций с неровными границами в Godot 4

Этот гайд показывает, как внутри готовой территории автоматически создать несколько провинций с неровными административными границами — примерно как на политических картах и в grand strategy-играх.

В примере используется **Godot 4**, `FastNoiseLite`, растровая маска территории и алгоритм **multi-source Dijkstra**.

---

## Что мы хотим получить

Есть готовая форма государства или региона:

```text
море
       █████████
     █████████████
   ███████████████
     █████████████
       ████████
```

Нужно автоматически разделить её, например, на 4 провинции:

```text
          2
       _______
      /       \
  1  /         \
 ___/           \
    \____        \
         \___     \
    3        \__ 4
```

При этом:

- внешняя граница региона не меняется;
- внутри появляется ровно 4 провинции;
- провинции связные;
- внутренние границы неровные;
- внешний контур можно оставить толстым белым;
- внутренние границы можно сделать тонкими серыми.

---

# 1. Общая идея

Алгоритм выглядит так:

```text
Форма страны
     ↓
маска страны
     ↓
4 точки-центра провинций
     ↓
все 4 провинции начинают расти
     ↓
шум немного искажает направление роста
     ↓
вся территория распределяется между 4 провинциями
     ↓
рисуем цвета
     ↓
рисуем тонкие внутренние границы
     ↓
рисуем толстую белую внешнюю границу
```

---

# 2. Что такое шум

Шум — это управляемая случайность.

Если граница строится без шума, она может получиться слишком геометрической:

```text
|
|
|
|
|
```

Если добавить плавный шум:

```text
 |
  |
 /
 |
  \
   |
  /
```

Для карт лучше использовать не обычный `random()`, а плавный шум:

- Perlin Noise;
- Simplex Noise;
- FastNoiseLite.

У соседних точек значения похожи, поэтому граница изгибается крупными плавными участками, а не превращается в хаотичную рябь.

---

# 3. Подготовь маску территории

Создай отдельную картинку, например:

```text
country_mask.png
```

В ней:

- территория, которую надо делить на провинции — белая;
- всё остальное — чёрное или прозрачное.

Пример:

```text
чёрное чёрное чёрное
      ███████
    ███████████
   █████████████
     █████████
       █████
```

Размер маски должен совпадать с размером карты.

Например:

```text
world_map.png     2048 × 1024
country_mask.png  2048 × 1024
```

---

# 4. Структура сцены

Можно сделать так:

```text
Map
├── BaseMap       Sprite2D
└── Provinces     Sprite2D
```

Где:

- `BaseMap` — обычная карта;
- `Provinces` — слой, в который код нарисует провинции.

Для обоих `Sprite2D` желательно поставить:

```text
Centered = false
```

Тогда координаты пикселей будут совпадать с координатами изображения.

---

# 5. Скрипт ProvinceGenerator.gd

Создай файл:

```text
ProvinceGenerator.gd
```

и прикрепи его к `Provinces`.

```gdscript
extends Sprite2D


# ============================================================
# НАСТРОЙКИ
# ============================================================

@export var mask_texture: Texture2D

@export_range(2, 20, 1)
var province_count: int = 4

@export var generation_seed: int = 12345

@export_range(0.001, 0.1, 0.001)
var noise_frequency: float = 0.018

@export_range(0.0, 5.0, 0.05)
var roughness: float = 1.8

@export_range(0, 50, 1)
var seed_margin: int = 8

@export_range(1, 10, 1)
var outer_border_width: int = 2

@export var manual_seeds: Array[Vector2i] = []


# ============================================================
# ЦВЕТА
# ============================================================

var province_colors: Array[Color] = [
    Color(0.78, 0.72, 0.84, 1.0),
    Color(0.74, 0.81, 0.65, 1.0),
    Color(0.79, 0.63, 0.65, 1.0),
    Color(0.78, 0.70, 0.57, 1.0),
    Color(0.59, 0.67, 0.77, 1.0),
    Color(0.65, 0.78, 0.75, 1.0),
]

var internal_border_color := Color(0.48, 0.45, 0.47, 1.0)
var outer_border_color := Color.WHITE


# ============================================================
# ДАННЫЕ
# ============================================================

var map_width: int
var map_height: int

var province_map := PackedInt32Array()
var cost_map := PackedFloat32Array()
var inside_map := PackedByteArray()

var valid_pixels: Array[Vector2i] = []
var province_seeds: Array[Vector2i] = []

var rng := RandomNumberGenerator.new()
var noise := FastNoiseLite.new()


# ============================================================
# PRIORITY QUEUE / MIN HEAP
# ============================================================

var heap_costs := PackedFloat32Array()
var heap_indices := PackedInt32Array()


const NEIGHBORS := [
    Vector2i(-1, 0),
    Vector2i(1, 0),
    Vector2i(0, -1),
    Vector2i(0, 1),

    Vector2i(-1, -1),
    Vector2i(1, -1),
    Vector2i(-1, 1),
    Vector2i(1, 1)
]


# ============================================================
# ЗАПУСК
# ============================================================

func _ready() -> void:
    centered = false

    if mask_texture == null:
        push_error("Не указана mask_texture!")
        return

    generate_provinces()


# ============================================================
# ГЛАВНАЯ ФУНКЦИЯ
# ============================================================

func generate_provinces() -> void:

    rng.seed = generation_seed

    var mask_image: Image = mask_texture.get_image()

    map_width = mask_image.get_width()
    map_height = mask_image.get_height()

    if map_width <= 0 or map_height <= 0:
        push_error("Маска имеет неправильный размер.")
        return

    _build_inside_map(mask_image)

    if valid_pixels.is_empty():
        push_error("В маске нет белой территории.")
        return

    _setup_noise()

    province_seeds = _choose_seeds()

    print("Центры провинций:")
    for i in range(province_seeds.size()):
        print(i, ": ", province_seeds[i])

    _grow_provinces()
    _render_provinces()

    print("Генерация закончена.")


# ============================================================
# СОЗДАНИЕ МАСКИ
# ============================================================

func _build_inside_map(mask_image: Image) -> void:

    var total := map_width * map_height

    inside_map.resize(total)
    inside_map.fill(0)

    province_map.resize(total)
    province_map.fill(-1)

    cost_map.resize(total)
    cost_map.fill(1.0e30)

    valid_pixels.clear()

    for y in range(map_height):
        for x in range(map_width):

            var color := mask_image.get_pixel(x, y)
            var brightness := (color.r + color.g + color.b) / 3.0

            var inside := (
                color.a > 0.1
                and brightness > 0.5
            )

            var index := _get_index(x, y)

            if inside:
                inside_map[index] = 1
                valid_pixels.append(Vector2i(x, y))


# ============================================================
# ШУМ
# ============================================================

func _setup_noise() -> void:

    noise.seed = generation_seed
    noise.noise_type = FastNoiseLite.TYPE_SIMPLEX_SMOOTH
    noise.frequency = noise_frequency

    noise.fractal_type = FastNoiseLite.FRACTAL_FBM
    noise.fractal_octaves = 3
    noise.fractal_gain = 0.5
    noise.fractal_lacunarity = 2.0


# ============================================================
# ВЫБОР ЦЕНТРОВ ПРОВИНЦИЙ
# ============================================================

func _choose_seeds() -> Array[Vector2i]:

    var result: Array[Vector2i] = []

    if manual_seeds.size() == province_count:

        var all_valid := true

        for p in manual_seeds:

            if not _is_inside(p.x, p.y):
                all_valid = false
                break

        if all_valid:
            return manual_seeds.duplicate()


    var first := _get_random_safe_pixel()

    if first.x < 0:
        first = valid_pixels[
            rng.randi_range(
                0,
                valid_pixels.size() - 1
            )
        ]

    result.append(first)


    while result.size() < province_count:

        var best_point := Vector2i(-1, -1)
        var best_distance := -1.0

        var attempts := min(
            4000,
            max(500, valid_pixels.size())
        )

        for attempt in range(attempts):

            var candidate := valid_pixels[
                rng.randi_range(
                    0,
                    valid_pixels.size() - 1
                )
            ]

            if not _is_safe_seed(candidate):
                continue

            var closest_distance := 1.0e30

            for existing in result:

                var dx := candidate.x - existing.x
                var dy := candidate.y - existing.y

                var distance_squared := float(
                    dx * dx + dy * dy
                )

                closest_distance = min(
                    closest_distance,
                    distance_squared
                )

            if closest_distance > best_distance:
                best_distance = closest_distance
                best_point = candidate


        if best_point.x < 0:
            best_point = valid_pixels[
                rng.randi_range(
                    0,
                    valid_pixels.size() - 1
                )
            ]

        result.append(best_point)

    return result


func _get_random_safe_pixel() -> Vector2i:

    for i in range(2000):

        var p := valid_pixels[
            rng.randi_range(
                0,
                valid_pixels.size() - 1
            )
        ]

        if _is_safe_seed(p):
            return p

    return Vector2i(-1, -1)


func _is_safe_seed(point: Vector2i) -> bool:

    if seed_margin <= 0:
        return true

    for dy in range(-seed_margin, seed_margin + 1):
        for dx in range(-seed_margin, seed_margin + 1):

            var x := point.x + dx
            var y := point.y + dy

            if not _is_inside(x, y):
                return false

    return true


# ============================================================
# РОСТ ПРОВИНЦИЙ
# ============================================================

func _grow_provinces() -> void:

    province_map.fill(-1)
    cost_map.fill(1.0e30)

    _heap_clear()


    for province_id in range(province_seeds.size()):

        var seed := province_seeds[province_id]

        var index := _get_index(
            seed.x,
            seed.y
        )

        province_map[index] = province_id
        cost_map[index] = 0.0

        _heap_push(0.0, index)


    while not _heap_is_empty():

        var item := _heap_pop()

        var current_cost: float = item[0]
        var current_index: int = item[1]

        if current_cost > cost_map[current_index] + 0.0001:
            continue


        var x := current_index % map_width
        var y := current_index / map_width

        var province_id := province_map[current_index]


        for direction in NEIGHBORS:

            var nx := x + direction.x
            var ny := y + direction.y


            if nx < 0 or ny < 0:
                continue

            if nx >= map_width or ny >= map_height:
                continue


            var neighbor_index := _get_index(nx, ny)

            if inside_map[neighbor_index] == 0:
                continue


            var diagonal := (
                direction.x != 0
                and direction.y != 0
            )

            var movement_cost := (
                1.41421356
                if diagonal
                else 1.0
            )


            var n := noise.get_noise_2d(
                float(nx),
                float(ny)
            )

            var noise_01 := clamp(
                (n + 1.0) * 0.5,
                0.0,
                1.0
            )


            var terrain_cost := (
                1.0
                + noise_01 * roughness
            )


            var new_cost := (
                current_cost
                + movement_cost * terrain_cost
            )


            if new_cost < cost_map[neighbor_index]:

                cost_map[neighbor_index] = new_cost
                province_map[neighbor_index] = province_id

                _heap_push(
                    new_cost,
                    neighbor_index
                )


# ============================================================
# РЕНДЕР
# ============================================================

func _render_provinces() -> void:

    var output := Image.create(
        map_width,
        map_height,
        false,
        Image.FORMAT_RGBA8
    )

    output.fill(Color(0, 0, 0, 0))


    # Заливка провинций.
    for y in range(map_height):
        for x in range(map_width):

            if not _is_inside(x, y):
                continue

            var index := _get_index(x, y)
            var province_id := province_map[index]

            if province_id < 0:
                continue

            var color := province_colors[
                province_id % province_colors.size()
            ]

            output.set_pixel(
                x,
                y,
                color
            )


    # Внутренние границы.
    for y in range(map_height):
        for x in range(map_width):

            if not _is_inside(x, y):
                continue

            if _is_internal_border(x, y):

                output.set_pixel(
                    x,
                    y,
                    internal_border_color
                )


    # Внешняя белая граница.
    for y in range(map_height):
        for x in range(map_width):

            if _is_near_outer_border(
                x,
                y,
                outer_border_width
            ):

                output.set_pixel(
                    x,
                    y,
                    outer_border_color
                )


    texture = ImageTexture.create_from_image(output)


# ============================================================
# ВНУТРЕННЯЯ ГРАНИЦА
# ============================================================

func _is_internal_border(x: int, y: int) -> bool:

    var current_index := _get_index(x, y)
    var current_id := province_map[current_index]

    var directions := [
        Vector2i(-1, 0),
        Vector2i(1, 0),
        Vector2i(0, -1),
        Vector2i(0, 1)
    ]

    for direction in directions:

        var nx := x + direction.x
        var ny := y + direction.y

        if not _is_inside(nx, ny):
            continue

        var neighbor_id := province_map[
            _get_index(nx, ny)
        ]

        if neighbor_id != current_id:
            if current_id < neighbor_id:
                return true

    return false


# ============================================================
# ВНЕШНЯЯ БЕЛАЯ ГРАНИЦА
# ============================================================

func _is_near_outer_border(
    x: int,
    y: int,
    radius: int
) -> bool:

    var current_inside := _is_inside(x, y)

    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):

            if dx == 0 and dy == 0:
                continue

            var nx := x + dx
            var ny := y + dy

            var neighbor_inside := _is_inside(nx, ny)

            if neighbor_inside != current_inside:

                if current_inside:
                    return true

                if neighbor_inside:
                    return true

    return false


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

func _get_index(x: int, y: int) -> int:
    return y * map_width + x


func _is_inside(x: int, y: int) -> bool:

    if x < 0 or y < 0:
        return false

    if x >= map_width or y >= map_height:
        return false

    return inside_map[
        _get_index(x, y)
    ] == 1


# ============================================================
# MIN HEAP
# ============================================================

func _heap_clear() -> void:

    heap_costs = PackedFloat32Array()
    heap_indices = PackedInt32Array()


func _heap_is_empty() -> bool:
    return heap_costs.is_empty()


func _heap_push(
    cost: float,
    index: int
) -> void:

    heap_costs.append(cost)
    heap_indices.append(index)

    var position := heap_costs.size() - 1

    while position > 0:

        var parent := int(
            (position - 1) / 2
        )

        if heap_costs[parent] <= heap_costs[position]:
            break


        var temp_cost := heap_costs[parent]
        var temp_index := heap_indices[parent]


        heap_costs[parent] = heap_costs[position]
        heap_indices[parent] = heap_indices[position]


        heap_costs[position] = temp_cost
        heap_indices[position] = temp_index


        position = parent


func _heap_pop() -> Array:

    var result_cost := heap_costs[0]
    var result_index := heap_indices[0]

    var last_position := heap_costs.size() - 1


    if last_position == 0:

        heap_costs.resize(0)
        heap_indices.resize(0)

        return [
            result_cost,
            result_index
        ]


    var last_cost := heap_costs[last_position]
    var last_index := heap_indices[last_position]


    heap_costs.resize(last_position)
    heap_indices.resize(last_position)


    heap_costs[0] = last_cost
    heap_indices[0] = last_index


    var position := 0


    while true:

        var left := position * 2 + 1
        var right := position * 2 + 2

        var smallest := position


        if left < heap_costs.size():

            if heap_costs[left] < heap_costs[smallest]:
                smallest = left


        if right < heap_costs.size():

            if heap_costs[right] < heap_costs[smallest]:
                smallest = right


        if smallest == position:
            break


        var temp_cost := heap_costs[position]
        var temp_index := heap_indices[position]


        heap_costs[position] = heap_costs[smallest]
        heap_indices[position] = heap_indices[smallest]


        heap_costs[smallest] = temp_cost
        heap_indices[smallest] = temp_index


        position = smallest


    return [
        result_cost,
        result_index
    ]
```

---

# 6. Как работает province_map

В памяти создаётся массив размером с изображение.

Например:

```text
-1 -1 -1 -1 -1 -1
-1  0  0  1  1 -1
-1  0  0  1  1 -1
-1  0  2  3  1 -1
-1  2  2  3  3 -1
-1 -1 -1 -1 -1 -1
```

Где:

```text
-1 = вне страны
0 = провинция №1
1 = провинция №2
2 = провинция №3
3 = провинция №4
```

Это удобно для игры, потому что по координате мыши можно сразу узнать ID провинции.

---

# 7. Как выбираются центры провинций

Сначала ставятся 4 точки:

```text
       ● 1


● 0


     ● 3

 ● 2
```

После этого все четыре начинают одновременно захватывать свободные клетки.

---

# 8. Почему границы получаются неровными

Основная часть:

```gdscript
var n := noise.get_noise_2d(
    float(nx),
    float(ny)
)
```

Шум делает некоторые клетки чуть более дорогими для прохождения.

Без шума:

```text
1 1 1 1 1
1 1 1 1 1
1 1 1 1 1
```

С шумом:

```text
1.1  1.2  1.5  1.7  1.6
1.0  1.3  1.8  2.1  1.9
1.2  1.4  1.6  1.7  1.5
1.4  1.2  1.1  1.3  1.4
```

Рост выбирает более дешёвые пути, поэтому линия изгибается.

---

# 9. Рекомендуемые настройки

Для начала:

```text
Province Count       4
Generation Seed      12345

Noise Frequency      0.018
Roughness             1.8

Seed Margin           8
Outer Border Width    2
```

---

# 10. Noise Frequency

Этот параметр отвечает за размер изгибов.

## 0.005

Очень крупные изгибы:

```text
________
        \
         \
          ______
```

## 0.02

Подходит для обычных провинций:

```text
____
    \__
       \
      __/
_____/
```

## 0.1

Слишком мелкая рябь:

```text
_/\/\_/\/\/\_/\/
```

Хороший диапазон:

```text
0.01–0.03
```

---

# 11. Roughness

`roughness` отвечает за силу искажения.

## roughness = 0

Почти геометрические границы:

```text
        |
        |
--------+
        |
```

## roughness = 1.5

Нормальные административные границы:

```text
        /
       /
------/
      \
       \
```

## roughness = 5

Уже слишком сильные изгибы:

```text
      ______
 ___/       \____
/    ____        \
    /    \___
___/         \____
```

Для подобного стиля:

```text
1.2–2.5
```

---

# 12. Лучше задавать центры вручную

Полностью случайные центры могут дать плохую композицию.

Поэтому можно использовать:

```gdscript
@export var manual_seeds: Array[Vector2i] = []
```

Например:

```text
0 = (400, 300)
1 = (600, 280)
2 = (410, 480)
3 = (590, 470)
```

Тогда общая структура будет примерно такой:

```text
┌─────────────────────┐
│                     │
│      1          2   │
│                     │
│                     │
│      3          4   │
│                     │
└─────────────────────┘
```

Шум будет менять только форму границ.

---

# 13. Генерация нового варианта по кнопке

Можно добавить:

```gdscript
func _unhandled_input(event: InputEvent) -> void:

    if event is InputEventKey:

        if event.pressed and event.keycode == KEY_R:

            generation_seed += 1
            generate_provinces()
```

Теперь каждое нажатие `R` создаёт новый вариант.

---

# 14. Как узнать, на какую провинцию нажал игрок

Добавь:

```gdscript
func get_province_at_position(
    position: Vector2
) -> int:

    var x := int(floor(position.x))
    var y := int(floor(position.y))

    if x < 0 or y < 0:
        return -1

    if x >= map_width or y >= map_height:
        return -1

    return province_map[
        _get_index(x, y)
    ]
```

И обработку клика:

```gdscript
func _unhandled_input(event: InputEvent) -> void:

    if event is InputEventMouseButton:

        if event.button_index == MOUSE_BUTTON_LEFT:
            if event.pressed:

                var mouse := get_local_mouse_position()

                var province_id := get_province_at_position(
                    mouse
                )

                print(
                    "Нажата провинция: ",
                    province_id
                )
```

---

# 15. Какие данные можно привязать к провинции

Например:

```text
Province 0
название = "Акита"
население = 320000
владелец = Japan
столица = ...
налоги = ...
армия = ...
```

Удобно хранить отдельный объект или словарь данных по `province_id`.

---

# 16. Внутренние и внешние границы

Внутренние:

```text
провинция 1
████████│████████
        ↑
     1 пиксель
```

Внешние:

```text
        ███████
     ███       ███
   ██             ██
```

Они рисуются отдельно.

Правильный порядок рендера:

```text
заливка провинций
        ↓
тонкие внутренние границы
        ↓
толстая белая внешняя граница
```

---

# 17. Не обязательно генерировать карту каждый запуск

Если это постоянная карта игры, можно найти красивый seed:

```text
Seed = 184733
```

и оставить его.

Тогда карта будет одинаковой при каждом запуске.

---

# 18. Сохранение результата в PNG

В конце `_render_provinces()` можно добавить:

```gdscript
output.save_png(
    "user://generated_provinces.png"
)
```

---

# 19. Почему не обычный Voronoi

Обычный Voronoi часто даёт слишком геометрические границы:

```text
          /
         /
        /
-------+
      /
     /
```

Здесь используется рост от центров + шум:

```text
       ___
      /
 ____/
     \__
        \
       __/
______/
```

По стилю это больше похоже на административные границы.

---

# 20. Следующий уровень — учитывать рельеф

Позже стоимость клетки можно считать так:

```text
обычная земля = 1
лес = 1.2
река = 3
холмы = 2
горы = 8
```

Тогда границы начнут естественно идти вдоль:

- рек;
- гор;
- берегов;
- исторических областей.

Пример:

```text
ПРОВИНЦИЯ A

████████████████
              \
~~~~~~~~~~~~~~~\~~~~ РЕКА
                \
                 ███████

                ПРОВИНЦИЯ B
```

---

# 21. Дальнейшее улучшение: превращение границ в полигоны

Если позже понадобятся настоящие векторные полигоны, можно:

1. взять `province_map`;
2. найти границу каждой провинции;
3. использовать `Marching Squares`;
4. получить список точек;
5. упростить его через `Ramer–Douglas–Peucker`;
6. создать `Polygon2D`;
7. рисовать границы через `Line2D`.

Так можно получить красивый векторный слой поверх карты.

---

# 22. Итоговая схема

Для такой карты оптимальная последовательность:

```text
PNG-маска территории
        ↓
4 seed-точки
        ↓
multi-source Dijkstra
        +
FastNoiseLite
        ↓
province_map
        ↓
цветная заливка
        ↓
внутренние границы
        ↓
белая внешняя граница
```

Для начала достаточно использовать:

```text
province_count = 4
noise_frequency = 0.018
roughness = 1.8
```

и вручную поставить четыре центра провинций.

После этого можно сделать редактор внутри Godot: ставить точки мышкой и нажимать `Generate`.
