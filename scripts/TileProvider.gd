class_name TileProvider
extends RefCounted
## Базовый класс провайдера тайлов (один слой карты).
##
## Схема "slippy map": на уровне z сетка мира = 2^z × 2^z тайлов;
## тайл (x, y) покрывает нормализованную область
## [x/2^z, (x+1)/2^z) × [y/2^z, (y+1)/2^z) по всему миру.
##
## Наследники переопределяют _render(z, x, y) -> Image.
## Тайлы кэшируются по ключу "z/x/y".

const GEN_PX := 64  ## Внутреннее разрешение генерируемого тайла (px). Меньше = быстрее.

var _cache: Dictionary = {}


## Единый интерфейс для движка. У процедурных слоёв тайл готов сразу (синхронно).
## Онлайн-провайдер переопределяет это и возвращает null, пока тайл качается.
func request_tile(z: int, x: int, y: int) -> Texture2D:
	return get_tile_texture(z, x, y)


## Текстура тайла (кэшируется). Не переопределять — переопределяйте _render().
func get_tile_texture(z: int, x: int, y: int) -> Texture2D:
	var key := "%d/%d/%d" % [z, x, y]
	if _cache.has(key):
		return _cache[key]
	var tex := ImageTexture.create_from_image(_render(z, x, y))
	_cache[key] = tex
	return tex


## Переопределяемый метод: рисует один тайл. По умолчанию — прозрачный.
func _render(_z: int, _x: int, _y: int) -> Image:
	return Image.create(GEN_PX, GEN_PX, false, Image.FORMAT_RGBA8)


## Нормализованные мировые координаты (u, v в 0..1) центра пикселя тайла.
static func pixel_uv(z: int, x: int, y: int, px: int, py: int) -> Vector2:
	var per_axis := float(1 << z)
	return Vector2(
		(x + (px + 0.5) / GEN_PX) / per_axis,
		(y + (py + 0.5) / GEN_PX) / per_axis)
