# Генерация сухопутных клеток провинции в Godot 4
## Динамическое число клеток по региональной таблице + Improved Political Claims + последовательное деление

**Проект:** глобальная историческая стратегия на Godot 4  
**Назначение:** технический гайд для реализации генератора внутренних сухопутных клеток провинций.

---

# 1. Главный принцип

Число клеток **не фиксируется в генераторе**. Нельзя использовать:

```text
каждая провинция = 5 клеток
```

или:

```text
каждая провинция = 4 клетки
```

Правильная схема:

```text
региональный профиль
→ площадь конкретной провинции
→ min/max региона
→ допустимые локальные поправки
→ редкий override
→ final_cell_count = N
→ генератор строит ровно N клеток
```

Таким образом таблица отвечает на вопрос **«сколько клеток»**, а геометрический генератор — **«как они выглядят»**.

---

# 2. Какие исходные файлы учтены

В этом плане учтены:

- `ТАБЛИЦА_РЕГИОНАЛЬНЫХ_ПРОФИЛЕЙ_КЛЕТОК(1).xlsx`;
- `ОТЧЕТ_ПЛОЩАДЬ_КЛЕТОК_РЕГИОНЫ_И_ГЕОМЕТРИЯ(1).md`;
- `ГЕОМЕТРИЯ_СУХОПУТНЫХ_КЛЕТОК_ПОЛНЫЙ_АНАЛИЗ_И_ПЛАН(1).md`;
- `ЛА_КОРУНЬЯ_УЛУЧШЕНИЕ_ГЕОМЕТРИИ_КЛЕТОК(1).md`;
- визуальный тест `Improved Political Claims`.

Ключевой вывод из документов: систему расчёта числа клеток нужно сохранить, а механический Voronoi/N-way growth как финальный способ геометрии — заменить.

---

# 3. Важные ограничения текущего проекта

## 3.1. Рельеф на этом этапе отсутствует

Рельеф создаётся **после** клеток. Поэтому генератор клеток сейчас не должен использовать как вход:

- горы;
- хребты;
- водоразделы;
- долины из игрового рельефа;
- склоны;
- позднее создаваемые реки;
- любые слои, которых ещё не существует.

Из аналитических документов можно сохранить саму идею `cost field`, но на текущем этапе оно должно строиться из уже доступной геометрии:

```text
контур провинции;
берег;
вогнутости;
перешейки;
лопасти;
медиальный скелет;
локальная ширина;
координаты реальной столицы;
региональный профиль.
```

Если когда-либо порядок генерации изменится, природные барьеры можно добавить позже дополнительным слоем.

## 3.2. Игрового города ещё нет

На этапе генерации клеток игрового города не существует.

Термин `primary cell` / «потенциальная городская клетка» означает клетку вокруг **координат реальной столицы соответствующей провинции**. Это географический anchor под будущий главный город.

То есть используется:

```text
real_capital_position
```

а не:

```text
existing_game_city
```

---

# 4. Архитектуру делим на две независимые подсистемы

## A. ProvinceCellCountResolver

Решает только:

```text
сколько клеток должно быть в провинции?
```

Выход:

```text
final_cell_count = N
```

## B. ProvinceCellGeometryGenerator

Получает:

```text
province + N
```

и обязан построить ровно `N` корректных связанных клеток.

Геометрический генератор **не должен сам решать**, что ему хочется 4, 5 или 6 зон.

---

# 5. Что находится в Excel

В книге есть базовые классы плотности P0–P8:

| Код | Профиль | Базовая цель, км² | Мин | Макс |
|---|---|---:|---:|---:|
| P0 | Метропольное ядро | 500 | 3 | 8 |
| P1 | Сверхплотный исторический | 800 | 1 | 10 |
| P2 | Плотный исторический | 1400 | 1 | 12 |
| P3 | Обычный исторический | 2200 | 1 | 14 |
| P4 | Широкий аграрный | 4000 | 1 | 16 |
| P5 | Редкий аграрный/степной | 8000 | 1 | 16 |
| P6 | Фронтирный | 18000 | 1 | 14 |
| P7 | Редкий | 45000 | 1 | 12 |
| P8 | Крайне редкий | 150000 | 1 | 12 |

Но конкретная строка региона важнее базового класса.

Например:

```text
P3 default = 2200 км²
```

а Галисия имеет:

```text
profile_id = P3
target_cell_area_km2 = 2100
min = 1
max = 10
```

Для Галисии нужно использовать **2100**, а не 2200.

Приоритет:

```text
1. конкретный регион;
2. P0–P8 как default/fallback;
3. province override только для редкого исключения.
```

В листе `Мировые регионы v1` находится 273 проектных региональных профиля.

---

# 6. Excel не должен читаться runtime-игрой

Excel — проектный источник данных.

Перед сборкой его нужно конвертировать в JSON.

