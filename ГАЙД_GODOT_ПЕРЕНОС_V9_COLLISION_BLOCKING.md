# Гайд: перенос `province_cell_growth_v9_collision_blocking.html` в Godot 4

## Цель

Берём именно механику **`province_cell_growth_v9_collision_blocking.html`** и переносим её в Godot 4.

Общая идея:

```text
Провинция
↓
внутри случайно размещаем несколько кругов далеко друг от друга
↓
у каждого круга тысячи радиальных направлений
↓
каждое направление имеет собственную скорость
↓
для каждой точки провинции считаем:
какой круг добрался бы сюда раньше
↓
получаем первоначальные клетки
↓
8 раз проверяем:
не появился ли круг за чужой территорией
↓
исправляем такие пролезания
↓
небольшая очистка границы
↓
готовые клетки
```

---

# 1. Дефолтные настройки

Именно по последнему выбранному варианту:

```gdscript
# Круги
var circle_count: int = 4
var start_radius: float = 18.0

var min_center_distance: float = 205.0
var edge_margin: float = 52.0
var center_spread: float = 0.97

# Радиальные точки
var ray_count: int = 8700

var base_speed: float = 65.0
var speed_variation: float = 0.29

var speed_arc_count: int = 44
var angular_smoothness: float = 1.0

var micro_variation: float = 0.99
var circle_speed_variation: float = 0.46

# Столкновения
var block_after_enemy: bool = true
var collision_passes: int = 8

# Площадь
var area_profile_strength: float = 0.45

# Постобработка
var cleanup_passes: int = 4
var border_simplify: float = 7.0

# Рабочий raster
var raster_step: int = 3
```

Также в Debug Mode:

```text
Показывать лучи = true
Показывать точки фронта = true
```

Но в самой игре это рисовать не обязательно.

---

# 2. Очень важный момент про 8700 точек

**Не создавай 8700 `Node2D` или `RayCast2D`.**

При четырёх клетках это было бы:

```text
8700 × 4 = 34 800 объектов
```

Это не нужно.

8700 лучей должны существовать просто как числа:

```gdscript
PackedFloat32Array
```

Для одного круга:

```text
speed[0]
speed[1]
speed[2]
...
speed[8699]
```

То есть каждый круг хранит массив из 8700 скоростей.

---

# 3. Структура проекта

Для начала:

```text
province_generation/
│
├── ProvinceCellGenerator.gd
├── CircleGrowthData.gd
├── ProvinceRaster.gd
└── ProvinceCellDebug.gd
```

Но для первого прототипа можно написать всё в:

```text
ProvinceCellGenerator.gd
```

Сцена:

```text
ProvinceGeneratorDemo
│
├── ProvinceCellGenerator
├── ResultSprite
└── DebugDraw
```

---

# 4. Данные одного круга

Создаём класс:

```gdscript
class CircleData:
	var position: Vector2
	var speed_multiplier: float = 1.0
	var speeds: PackedFloat32Array
```

И массив:

```gdscript
var circles: Array = []
```

---

# 5. Получаем полигон провинции

Предположим, у тебя уже есть:

```gdscript
var province_polygon: PackedVector2Array
```

Например:

```gdscript
province_polygon = PackedVector2Array([
	Vector2(100, 100),
	Vector2(500, 80),
	Vector2(700, 200),
	Vector2(650, 500),
	Vector2(200, 550)
])
```

Для проверки попадания точки внутрь полигона:

```gdscript
Geometry2D.is_point_in_polygon()
```

---

# 6. Переводим провинцию во временную сетку

Геометрия клеток считается не напрямую на `Polygon2D`, а на временном raster.

Например:

```text
raster_step = 3
```

Один логический пиксель:

```text
3 × 3 пикселя карты
```

Создаём:

```gdscript
var grid_width: int
var grid_height: int

var inside_map: PackedByteArray
var owner_map: PackedInt32Array
```

Значения:

```text
inside_map:

0 = вне провинции
1 = внутри


owner_map:

-1 = никто
 0 = круг 0
 1 = круг 1
 2 = круг 2
 3 = круг 3
```

---

# 7. Bounding Box

Не обрабатываем всю карту мира.

Находим прямоугольник только вокруг конкретной провинции:

