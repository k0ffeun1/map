extends "res://scripts/HistoricalHierarchyWorldViewerV3.gd"
## Compatibility entry point kept for Main.tscn.
## Actual X/C/V/B implementation is HistoricalHierarchyWorldViewerV3.gd.
## Z/F6 also close the active hierarchy mode, so map modes never overlap.

func _input(event: InputEvent) -> void:
	var key := event as InputEventKey
	if key != null and key.pressed and not key.echo:
		var code := key.physical_keycode if key.physical_keycode != 0 else key.keycode
		if code == KEY_Z or code == KEY_F6:
			if not get_active_mode().is_empty():
				set_active_mode("")
			# Do not mark handled: Z/F6 owner must still receive the same event.
			return
	super._input(event)