Рекомендуемые файлы:

```text
assets/game_data/land_cell_generation_profiles.json
assets/game_data/regions.json
assets/game_data/province_cell_generation_overrides.json
```

Пример региона:

```json
{
  "id": "region:iberia:galicia",
  "macroregion_id": "macroregion:iberia",
  "land_cell_generation": {
    "profile_id": "P3",
    "target_cell_area_km2": 2100,
    "min_cells_per_province": 1,
    "max_cells_per_province": 10
  }
}
```

Пример провинции:

```json
{
  "id": "province:spain:la_coruna",
  "region_id": "region:iberia:galicia",
  "area_km2": 7950,
  "capital_anchor": {
    "lon": -8.4115,
    "lat": 43.3623
  }
}
```

`capital_anchor` — географический anchor, а не игровой город.

---

# 7. Формула числа клеток

Документы предлагают:

```text
K_local = coast × relief × shape
```

Но сейчас рельеф недоступен. Поэтому в текущей версии:

```text
K_local = coast_factor × shape_factor
K_local = clamp(K_local, 0.85, 1.35)
```

Либо технически можно оставить:

```text
relief_factor = 1.0
```

до изменения pipeline.

Далее:

```text
raw_count =
    province_area_km2
    / region.target_cell_area_km2
    × K_local

area_count = round(raw_count)

final_count =
    clamp(
        max(area_count, anchor_minimum, geography_minimum),
        region.min_cells_per_province,
        region.max_cells_per_province
    )
```

После этого при наличии действительно необходимого override:

```text
if forced_cell_count != null:
    final_count = forced_cell_count
```

---

# 8. Coast factor

Из таблицы:

```text
нет побережья                  1.00
обычное побережье              1.05
бухты и полуострова            1.12
сильно изрезанный берег        1.20
архипелаг                      1.30
```

Это можно определять уже сейчас, потому что берег — часть существующей геометрии провинции.

---

# 9. Shape factor

```text
компактная                     1.00
вытянутая                      1.05
несколько выраженных лопастей  1.12
полуостровы / перешейки        1.18
```

Для автоматического выбора использовать:

```text
aspect_ratio;
compactness;
perimeter_to_area_ratio;
число крупных concavities;
число крупных skeleton branches;
число подтверждённых necks;
число выраженных lobes.
```

---

# 10. Anchor minimum

Координата реальной столицы влияет прежде всего на **форму primary cell**, а не автоматически увеличивает число клеток.

`anchor_minimum` должен приходить из статических проектных данных.

Например:

```text
обычная провинция → 1
метропольное ядро → минимум 4
```

Пример override:

```json
{
  "province:uk:greater_london": {
    "minimum_cell_count": 4,
    "forced_cell_count": null,
    "reason": "metropolitan_core"
  }
}
```

---

# 11. Пример Ла-Коруньи

Из Excel:

```text
регион = Галисия
profile = P3
target = 2100 км²
min = 1
max = 10
```

Площадь:

```text
A ≈ 7950 км²
```

При `K_local = 1.0`:

```text
7950 / 2100 = 3.7857
round = 4
```

Следовательно:

```text
final_cell_count = 4
```

То есть Ла-Корунья **не должна** делиться на 5 зон только потому, что тест Method 5 делал пять.

---

# 12. Пример Большого Лондона

В таблице:

```text
profile = P0
target = 450 км²
min = 4
max = 7
```

Площадь примерно:

```text
1570 км²
```

По площади выходит около 3–4, но `min = 4`, поэтому:

```text
final_count >= 4
```

Именно для этого нужны min/max и статические overrides.

---

# 13. GDScript: ProvinceCellCountResolver

```gdscript
class_name ProvinceCellCountResolver
extends RefCounted


static func resolve_count(
    province: ProvinceData,
    region: RegionData,
    override_data: Dictionary
) -> int:

    var target_area: float = (
        region.target_cell_area_km2
    )

    var coast_factor := (
        CoastComplexityAnalyzer.get_factor(
            province
        )
    )

    var shape_factor := (
        ShapeComplexityAnalyzer.get_factor(
            province
        )
    )

    var local_complexity := (
        coast_factor * shape_factor
    )

    local_complexity = clamp(
        local_complexity,
        0.85,
        1.35
    )

    var raw_count := (
        province.area_km2
        / target_area
        * local_complexity
    )

    var area_count := max(
        1,
        roundi(raw_count)
    )

    var anchor_minimum := 1

    if override_data.has("minimum_cell_count"):
        var value = override_data["minimum_cell_count"]

        if value != null:
            anchor_minimum = max(
                anchor_minimum,
                int(value)
            )

    var geography_minimum := (
        ProvinceGeometryMinimumResolver.resolve(
            province
        )
    )

    var final_count := max(
        area_count,
        anchor_minimum,
        geography_minimum
    )

    final_count = clampi(
        final_count,
        region.min_cells_per_province,
        region.max_cells_per_province
    )

    if override_data.has("forced_cell_count"):
        var forced = override_data["forced_cell_count"]

        if forced != null:
            final_count = int(forced)

    return final_count
```

