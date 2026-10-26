@tool
extends EditorPlugin

var _dock: Control


func _enter_tree() -> void:
	var panel: Control = load(
		"res://addons/asset_library/asset_dock.tscn").instantiate()
	_dock = panel
	add_control_to_dock(DOCK_SLOT_LEFT_UR, panel)


func _exit_tree() -> void:
	if is_instance_valid(_dock):
		remove_control_from_docks(_dock)
		_dock.free()