```gdscript
func calculate_bbox(polygon: PackedVector2Array) -> Rect2:
	var min_x := INF
	var min_y := INF
	var max_x := -INF
	var max_y := -INF

	for p in polygon:
		min_x = min(min_x, p.x)
		min_y = min(min_y, p.y)
		max_x = max(max_x, p.x)
		max_y = max(max_y, p.y)

	return Rect2(
		Vector2(min_x, min_y),
		Vector2(max_x - min_x, max_y - min_y)
	)
```

---

# 8. Создаём маску

```gdscript
func build_raster() -> void:
	grid_width = int(ceil(province_bbox.size.x / raster_step))
	grid_height = int(ceil(province_bbox.size.y / raster_step))

	var total := grid_width * grid_height

	inside_map.resize(total)
	inside_map.fill(0)

	owner_map.resize(total)
	owner_map.fill(-1)

	for y in range(grid_height):
		for x in range(grid_width):

			var world_pos := grid_to_world(x, y)

			if Geometry2D.is_point_in_polygon(
				world_pos,
				province_polygon
			):
				inside_map[index(x, y)] = 1
```

Вспомогательные функции:

```gdscript
func index(x: int, y: int) -> int:
	return y * grid_width + x


func grid_to_world(x: int, y: int) -> Vector2:
	return province_bbox.position + Vector2(
		(x + 0.5) * raster_step,
		(y + 0.5) * raster_step
	)
```

---

# 9. Размещаем круги

Теперь нужно поставить 4 центра.

Но не просто:

```gdscript
randf()
```

Иначе они могут оказаться рядом.

Используем **farthest-point sampling**.

Логика:

```text
первая точка
→ случайно

вторая
→ ищем место максимально далеко от первой

третья
→ максимально далеко от первых двух

четвёртая
→ максимально далеко от первых трёх
```

При этом:

```text
минимальная дистанция = 205
отступ от края = 52
```

---

# 10. Случайный кандидат

```gdscript
func random_inside_position() -> Vector2:
	for attempt in range(5000):

		var p := Vector2(
			randf_range(
				province_bbox.position.x,
				province_bbox.end.x
			),
			randf_range(
				province_bbox.position.y,
				province_bbox.end.y
			)
		)

		if Geometry2D.is_point_in_polygon(
			p,
			province_polygon
		):
			return p

	return province_bbox.get_center()
```

Но ещё понадобится:

```text
distance_to_province_border(p)
```

чтобы центр не оказался прямо у берега.

---

# 11. Разносим центры

Псевдокод:

```gdscript
func generate_circle_positions() -> Array[Vector2]:

	var result: Array[Vector2] = []

	result.append(
		random_valid_position()
	)

	while result.size() < circle_count:

		var best_position := Vector2.ZERO
		var best_score := -INF

		for attempt in range(1300):

			var candidate := random_valid_position()

			var nearest := INF

			for existing in result:
				nearest = min(
					nearest,
					candidate.distance_to(existing)
				)

			if nearest < min_center_distance:
				continue

			var score := nearest * center_spread

			# Немного случайности.
			score += randf() * 50.0 * (1.0 - center_spread)

			if score > best_score:
				best_score = score
				best_position = candidate

		result.append(best_position)

	return result
```

---

# 12. Теперь создаём 8700 скоростей

Окружность:

```text
360°
```

делим на:

```text
8700 направлений
```

Шаг:

```text
360 / 8700
≈ 0.0414°
```

То есть массив очень плотный.

---

# 13. Сначала создаём 44 крупные скоростные дуги

Настройка:

```text
speed_arc_count = 44
```

Создаём:

```gdscript
var knots := PackedFloat32Array()
knots.resize(speed_arc_count)
```

Каждой дуге:

```gdscript
knots[i] = randf_range(-1.0, 1.0)
```

Например:

```text
0.22
-0.51
-0.38
0.63
0.77
...
```

---

# 14. Для каждого из 8700 лучей интерполируем скорость

Прямой перенос логики v9:

```gdscript
func build_speed_profile(
	circle_index: int,
	multiplier: float
) -> PackedFloat32Array:

	var speeds := PackedFloat32Array()
	speeds.resize(ray_count)

	var rng := RandomNumberGenerator.new()
	rng.seed = generation_seed + circle_index * 7919

	var knots := PackedFloat32Array()
	knots.resize(speed_arc_count)

	for i in range(speed_arc_count):
		knots[i] = rng.randf_range(-1.0, 1.0)

	for ray in range(ray_count):

		var u := (
			float(ray)
			/ float(ray_count)
			* float(speed_arc_count)
		)

		var k0 := int(floor(u)) % speed_arc_count
		var k1 := (k0 + 1) % speed_arc_count

		var t := u - floor(u)

		var smooth_t := t * t * (3.0 - 2.0 * t)

		t = lerpf(
			t,
			smooth_t,
			angular_smoothness
		)

		var z := lerpf(
			knots[k0],
			knots[k1],
			t
		)

		# Микроразница соседних лучей.
		z += rng.randf_range(-1.0, 1.0) \
			* micro_variation \
			* 0.12

		var speed := (
			base_speed
			* multiplier
			* (
				1.0
				+ z
				* speed_variation
				* 0.62
			)
		)

		speeds[ray] = max(
			base_speed * 0.2,
			speed
		)

	return speeds
```

При выбранных настройках:

```text
angular_smoothness = 1.0
micro_variation = 0.99
```

---

# 15. Разница средней скорости кругов

Настройка:

```text
46%
```

В браузерной версии это не означает прямые ±46%.

Коэффициент дополнительно умножается примерно на:

```text
0.18
```

Поэтому:

```gdscript
multiplier *= 1.0 + randf_range(
	-1.0,
	1.0
) * circle_speed_variation * 0.18
```

При:

```text
0.46
```

максимальная случайная разница будет примерно:

```text
±8.28%
```

Именно так работает выбранный вариант v9.

---

# 16. Профиль «1 крупная + 2 средние + 1 малая»

В v9 используются коэффициенты:

```gdscript
var size_multipliers := [
	1.15,
	1.06,
	0.98,
	0.88
]
```

Потом они перемешиваются:

```gdscript
size_multipliers.shuffle()
```

И ослабляются параметром:

```gdscript
area_profile_strength = 0.45
```

Формула:

```gdscript
func apply_area_strength(value: float) -> float:
	return 1.0 + (
		value - 1.0
	) * area_profile_strength
```

Например:

```text
1.15
```

при силе `45%` превращается примерно в:

```text
1.0675
```

То есть эффект есть, но он не слишком сильный.

---

# 17. Получение скорости по произвольному углу

Пиксель находится не обязательно точно на одном из 8700 лучей.

Поэтому берём два соседних луча.

```gdscript
func speed_at_angle(
	circle,
	angle: float
) -> float:

	var normalized := fposmod(
		angle,
		TAU
	)

	var u := (
		normalized
		/ TAU
		* ray_count
	)

	var i0 := int(floor(u)) % ray_count
	var i1 := (i0 + 1) % ray_count

	var t := u - floor(u)

	return lerpf(
		circle.speeds[i0],
		circle.speeds[i1],
		t
	)
```

---

# 18. Главное соревнование

Теперь для **каждого raster-пикселя** внутри провинции считаем время прихода каждого круга.

Формула:

```text
время =
(расстояние от центра - начальный радиус)
/ скорость по этому направлению
```

---

# 19. Функция `arrival_time`

```gdscript
func arrival_time(
	circle,
	point: Vector2
) -> float:

	var delta: Vector2 = point - circle.position

	var distance := delta.length()

	var angle := atan2(
		delta.y,
		delta.x
	)

	var speed := speed_at_angle(
		circle,
		angle
	)

	return max(
		0.0,
		distance - start_radius
	) / speed
```

---

# 20. Распределяем всю провинцию

```gdscript
func calculate_initial_owners() -> void:

	owner_map.fill(-1)

	for y in range(grid_height):
		for x in range(grid_width):

			var idx := index(x, y)

			if inside_map[idx] == 0:
				continue

			var point := grid_to_world(x, y)

			var best_circle := -1
			var best_time := INF

			for k in range(circles.size()):

				var time := arrival_time(
					circles[k],
					point
				)

				if time < best_time:
					best_time = time
					best_circle = k

			owner_map[idx] = best_circle
```

Вот здесь происходит основное соревнование.

---

# 21. Что получится до проверки столкновений

Например:

```text
AAAAAAAABBBBBB
AAAAAAABBBBBBB
AAAAACCCBBBBBB
AAAACCCCCBBBBB
DDDDCCCCCCBBBB
DDDDDDCCCCBBBB
```

Но иногда может появиться проблема:

```text
AAAAA BBBBB A
```

То есть A математически снова оказался быстрее **за чужой территорией**.

Именно поэтому в v9 есть следующий этап.

---

# 22. Collision Blocking

Настройки:

```text
Луч останавливается после встречи с чужой клеткой = ON
collision_passes = 8
```

Работает это так.

Для каждого круга:

```text
A
```

создаём:

```gdscript
var cut_distance := PackedFloat32Array()
cut_distance.resize(ray_count)
cut_distance.fill(INF)
```

И:

```gdscript
var blocker_owner := PackedInt32Array()
blocker_owner.resize(ray_count)
blocker_owner.fill(-1)
```

---

# 23. Ищем первую чужую территорию каждого направления

Для каждого пикселя, который принадлежит **не A**:

```text
вычисляем угол от A
↓
превращаем угол в номер луча
↓
смотрим расстояние
↓
запоминаем ближайшего чужого владельца
```

---

# 24. Получение номера луча

```gdscript
func angle_to_ray(angle: float) -> int:

	var normalized := fposmod(
		angle,
		TAU
	)

	return int(
		normalized
		/ TAU
		* ray_count
	) % ray_count
```

---

# 25. Первый проход

```gdscript
for y in range(grid_height):
	for x in range(grid_width):

		var idx := index(x, y)

		var current_owner := source[idx]

		if current_owner < 0:
			continue

		if current_owner == circle_id:
			continue

		var point := grid_to_world(x, y)

		var delta := point - circle.position
		var distance := delta.length()

		if distance < start_radius:
			continue

		var ray := angle_to_ray(
			atan2(delta.y, delta.x)
		)

		if distance < cut_distance[ray]:

			cut_distance[ray] = distance
			blocker_owner[ray] = current_owner
```

---

# 26. Теперь ищем собственную территорию за чужой

Например:

```text
A → A → A → B → B → A
```

Последний `A` незаконен.

Проверяем каждый пиксель A:

```gdscript
if blocker_owner[ray] >= 0:
	if distance > cut_distance[ray] + tolerance:

		next_owner[idx] = blocker_owner[ray]
```

В v9 tolerance примерно:

```gdscript
var tolerance := raster_step * 1.75
```

---

# 27. Полная функция Collision Blocking

```gdscript
func enforce_collision_blocking() -> void:

	if not block_after_enemy:
		return

	for pass_index in range(collision_passes):

		var source := owner_map.duplicate()
		var next := source.duplicate()

		var changes := 0

		for circle_id in range(circles.size()):

			var circle = circles[circle_id]

			var cut_distance := PackedFloat32Array()
			cut_distance.resize(ray_count)
			cut_distance.fill(INF)

			var blocker := PackedInt32Array()
			blocker.resize(ray_count)
			blocker.fill(-1)

			# --------------------------------
			# 1. Где впервые начинается враг
			# --------------------------------

			for y in range(grid_height):
				for x in range(grid_width):

					var idx := index(x, y)

					if inside_map[idx] == 0:
						continue

					var cell_owner := source[idx]

					if cell_owner < 0:
						continue

					if cell_owner == circle_id:
						continue

					var p := grid_to_world(x, y)

					var delta: Vector2 = (
						p - circle.position
					)

					var distance := delta.length()

					if distance < start_radius:
						continue

					var ray := angle_to_ray(
						atan2(
							delta.y,
							delta.x
						)
					)

					if distance < cut_distance[ray]:

						cut_distance[ray] = distance
						blocker[ray] = cell_owner

			# --------------------------------
			# 2. Убираем свою территорию
			#    за первым врагом
			# --------------------------------

			for y in range(grid_height):
				for x in range(grid_width):

					var idx := index(x, y)

					if source[idx] != circle_id:
						continue

					var p := grid_to_world(x, y)

					var delta: Vector2 = (
						p - circle.position
					)

					var distance := delta.length()

					if distance < start_radius:
						continue

					var ray := angle_to_ray(
						atan2(
							delta.y,
							delta.x
						)
					)

					if blocker[ray] < 0:
						continue

					var tolerance := (
						raster_step * 1.75
					)

					if distance > \
						cut_distance[ray] \
						+ tolerance:

						next[idx] = blocker[ray]
						changes += 1

		owner_map = next

		if changes == 0:
			break
```

Это и есть ключевая механика именно **v9**.