---

# 14. Почему чистый Method 5 нельзя использовать как финальный N-way алгоритм

Наш тест `Improved Political Claims` визуально дал хорошие границы, но если сделать:

```text
N seed
→ все N одновременно конкурируют
→ winner takes all
```

то при массовом прогоне снова появятся проблемы из аналитических файлов:

- лепестки;
- центральные Y-узлы;
- веерные границы;
- псевдо-Voronoi;
- похожий почерк у разных провинций;
- слишком равномерные сектора.

Поэтому Method 5 нужно сохранить, но **сменить его роль**.

---

# 15. Правильный гибрид

Используем Political Claims как генератор органичной формы **конкретного binary split**, а не как финальное деление всей провинции сразу.

```text
N = CellCountResolver(province)

если N == 1:
    вся провинция = одна клетка

если N >= 2:
    построить primary cell вокруг real_capital_position

остаток
→ выбрать часть для деления
→ создать 24–32 binary Political Claims кандидата
→ проверить кандидаты
→ оценить score
→ выбрать лучший
→ повторять, пока число частей != N
```

Это сочетает:

```text
визуальную органичность Method 5
+
последовательное разбиение из аналитических документов
```

---

# 16. Полный pipeline одной провинции

```text
Province polygon
        ↓
region_id + area_km2
        ↓
regional profile
        ↓
ProvinceCellCountResolver
        ↓
N
        ↓
working raster
        ↓
shape analysis
        ↓
real capital anchor
        ↓
primary cell
        ↓
remaining territory
        ↓
recursive binary claims splits
        ↓
connectivity cleanup
        ↓
sliver/tail cleanup
        ↓
shared borders
        ↓
topological smoothing
        ↓
validator
        ↓
final N cells
```

---

# 17. Рабочий raster

Исходная геометрия остаётся векторной, но генерацию проще выполнять во временной raster-сетке.

Например:

```text
визуальный bbox = 1600 × 800 px
рабочий raster step = 2–6 px
```

Raster существует только во время offline/build генерации.

Финальные клетки затем снова векторизуются.

---

# 18. Что вычислить из формы провинции до генерации

```text
bbox;
area;
perimeter;
centroid;
compactness;
aspect_ratio;
distance transform;
medial skeleton;
significant concavities;
neck candidates;
lobe candidates;
coast segments.
```

Эти признаки не требуют рельефа.

---

# 19. Distance Transform

Для каждой внутренней raster-клетки:

```text
distance_to_outer_border
```

Он нужен для:

- поиска безопасных внутренних anchor;
- определения локальной ширины;
- обнаружения тонких хвостов;
- обнаружения перешейков;
- оценки primary clearance.

---

# 20. Медиальный скелет

Скелет показывает:

- главные оси провинции;
- длинные ответвления;
- полуостровные лопасти;
- узкие переходы;
- хорошие центры будущих подзон.

Он особенно полезен для выбора seed pair следующего binary split.

---

# 21. Primary cell создаётся первой

Если `N >= 2`, первым обязательным объектом является primary cell.

Anchor:

```text
real_capital_position
```

Преобразование:

```text
lon/lat
→ world map coordinates
→ province local coordinates
→ raster cell
```

Если точка после simplify оказалась немного за полигоном, её нужно спроецировать на ближайшую **безопасную внутреннюю** точку, а не заменять случайным seed.

---

# 22. Защитная зона primary anchor

Из анализа Ла-Коруньи:

```text
distance_to_internal_border
>= 0.28 × equivalent_radius
```

где:

```text
R = sqrt(cell_area / PI)
```

Стартовое значение:

```text
PRIMARY_CLEARANCE_FACTOR = 0.28
```

Диапазон для калибровки:

```text
0.25–0.35
```

---

# 23. Primary cell не должна быть кругом

Плохо:

```text
capital
→ круговой buffer
→ клетка
```

Хорошо:

```text
capital core
+
major claims
+
directional bias
+
low-frequency noise
+
shape constraints
```

Это создаёт асимметричную территорию с нормальным внутренним пространством вокруг столицы.

---

# 24. Структура ClaimPoint

```gdscript
class_name ClaimPoint
extends RefCounted

var position: Vector2
var sigma: float
var strength: float
```

Gaussian:

```gdscript
static func gaussian(
    point: Vector2,
    center: Vector2,
    sigma: float
) -> float:

    var d2 := (
        point.distance_squared_to(center)
    )

    return exp(
        -d2 / (2.0 * sigma * sigma)
    )
```

---

# 25. ClaimsZone

