class_name SeaLabelsLayer
extends Node2D
## Подписи морей/океанов/проливов поверх карты (слой "Моря", клавиша 6).
##
## Технически НЕ тайловый слой (в отличие от остальных): подписей мало
## (~300 на весь мир из Natural Earth), поэтому все создаются один раз при
## setup() и просто показываются/прячутся вместе со слоем "Моря". Каждый
## кадр каждой подписи выставляется individual scale = 1/zoom камеры —
## так текст остаётся константного размера на экране при любом зуме, а
## position (мировая точка) не трогается, поэтому позиция не съезжает
## при панорамировании (см. SeaLabelNode.gd).

var _camera: Camera2D


## labels: [{"name","cla","pos"}] из SeaBorderTileProvider.get_labels().
func setup(labels: Array, camera: Camera2D) -> void:
	_camera = camera
	for entry in labels:
		var node := SeaLabelNode.new()
		node.position = entry["pos"]
		node.z_index = 100  # поверх всех тайловых слоёв
		add_child(node)
		node.setup(entry["name"], _font_size_for(entry.get("cla", "")))


## Разные "ранги" объектов — океаны/крупные моря крупнее подписаны, чем
## узкие проливы/заливы, как на обычных атласах.
func _font_size_for(cla: String) -> int:
	match cla:
		"ocean":
			return 26
		"sea":
			return 16
		_:
			return 12


func _process(_delta: float) -> void:
	if not is_instance_valid(_camera):
		return
	var s := Vector2.ONE / maxf(0.0001, _camera.zoom.x)
	for child in get_children():
		child.scale = s
