@tool
extends SceneTree

## Creates the editable base layer for the Province Map Builder laboratory.
## Further child layers are intentionally created in the plugin UI so their
## seed, relaxation and shape can be judged visually rather than hard-coded.

const MAP_SCRIPT = preload("res://addons/province_map_builder/province_map.gd")
const OUTLINE_PATH = "res://assets/province_map_builder/province_2848_outline.png"
const RESOURCE_PATH = "res://assets/province_map_builder/lacoruna_fantasy_admin2.tres"


func _init() -> void:
	call_deferred("_build")


func _build() -> void:
	var image := Image.load_from_file(OUTLINE_PATH)
	if image == null or image.is_empty():
		push_error("Province Builder Lab: outline image could not be loaded")
		quit(1)
		return
	var bitmap := BitMap.new()
	bitmap.create_from_image_alpha(image)
	var polygons: Array[PackedVector2Array] = bitmap.opaque_to_polygons(
		Rect2(Vector2.ZERO, bitmap.get_size()))
	if polygons.is_empty():
		push_error("Province Builder Lab: outline contains no opaque pixels")
		quit(1)
		return
	var province_map = MAP_SCRIPT.new()
	province_map.initialize_from_image(polygons, bitmap.get_size())
	var error := ResourceSaver.save(province_map, RESOURCE_PATH)
	if error != OK:
		push_error("Province Builder Lab: failed to save resource (%d)" % error)
		quit(1)
		return
	print("Province Builder Lab: base map created from ", OUTLINE_PATH)
	quit()