```gdscript
class_name ClaimsZone
extends RefCounted

var seed_position: Vector2
var power: float

var direction: Vector2
var direction_strength: float

var core_sigma: float
var core_strength: float

var major_claims: Array[ClaimPoint]
var medium_claims: Array[ClaimPoint]

var macro_noise: FastNoiseLite
var meso_noise: FastNoiseLite
var micro_noise: FastNoiseLite

var area_bias: float = 0.0
```

---

# 26. Major claims

Для primary cell:

```text
2–3 major claims
```

Для обычного binary split:

```text
1–3 major claims на каждую сторону
```

Они создают:

- крупные выступы;
- крупные вдавливания;
- асимметрию;
- смещение общей границы.

---

# 27. Medium claims

```text
2–5
```

Их сила ниже major.

Они отвечают за:

- локальные повороты;
- небольшие вдавливания;
- изменение маршрута фронта.

---

# 28. Claims нельзя ставить по всей провинции полностью случайно

Плохо:

```gdscript
claim.position = random_inside_province()
```

Правильнее:

```text
seed
→ preferred direction
→ ограниченная дистанция
→ candidate
→ проверка mask
```

Например:

```gdscript
var angle_offset := rng.randf_range(-0.9, 0.9)

var direction := (
    zone.direction.rotated(angle_offset)
)

var distance := rng.randf_range(
    min_dimension * 0.10,
    min_dimension * 0.30
)

var claim_position := (
    zone.seed_position
    + direction * distance
)
```

---

# 29. Направленность роста

```gdscript
var angle := rng.randf_range(0.0, TAU)

zone.direction = Vector2(
    cos(angle),
    sin(angle)
)
```

Для клетки:

```gdscript
var delta := position - zone.seed_position

if delta.length_squared() > 0.001:
    score += (
        delta.normalized().dot(zone.direction)
        * zone.direction_strength
    )
```

Это убирает круглые пятна.

---

# 30. Multi-scale noise

Нужно три масштаба:

```text
macro
meso
micro
```

Пример:

```text
macro frequency ≈ 0.008–0.015
meso  frequency ≈ 0.02–0.035
micro frequency ≈ 0.05–0.08
```

Силы:

```text
macro ≈ 4.0–5.5
meso  ≈ 1.5–2.5
micro ≈ 0.2–0.6
```

Главное:

```text
macro > meso >> micro
```

Иначе граница превращается в декоративную пилу.

---

# 31. FastNoiseLite

```gdscript
static func create_noise(
    noise_seed: int,
    frequency: float
) -> FastNoiseLite:

    var noise := FastNoiseLite.new()

    noise.seed = noise_seed
    noise.noise_type = (
        FastNoiseLite.TYPE_SIMPLEX_SMOOTH
    )
    noise.frequency = frequency

    return noise
```

---

# 32. Shape field вместо terrain field

До рельефа можно использовать:

```text
distance_to_border;
distance_to_neck;
concavity influence;
skeleton branch affinity;
lobe membership;
coast relation;
local width.
```

Граница получает бонус, если:

- проходит через сильное сужение;
- отделяет крупную lobe;
- соединяет пару значимых concavities;
- проходит рядом с подтверждённым neck.

Штраф, если:

- режет широкий центр лопасти без причины;
- пересекает длинный полуостров поперёк;
- идёт через protected primary core.

---

# 33. Итоговый Claims score

```text
score =
    core_influence
  + major_claims
  + medium_claims
  + directional_bias
  + macro_noise
  + meso_noise
  + micro_noise
  + shape_affinity
  + area_bias
  - distance_penalty
  - primary_protection_penalty
```

---

# 34. Binary Political Claims split

Каждый шаг делит одну существующую часть **только на две**.

```text
Claims A
vs
Claims B
```

Например:

```text
AAAAAAAAAABBBBBBBBBB
AAAAAAAAAABBBBBBBBBB
AAAAAAAABBBBBBBBBBBB
AAAAAAABBBBBBBBBBBBB
```

Получившийся split не принимается автоматически.

Он идёт в `SplitCandidateValidator` и `SplitCandidateScorer`.

---

# 35. На один split генерировать много вариантов

Стартово:

```text
CANDIDATES_PER_SPLIT = 32
```

Для каждой попытки меняются:

```text
seed pair;
direction;
major claims;
medium claims;
noise seed/offset;
area bias.
```

Выбирается лучший валидный кандидат.

---

# 36. Как выбирать seed pair

Приоритет:

```text
1. отдельная крупная lobe;
2. большой skeleton branch;
3. область за neck;
4. устойчивый interior maximum distance point;
5. weighted farthest point fallback.
```

То есть seed не должен быть просто случайным.

---

# 37. Как выбирать часть, которую делить следующей

Пока:

```text
parts.size() < final_cell_count
```

для каждой части считаем `split_need`:

