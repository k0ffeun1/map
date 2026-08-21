extends Camera2D
## Camera controller for the world map.
##
## Handles:
##  - WASD / arrow-key panning (smooth)
##  - Right / middle mouse-button drag panning
##  - Mouse-wheel zoom (towards cursor)
##  - R  -> reset to map center
##  - ESC -> quit the game
##
## The map bounds are supplied by MapController via set_map_bounds().

# --- Tunables -----------------------------------------------------------------
@export var pan_speed: float = 1200.0          ## Keyboard pan speed (px/sec at zoom 1).
@export var pan_smoothing: float = 12.0        ## Higher = snappier keyboard panning.
@export var zoom_step: float = 0.15            ## Fraction of zoom change per wheel notch.
@export var zoom_min: float = 0.1              ## Most zoomed-out (small numbers = far).
@export var zoom_max: float = 8.0              ## Most zoomed-in (~z7 tile detail + небольшой запас).
@export var zoom_smoothing: float = 12.0       ## Higher = snappier zoom.

# --- State --------------------------------------------------------------------
var _map_rect: Rect2 = Rect2()                 ## World-space bounds of the map sprite.
var _has_bounds: bool = false

var _target_zoom: Vector2 = Vector2.ONE
var _target_position: Vector2 = Vector2.ZERO

var _dragging: bool = false


func _ready() -> void:
	make_current()
	_target_zoom = zoom
	_target_position = position


## Called by MapController once the map size is known.
func set_map_bounds(rect: Rect2) -> void:
	_map_rect = rect
	_has_bounds = true
	reset_to_center()


func reset_to_center() -> void:
	if _has_bounds:
		_target_position = _map_rect.get_center()
		# Вписать всю карту в окно (показать весь мир целиком).
		var vp := get_viewport_rect().size
		var fit := minf(vp.x / _map_rect.size.x, vp.y / _map_rect.size.y)
		_target_zoom = Vector2(fit, fit) * 1.02  # чуть плотнее, без чёрных полей
	else:
		_target_position = Vector2.ZERO
		_target_zoom = Vector2.ONE
	# Snap immediately so R feels instant.
	position = _target_position
	zoom = _target_zoom


func _unhandled_input(event: InputEvent) -> void:
	# --- Quit / reset ---
	if event.is_action_pressed("reset_camera"):
		reset_to_center()
	if event is InputEventKey and event.pressed and event.keycode == KEY_ESCAPE:
		get_tree().quit()
	if event is InputEventKey and event.pressed and not event.echo:
		if event.physical_keycode == KEY_KP_ADD:
			zoom_by_factor_at_center(1.0 + zoom_step)
			get_viewport().set_input_as_handled()
		elif event.physical_keycode == KEY_KP_SUBTRACT:
			zoom_by_factor_at_center(1.0 - zoom_step)
			get_viewport().set_input_as_handled()

	# --- Mouse wheel zoom ---
	if event is InputEventMouseButton and event.pressed:
		if event.button_index == MOUSE_BUTTON_WHEEL_UP:
			_zoom_at(get_global_mouse_position(), 1.0 + zoom_step)
		elif event.button_index == MOUSE_BUTTON_WHEEL_DOWN:
			_zoom_at(get_global_mouse_position(), 1.0 - zoom_step)

	# --- Drag with right / middle mouse button ---
	if event is InputEventMouseButton:
		if event.button_index == MOUSE_BUTTON_RIGHT or event.button_index == MOUSE_BUTTON_MIDDLE:
			_dragging = event.pressed

	if event is InputEventMouseMotion and _dragging:
		# Move opposite to the mouse, scaled by current zoom so drag feels 1:1.
		_target_position -= event.relative / zoom
		position = _target_position   # Follow the cursor instantly while dragging.
		_target_position = _clamp_to_bounds(_target_position)
		position = _target_position


## Целевой зум (куда едет анимация). TileMapViewer выбирает LOD по нему,
## а не по промежуточному сглаженному zoom — иначе LOD дребезжит при анимации.
func get_target_zoom() -> float:
	return _target_zoom.x


