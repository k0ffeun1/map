class_name SolidColorTileProvider
extends TileProvider
## Черновой прототип слоя "V" (план в done.md/чате: подложка океан+глубины,
## всегда снизу стопки слоёв). Этап 1 — просто ОДИН плоский цвет на весь мир,
## без всякой геометрии (не читает world_ocean.json/provinces.json). Каждый
## тайл на любом z/x/y — один и тот же цвет, поэтому кэшировать по z/x/y
## незачем: одна текстура 1x1 переиспользуется на все тайлы сразу.

var _color: Color
var _img: Image
var _tex: ImageTexture


func _init(color: Color) -> void:
	_color = color
	_img = Image.create(1, 1, false, Image.FORMAT_RGBA8)
	_img.set_pixel(0, 0, _color)
	_tex = ImageTexture.create_from_image(_img)


func request_tile(_z: int, _x: int, _y: int) -> Texture2D:
	return _tex


## Живая смена цвета — все уже созданные Sprite2D делят ОДИН и тот же _tex
## (см. докстринг класса), поэтому обновление текстуры на месте (не создание
## новой) сразу применяется ко всем видимым тайлам без пересоздания спрайтов.
func set_color(color: Color) -> void:
	_color = color
	_img.set_pixel(0, 0, _color)
	_tex.update(_img)