```text
split_need =
    area_excess
  + shape_complexity
  + lobe_count
  + skeleton_branch_count
  + aspect_ratio_penalty
```

Делим часть с максимальной потребностью.

---

# 38. Площадь не должна доминировать

Приоритет из аналитических документов:

```text
1. геометрический/географический смысл;
2. нормальная форма;
3. безопасность primary cell;
4. площадь.
```

Не нужно получать строго:

```text
20 / 20 / 20 / 20 / 20
```

Нормальный результат:

```text
17 / 18 / 19 / 21 / 25
```

если формы хорошие.

---

# 39. SplitCandidate score

Адаптированный под текущую стадию без рельефа:

```text
split_score =

    3.0 × shape_feature_score
  + 2.5 × primary_clearance_score
  + 2.0 × lobe_separation_score
  + 1.8 × compactness_gain
  + 1.2 × area_balance_score

  - 3.5 × primary_proximity_penalty
  - 3.0 × peninsula_damage_penalty
  - 2.5 × stripe_penalty
  - 2.5 × sliver_penalty
  - 2.0 × parallel_border_penalty
  - 1.5 × excessive_smoothness_penalty
  - 2.0 × acute_wedge_penalty
```

Это стартовые веса, а не окончательная истина.

---

# 40. Shape feature score

Оценивает:

- совпадение с neck;
- отделение целой lobe;
- логичную пару concavities;
- короткость границы относительно разделённых площадей;
- логичную точку выхода к внешнему контуру.

---

# 41. Primary clearance

Для primary cell:

```text
distance(anchor, nearest_internal_border)
>= 0.28 × equivalent_radius
```

Если кандидат проходит внутри protected core:

```text
candidate = invalid
```

или получает практически запретительный penalty.

---

# 42. Aspect ratio

Стартовые ограничения:

```text
обычная клетка:
aspect_ratio <= 3.0

естественно вытянутая:
aspect_ratio <= 4.0
```

Выше 3.0 — только если форма действительно это объясняет.

---

# 43. Minimum width

Стартовый ориентир из анализа:

```text
minimum_width >= 0.18 × sqrt(area_km2)
```

Порог нужно калибровать.

В raster лучше считать устойчивую ширину через distance transform, а не один случайный самый узкий пиксель.

---

# 44. Stripe penalty

Плохой результат:

```text
AAAA|BBBB|CCCC|DDDD
AAAA|BBBB|CCCC|DDDD
AAAA|BBBB|CCCC|DDDD
```

Если две соседние внутренние границы имеют:

```text
разницу направления < 15°
```

и идут почти параллельно:

```text
> 50% длины
```

давать штраф.

---

# 45. Sliver/tail penalty

Плохо:

```text
████████████████
            ██
             ██
              █
```

Штрафовать:

- длинный тонкий хвост;
- клетку-щель;
- узкий коридор;
- длинный острый клин.

---

# 46. Acute wedge

Не допускать длинных искусственных клиньев с внутренним углом около:

```text
< 25–30°
```

Мелкие острые углы естественного внешнего берега не являются ошибкой внутреннего деления.

---

# 47. Связность

Каждая клетка должна быть связна по 4-соседям рабочего raster.

После binary split:

```text
Flood Fill(A)
Flood Fill(B)
```

Если одна сторона распалась:

```text
candidate = invalid
```

Лучше отвергнуть плохой кандидат, чем бесконечно ремонтировать его cleanup-ом.

---

# 48. Анклавы

Для обычной связной суши:

```text
одна клетка = один connected component
```

Исключение — реальные островные компоненты исходной провинции, для которых должна быть отдельная логика MultiPolygon.

---

# 49. Внутренние узлы

Последовательное binary splitting уже резко снижает центральные звёзды.

Нельзя специально создавать:

```text
degree-4 cross
```

или:

```text
N лепестков вокруг одного центра
```

Допустимы естественные T-соединения.

---

# 50. Общую границу хранить один раз

Нельзя независимо сглаживать два соседних полигона.

Правильно:

```text
extract shared border
→ smooth shared border once
→ обе клетки используют один edge
```

Иначе появятся щели и overlap.

---

# 51. Характер линии

Плохой подход:

```text
прямая
→ случайный offset каждой точки
→ мелкая змея
```

Хороший:

```text
4–8 крупных опорных сегментов
→ 2–5 крупных поворотов
→ мягкое топологическое сглаживание
```

Граница должна быть асимметричной, местами спокойной, местами изгибающейся.

---

# 52. Обработка разных N

## N = 1

```text
вся провинция = одна клетка
```

## N = 2

```text
primary cell
+
остаток
```

Одна внутренняя граница.

## N = 3

```text
primary
+
остаток, разделённый один раз
```

Не нужен один общий Y-узел.

## N = 4

Для Ла-Коруньи логика:

```text
primary
→ западная прибрежная/лопастная часть
→ оставшийся interior делится ещё раз
```

## N >= 5

Алгоритм тот же:

```text
while parts.size() < N:
    part = choose_best_part_to_split()
    split = find_best_binary_claims_split(part)
    replace(part, split.A, split.B)
```

Поэтому один генератор работает с 1–16 клетками без отдельной логики «под 5».

---

# 53. Главный ProvinceCellGenerator

```gdscript
class_name ProvinceCellGenerator
extends RefCounted


static func generate_province_cells(
    province: ProvinceData,
    region: RegionData,
    override_data: Dictionary,
    generator_seed: int
) -> Array[GeneratedCell]:

    var rng := RandomNumberGenerator.new()
    rng.seed = generator_seed

    var target_count := (
        ProvinceCellCountResolver.resolve_count(
            province,
            region,
            override_data
        )
    )

    var context := (
        ProvinceGenerationContextBuilder.build(
            province
        )
    )

    if target_count == 1:
        return [
            GeneratedCell.from_full_province(
                province,
                context.capital_anchor
            )
        ]

    var primary_result := (
        PrimaryCellGenerator.generate(
            context,
            region,
            rng
        )
    )

    if not primary_result.is_valid:
        return []

    var parts: Array[CellPart] = []

    parts.append(
        primary_result.primary_part
    )

    for p in primary_result.remaining_parts:
        parts.append(p)

    while parts.size() < target_count:

        var part_index := (
            SplitPartSelector.choose_part(
                parts,
                region.target_cell_area_km2
            )
        )

        if part_index < 0:
            break

        var split_result := (
            ClaimsBinarySplitGenerator.find_best_split(
                parts[part_index],
                context,
                region,
                rng
            )
        )

        if not split_result.is_valid:
            break

        parts.remove_at(part_index)
        parts.append(split_result.part_a)
        parts.append(split_result.part_b)

    CellConnectivityCleaner.clean(parts)
    CellTailCleaner.clean(parts)

    var topology := (
        CellTopologyBuilder.build(
            parts,
            context
        )
    )

    CellBoundarySmoother.smooth(
        topology,
        context
    )

    var validation := (
        ProvinceCellValidator.validate(
            province,
            parts,
            topology,
            region,
            context
        )
    )

    if not validation.is_valid:
        ProvinceCellDebugWriter.write(
            province,
            parts,
            topology,
            validation,
            context
        )

    return GeneratedCellExporter.build_cells(
        province,
        parts,
        topology,
        context
    )
```

---

# 54. ClaimsBinarySplitGenerator

```gdscript
class_name ClaimsBinarySplitGenerator
extends RefCounted


const CANDIDATE_COUNT := 32


static func find_best_split(
    part: CellPart,
    context: ProvinceGenerationContext,
    region: RegionData,
    rng: RandomNumberGenerator
) -> SplitResult:

    var best_result := SplitResult.invalid()
    var best_score := -INF

    for attempt in CANDIDATE_COUNT:

        var candidate := generate_candidate(
            part,
            context,
            region,
            rng
        )

        if not candidate.is_valid:
            continue

        if not SplitCandidateValidator.validate(
            candidate,
            context,
            region
        ):
            continue

        var score := SplitCandidateScorer.score(
            candidate,
            context,
            region
        )

        if score > best_score:
            best_score = score
            best_result = candidate

    return best_result
```

---

# 55. Баланс площади внутри binary split

Не нужно всегда стремиться к 50/50.

Например:

```text
part = 5000 км²
target = 2100 км²
```

Нормальный split:

```text
2100 + 2900
```

может быть лучше, чем:

```text
2500 + 2500
```

Особенно если геометрия одной лопасти естественно даёт одну из этих площадей.

---

# 56. Распределение будущего cell budget по веткам

Для больших `N` полезно не просто делить часть, а оценивать, сколько будущих клеток должно остаться в каждой ветке.

Например:

```text
остаток должен дать 6 клеток
```

и имеет две крупные лопасти:

```text
A ≈ 1/3 площади
B ≈ 2/3 площади
```

Можно задать:

```text
A budget = 2
B budget = 4
```

Тогда следующие splits будут намного естественнее.

---

# 57. Детерминизм

Одинаковые исходные данные должны давать одинаковые клетки.

Seed формировать из:

```text
world_seed
+
province_id
+
generator_version
```

Например:

```gdscript
static func make_province_seed(
    world_seed: int,
    province_id: String,
    generator_version: int
) -> int:

    return hash(
        str(world_seed)
        + ":"
        + province_id
        + ":"
        + str(generator_version)
    )
```

---

# 58. Версия генератора

Хранить:

```text
land_cell_generator_version
```

При изменении алгоритма:

```text
3 → 4
```

можно точно отделить старые результаты от новых.

---

# 59. Validator

Обязательные проверки.

## Топология