---

# 28. Почему 8 проходов

Представим:

```text
A A A B A C
```

Первый проход убрал незаконный A:

```text
A A A B B C
```

Но после этого могла измениться ситуация между B и C.

Поэтому повторяем:

```text
до 8 раз
```

Если раньше изменений больше нет:

```gdscript
if changes == 0:
	break
```

---

# 29. Очистка мелких пиксельных зубцов

После Collision Blocking можно сделать 3–4 прохода простого majority filter.

Берём соседей `3×3`.

Если почти все вокруг принадлежат другому владельцу:

```text
BBB
BAB
BBB
```

центральный `A` превращаем в `B`.

Но очистка должна быть слабой.

Не надо превращать границы в идеально гладкие.

---

# 30. После очистки ещё раз Collision Blocking

Рекомендуемый порядок:

```text
initial competition
↓
8 collision passes
↓
cleanup
↓
ещё раз collision blocking
↓
готово
```

Потому что cleanup сам может слегка передвинуть границу.

---

# 31. Общий код генерации

Главная функция:

```gdscript
func generate_province_cells() -> void:

	# 1
	province_bbox = calculate_bbox(
		province_polygon
	)

	# 2
	build_raster()

	# 3
	generate_circles()

	# 4
	for circle in circles:
		circle.speeds = build_speed_profile(...)

	# 5
	calculate_initial_owners()

	# 6
	enforce_collision_blocking()

	# 7
	cleanup_owner_map()

	# 8
	enforce_collision_blocking()

	# 9
	render_result()
```

---

# 32. Рендер результата

Для Debug Mode удобно создать `Image`.

Например:

```gdscript
func create_result_image() -> Image:

	var image := Image.create_empty(
		grid_width,
		grid_height,
		false,
		Image.FORMAT_RGBA8
	)

	var colors := [
		Color("#c7b8dc"),
		Color("#cbb58f"),
		Color("#a7c995"),
		Color("#d2a1aa")
	]

	for y in range(grid_height):
		for x in range(grid_width):

			var idx := index(x, y)

			if inside_map[idx] == 0:
				image.set_pixel(
					x,
					y,
					Color.TRANSPARENT
				)
				continue

			var owner := owner_map[idx]

			image.set_pixel(
				x,
				y,
				colors[owner % colors.size()]
			)

	return image
```

Потом:

```gdscript
var texture := ImageTexture.create_from_image(
	result_image
)

$ResultSprite.texture = texture
```

---

# 33. Для игры `owner_map` важнее картинки

Не определяй клетку по цвету.

Главные игровые данные:

```gdscript
owner_map
```

Например игрок нажал:

```text
x = 152
y = 80
```

Получаем:

```gdscript
var cell_id := owner_map[
	index(x, y)
]
```

И:

```text
0
```

значит это клетка №0.

---

# 34. Анимация роста

Для самой игры она не нужна.

Но для Debug Mode можно повторить HTML.

После готового `owner_map` для каждого пикселя считаем:

```gdscript
arrival_time(
	circles[owner],
	point
)
```

Получаем:

```text
pixel A → 0.2 s
pixel B → 0.4 s
pixel C → 0.41 s
...
```

Сортируем и постепенно показываем.

То есть визуально будет казаться, что клетки реально растут одновременно.

---

# 35. Лучи в Debug Mode

Не рисуй все 8700.

Экран превратится в белое пятно.

Например показываем:

```gdscript
var debug_ray_step := 100
```

Получится:

```text
8700 / 100
=
87 видимых лучей
```

на один круг.

При этом в расчётах всё равно работают все 8700.

---

# 36. Производительность

При:

```text
4 круга
8700 лучей
```

8700 почти не проблема.

Потому что для пикселя мы **не проверяем 8700 лучей**.

Мы вычисляем угол:

```gdscript
atan2()
```

и сразу получаем:

```text
ray № 5247
```

или два соседних луча.

То есть первоначальное соревнование примерно:

```text
число raster-пикселей
×
4 круга
```

а не:

```text
пиксели × 4 × 8700
```

Это огромная разница.

---

# 37. Где будет самое тяжёлое место

Самая тяжёлая часть:

```text
collision_passes = 8
```

Потому что каждый проход сканирует raster несколько раз.

Поэтому для генерации мировой карты лучше:

```text
генерировать провинции один раз;
сохранять результат;
не пересчитывать каждый кадр.
```

То есть система должна работать как генератор:

```text
Generate
↓
Save
↓
Game uses saved cells
```

а не как постоянно работающая симуляция.

---

# 38. Обязательно хранить seed

Например:

```gdscript
var generation_seed: int = 482718
```

Тогда:

```text
одна и та же провинция
+
одинаковый seed
+
одинаковые параметры
=
одинаковые клетки
```

Это понадобится для воспроизводимости мира.

---

# 39. Структура сохранённой провинции

После генерации:

```json
{
	"province_id": "province:example",

	"generation_seed": 482718,

	"cell_count": 4,

	"circles": [
		{
			"x": 120.4,
			"y": 87.1
		},
		{
			"x": 330.2,
			"y": 150.8
		}
	],

	"cells": [
		{
			"id": 0
		},
		{
			"id": 1
		},
		{
			"id": 2
		},
		{
			"id": 3
		}
	]
}
```

А `owner_map` можно сохранять отдельно в бинарном формате.

---

# 40. Реальная столица провинции

Для системы, которую мы обсуждали раньше, можно сделать специальное правило:

```text
один из кругов
=
координаты реальной столицы провинции
```

А остальные:

```text
случайные,
но далеко от неё и друг от друга
```

Например:

```gdscript
positions.append(
	real_capital_position
)
```

А затем farthest-point создаёт остальные `N - 1`.

Это легко встроить поверх текущей механики и **не меняет сам алгоритм соревнования**.

---

# 41. Порядок реализации

## Этап 1

```text
Polygon → raster
```

Показать маску.

## Этап 2

```text
4 случайных сильно разнесённых центра
```

## Этап 3

Создать:

```text
8700 speed values
```

для каждого.

## Этап 4

Нарисовать график скоростей по окружности.

## Этап 5

Реализовать:

```gdscript
speed_at_angle()
```

## Этап 6

Реализовать:

```gdscript
arrival_time()
```

## Этап 7

Получить первоначальный:

```text
owner_map
```

## Этап 8

Добавить:

```text
Collision Blocking ×8
```

## Этап 9

Добавить слабую очистку.

## Этап 10

Сохранить результат.

## Этап 11

Только потом делать:

```text
контуры;
Polygon2D;
клик по клеткам;
массовую генерацию мира.
```

---

# 42. Главная формула всей системы

```gdscript
arrival_time =
	max(
		0,
		distance_to_circle - start_radius
	)
	/
	speed_at_angle
```

А победитель:

```gdscript
owner =
	circle_with_minimum_arrival_time
```

После этого:

```text
Collision Blocking × 8
```

не позволяет кругу свободно появляться далеко за уже обнаруженным конкурентом.

---

# 43. Финальная архитектура

```text
ПРОВИНЦИЯ
        ↓
POLYGON
        ↓
LOCAL RASTER
        ↓
4 КРУГА
        ↓
разнести центры
        ↓
для каждого:
8700 скоростей
        ↓
44 крупных скоростных дуги
        ↓
плавность 100%
        ↓
micro variation 99%
        ↓
для каждого raster-пикселя:
посчитать arrival_time от 4 кругов
        ↓
минимальное время = владелец
        ↓
INITIAL OWNER MAP
        ↓
COLLISION BLOCKING
× 8 проходов
        ↓
CLEANUP
        ↓
COLLISION BLOCKING
        ↓
FINAL OWNER MAP
        ↓
контуры клеток
        ↓
сохранение
```

---

# 44. Коротко: что именно переносим из HTML v9

```text
✔ случайные, но сильно разнесённые центры;
✔ старт не из одной точки, а из небольшого круга;
✔ 8700 радиальных направлений;
✔ у каждого направления своя скорость;
✔ 44 крупных скоростных дуги;
✔ плавность соседних направлений 100%;
✔ микроразница соседних лучей 99%;
✔ средняя скорость кругов может отличаться;
✔ профиль "1 крупная + 2 средние + 1 малая";
✔ initial owner определяется по минимальному arrival_time;
✔ после этого 8 проходов Collision Blocking;
✔ затем лёгкая очистка;
✔ затем ещё один Collision Blocking;
✔ owner_map становится основным игровым результатом.
```

Это должен быть прямой перенос выбранной механики HTML в Godot 4, а не другая система.