func get_zoom_min() -> float:
	return zoom_min


func get_zoom_max() -> float:
	return zoom_max


func set_target_zoom_at_center(new_zoom: float) -> void:
	_set_target_zoom_at(_target_position, new_zoom)


## Instantly move to a known world-space point; used by focused map tools.
func focus_at(world_position: Vector2, target_zoom: float) -> void:
	_target_position = _clamp_to_bounds(world_position)
	_target_zoom = Vector2.ONE * clampf(target_zoom, zoom_min, zoom_max)
	position = _target_position
	zoom = _target_zoom


func zoom_by_factor_at_center(factor: float) -> void:
	set_target_zoom_at_center(_target_zoom.x * factor)


func _zoom_at(world_anchor: Vector2, factor: float) -> void:
	_set_target_zoom_at(world_anchor, _target_zoom.x * factor)


func _set_target_zoom_at(world_anchor: Vector2, requested_zoom: float) -> void:
	var old_zoom := _target_zoom.x
	var new_zoom := clampf(requested_zoom, zoom_min, zoom_max)
	_target_zoom = Vector2(new_zoom, new_zoom)

	# Keep the world point under the cursor stationary during zoom.
	var mouse_offset := world_anchor - _target_position
	_target_position = world_anchor - mouse_offset * (old_zoom / new_zoom)
	_target_position = _clamp_to_bounds(_target_position)


func _process(delta: float) -> void:
	# --- Keyboard panning ---
	# Читаем ФИЗИЧЕСКИЕ коды клавиш напрямую (is_physical_key_pressed), а не
	# через InputMap-экшены (pan_left/right/up/down) — на некоторых системах
	# смена раскладки (напр. на русскую) ломала распознавание WASD через
	# экшены, даже несмотря на physical_keycode в биндинге. Прямой опрос
	# физической клавиши по её позиции на клавиатуре гарантированно не
	# зависит от текущей раскладки ввода.
	var dir := Vector2.ZERO
	dir.x = float(Input.is_physical_key_pressed(KEY_D) or Input.is_physical_key_pressed(KEY_RIGHT)) \
		- float(Input.is_physical_key_pressed(KEY_A) or Input.is_physical_key_pressed(KEY_LEFT))
	dir.y = float(Input.is_physical_key_pressed(KEY_S) or Input.is_physical_key_pressed(KEY_DOWN)) \
		- float(Input.is_physical_key_pressed(KEY_W) or Input.is_physical_key_pressed(KEY_UP))
	if dir != Vector2.ZERO:
		# Divide by zoom so panning speed feels consistent at any zoom level.
		_target_position += dir.normalized() * pan_speed * delta / zoom.x

	_target_position = _clamp_to_bounds(_target_position)

	# Smoothly approach the targets.
	position = position.lerp(_target_position, clampf(pan_smoothing * delta, 0.0, 1.0))
	zoom = zoom.lerp(_target_zoom, clampf(zoom_smoothing * delta, 0.0, 1.0))


## Keep the camera so the viewport never shows beyond the map edges.
func _clamp_to_bounds(pos: Vector2) -> Vector2:
	if not _has_bounds:
		return pos

	var view_size := get_viewport_rect().size / _target_zoom
	var half := view_size * 0.5

	var min_x := _map_rect.position.x + half.x
	var max_x := _map_rect.position.x + _map_rect.size.x - half.x
	var min_y := _map_rect.position.y + half.y
	var max_y := _map_rect.position.y + _map_rect.size.y - half.y

	# If the map is smaller than the viewport on an axis, center it there.
	if min_x > max_x:
		pos.x = _map_rect.get_center().x
	else:
		pos.x = clampf(pos.x, min_x, max_x)

	if min_y > max_y:
		pos.y = _map_rect.get_center().y
	else:
		pos.y = clampf(pos.y, min_y, max_y)

	return pos