```text
ровно N клеток;
каждая связна;
нет overlap;
нет holes;
union(cells) == province;
общие границы совпадают;
нет adjacency только через точку.
```

## Primary

```text
capital anchor внутри primary;
anchor не прижат к границе;
primary имеет нормальную глубину;
primary не узкая береговая полоска;
primary не идеальный круг.
```

## Геометрия

```text
aspect_ratio;
minimum_width;
compactness;
sliver;
long_tail;
acute_wedge;
parallel_border;
stripe;
excessive_smoothness.
```

## Площадь

Ориентир из документов:

```text
обычный регион:
0.55–1.65 × target

редкий/frontier:
0.40–2.20 × target
```

Это валидатор диапазона, а не команда сделать все клетки одинаковыми.

---

# 60. Debug output

Для каждой проблемной провинции сохранять:

```text
01_mask.png
02_capital_anchor.png
03_primary_protected_core.png
04_distance_transform.png
05_skeleton.png
06_concavities.png
07_necks.png
08_lobes.png
09_split_candidates.png
10_selected_splits.png
11_final_cells.png
validation.json
```

`validation.json`:

```json
{
  "province_id": "province:spain:la_coruna",
  "expected_cell_count": 4,
  "actual_cell_count": 4,
  "profile_id": "P3",
  "target_cell_area_km2": 2100,
  "errors": [],
  "warnings": []
}
```

---

# 61. Сохранять причину каждого split

```json
{
  "split_id": "province:spain:la_coruna:split:02",
  "basis": [
    "shape_claims",
    "lobe_separation",
    "neck_alignment"
  ],
  "score": 8.41,
  "scores": {
    "shape_feature": 0.82,
    "primary_clearance": 1.0,
    "lobe_separation": 0.73,
    "area_balance": 0.61,
    "stripe_penalty": 0.0,
    "sliver_penalty": 0.0
  }
}
```

Это очень поможет понимать, почему генератор провёл конкретную границу именно там.

---

# 62. Рекомендуемая структура файлов Godot

```text
res://scripts/map_generation/land_cells/

    data/
        land_cell_generation_profile.gd
        region_cell_rules.gd
        province_cell_override.gd

    count/
        province_cell_count_resolver.gd
        coast_complexity_analyzer.gd
        shape_complexity_analyzer.gd

    geometry/
        province_generation_context.gd
        province_mask_builder.gd
        distance_transform_builder.gd
        medial_skeleton_builder.gd
        concavity_detector.gd
        neck_detector.gd
        lobe_detector.gd

    primary/
        primary_cell_generator.gd
        capital_anchor_projector.gd

    claims/
        claim_point.gd
        claims_zone.gd
        claims_zone_factory.gd
        claims_score_calculator.gd

    split/
        split_part_selector.gd
        split_seed_selector.gd
        claims_binary_split_generator.gd
        split_candidate_validator.gd
        split_candidate_scorer.gd

    cleanup/
        cell_connectivity_cleaner.gd
        cell_tail_cleaner.gd

    topology/
        cell_topology_builder.gd
        shared_border_builder.gd
        cell_boundary_smoother.gd

    validation/
        province_cell_validator.gd
        cell_geometry_metrics.gd

    debug/
        province_cell_debug_writer.gd

    export/
        generated_cell.gd
        generated_cell_exporter.gd

    province_cell_generator.gd
```

---

# 63. GeneratedCell

```gdscript
class_name GeneratedCell
extends RefCounted

var id: String
var province_id: String

var is_primary: bool

var polygon: PackedVector2Array
var area_km2: float

var neighbor_ids: PackedStringArray
var shared_border_ids: PackedStringArray

var generation_metadata: Dictionary
```

Клетка должна хранить непосредственного родителя:

```text
province_id
```

Не нужно дублировать `region_id` в каждой клетке, потому что иерархия:

```text
cell → province → region → macroregion → ...
```

---

# 64. Порядок реализации

## Этап 1. Конвертер Excel → JSON

Экспортировать:

```text
Классы плотности
→ land_cell_generation_profiles.json

Мировые регионы v1 / Иберия
→ region land_cell_generation data
```

## Этап 2. area_km2

У 100% провинций должна быть финальная площадь после всех геометрических правок.

## Этап 3. region_id

У 100% провинций должен быть регион.

## Этап 4. Предпроход CellCountResolver

Сформировать отчёт:

```text
province_id
region_id
area_km2
profile_id
target
coast_factor
shape_factor
area_count
min
max
final_count
override
```

До генерации геометрии уже должно быть известно ожидаемое число клеток всего мира.

## Этап 5. Shape analysis

Реализовать:

```text
mask;
distance transform;
skeleton;
concavities;
necks;
lobes.
```

## Этап 6. Primary cell

Первый тест — Ла-Корунья.

## Этап 7. Binary Political Claims

Только две стороны на один split.

## Этап 8. 32 candidate splits

Выбрать лучший по score.

## Этап 9. Recursive controller

Делить до `final_cell_count`.

## Этап 10. Shared topology

Общие границы хранятся один раз.

## Этап 11. Validator + debug

Только после прохождения тестовых провинций запускать мир.

---

# 65. Первый milestone

Сначала не делать весь мир.

Сделать:

```text
ProvinceCellCountResolver
+
Ла-Корунья
+
N = 4 из таблицы
+
real capital primary anchor
+
primary cell
+
binary claims splitting
+
validator
```

Критерии:

```text
ровно 4 клетки;
primary содержит anchor;
нет central star;
нет degree-4 cross;
нет вертикальных полос;
нет тонких хвостов;
нет holes;
нет overlap;
primary не выглядит кругом.
```

---

# 66. После Ла-Коруньи проверить

```text
1. Бретань;
2. Большой Лондон;
3. компактную внутреннюю равнинную провинцию;
4. вытянутую провинцию;
5. островную/MultiPolygon провинцию;
6. крупную редкую провинцию.
```

Только после этого — мировой прогон.

---

# 67. Стартовые параметры Claims

```text
major_claim_count = 1–3
medium_claim_count = 2–5

direction_strength = 0.45–0.65

macro_noise_strength = 4.0–5.5
meso_noise_strength = 1.5–2.5
micro_noise_strength = 0.2–0.6

candidate_count = 32
cleanup_passes = 1–2
smooth_passes = 2–4
```

Параметры нужно нормализовать относительно размера рабочего raster, а не хранить абсолютные пиксели для всего мира.

---

# 68. Чего не делать

## Не делать

```text
ZONE_COUNT = 5
```

внутри генератора.

## Не использовать Excel runtime

Только JSON/binary.

## Не использовать N-way Claims как финальную геометрию

Только binary split внутри последовательного алгоритма.

## Не использовать несуществующий рельеф

Никаких случайных «mountain factor» ради имитации географии.

## Не считать, что игровой город уже существует

Используется только реальная столица как географический anchor.

## Не выравнивать площади любой ценой

Форма важнее идеального равенства.

## Не сглаживать соседние полигоны независимо

Сглаживать общий edge один раз.

## Не ремонтировать заведомо плохой candidate бесконечным cleanup

Плохой candidate проще отвергнуть и сгенерировать следующий.

---

# 69. Финальная схема

```text
              REGIONAL TABLE
        target / min / max / profile
                     │
                     ▼
              PROVINCE AREA
              + region_id
                     │
                     ▼
          CELL COUNT RESOLVER
                     │
                     │ N
                     ▼
         PROVINCE SHAPE CONTEXT
 mask / coast / skeleton / necks / lobes
          real capital anchor
                     │
                     ▼
               PRIMARY CELL
               claims field
                     │
                     ▼
            remaining territory
                     │
                     ▼
          SELECT PART TO SPLIT
                     │
                     ▼
        32 BINARY CLAIMS CANDIDATES
                     │
                     ▼
             VALIDATE + SCORE
                     │
                     ▼
                 BEST SPLIT
                     │
                     ▼
              parts.size == N ?
               │            │
              no           yes
               │            │
               └──────┐     ▼
                      │  TOPOLOGY
                      │     │
                      └─────┘
                            ▼
                     SHARED BORDERS
                            │
                            ▼
                       SMOOTHING
                            │
                            ▼
                        VALIDATOR
                            │
                            ▼
                       FINAL CELLS
```

---

# 70. Итоговое решение

Для проекта предлагается зафиксировать следующую архитектуру:

```text
1. Региональная таблица определяет target/min/max.
2. Площадь провинции определяет базовое число клеток.
3. Форма и берег дают только допустимые локальные поправки.
4. Ручной override применяется редко.
5. Получаем final_cell_count.
6. Реальная столица провинции становится anchor primary cell.
7. Primary cell формируется первой.
8. Improved Political Claims используется для органичной формы.
9. Но не как одновременный N-way partition.
10. Остаток делится последовательными binary claims splits.
11. На каждый split генерируется много кандидатов.
12. Кандидаты проходят строгую валидацию и score.
13. Лучший split применяется.
14. Процесс повторяется до ровно N клеток.
15. Общие границы строятся один раз и сглаживаются топологически.
16. Финальный validator проверяет число, связность, площадь и форму.
```

Это сохраняет лучшие стороны Method 5:

```text
неровные политически похожие границы;
крупные фронты;
выступы;
вогнутости;
перешейки;
асимметрию;
```

но убирает главный недостаток:

```text
механическое одновременное деление провинции на N лепестков.
```

И главное — один и тот же генератор автоматически работает для любого числа клеток, рассчитанного по региональной таблице:

```text
1 ... region.max_cells_per_province
```
