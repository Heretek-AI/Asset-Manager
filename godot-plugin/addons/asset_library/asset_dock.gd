@tool
extends VBoxContainer
## Dock panel: search the remote library, download into res://.

const CONFIG_PATH := "user://asset_library.cfg"
const Client := preload("res://addons/asset_library/asset_client.gd")

var _items: Array = []
var _http: HTTPRequest
var _dl: HTTPRequest
var _thumb: HTTPRequest
var _dl_name: String = ""
var _url_field: LineEdit
var _token_field: LineEdit
var _query_field: LineEdit
var _go_button: Button
var _results: ItemList
var _preview: TextureRect
var _download_button: Button


func _ready() -> void:
	_http = HTTPRequest.new()
	add_child(_http)
	_http.request_completed.connect(_on_list_done)
	_dl = HTTPRequest.new()
	add_child(_dl)
	_dl.request_completed.connect(_on_blob_done)
	_thumb = HTTPRequest.new()
	add_child(_thumb)
	_thumb.request_completed.connect(_on_thumb_done)
	# Plain relative paths, not %-unique names: % resolution depends on
	# scene-owner bookkeeping that is absent when the panel is instanced
	# outside the editor (headless probes, runtime tools).
	_url_field = get_node("URL") as LineEdit
	_token_field = get_node("Token") as LineEdit
	_query_field = get_node("SearchRow/Query") as LineEdit
	_go_button = get_node("SearchRow/Go") as Button
	_results = get_node("Results") as ItemList
	_preview = get_node("Preview") as TextureRect
	_download_button = get_node("Download") as Button
	_go_button.pressed.connect(_on_search)
	_results.item_selected.connect(_on_preview_index)
	_download_button.pressed.connect(_on_download)
	_load_config()


func _load_config() -> void:
	var cfg := ConfigFile.new()
	if cfg.load(CONFIG_PATH) == OK:
		_url_field.text = str(cfg.get_value("server", "url", ""))
		_token_field.text = str(cfg.get_value("server", "token", ""))


func _save_config() -> void:
	var cfg := ConfigFile.new()
	cfg.set_value("server", "url", _url_field.text)
	cfg.set_value("server", "token", _token_field.text)
	cfg.save(CONFIG_PATH)


func _api(path: String) -> String:
	return _url_field.text.strip_edges().trim_suffix("/") + path


func _auth() -> PackedStringArray:
	return PackedStringArray(
		["Authorization: Bearer " + _token_field.text])


func _on_search() -> void:
	_save_config()
	var url := Client.search_url(
		_api("/api/v1/assets"), {"q": _query_field.text})
	if _http.request(url, _auth()) != OK:
		push_error("asset-library: search request failed to start")


func _on_list_done(result: int, _code: int, _headers: PackedStringArray,
		body: PackedByteArray) -> void:
	if result != HTTPRequest.RESULT_SUCCESS:
		push_error("asset-library: search failed")
		return
	_items = Client.parse_assets(body.get_string_from_utf8())
	_results.clear()
	for item: Variant in _items:
		_results.add_item(str((item as Dictionary).get("name", "?")))


func _on_download() -> void:
	var selected: PackedInt32Array = _results.get_selected_items()
	if selected.is_empty():
		return
	var item: Dictionary = _items[selected[0]]
	_dl_name = str(item.get("name", "download.bin"))
	var url := _api("/api/v1/assets/%d/blob" % int(item.get("id", 0)))
	if _dl.request(url, _auth()) != OK:
		push_error("asset-library: download request failed to start")


func _on_preview_index(index: int) -> void:
	if index < 0 or index >= _items.size():
		return
	var item: Dictionary = _items[index]
	var url := _api("/api/v1/assets/%d/thumbnail" % int(item.get("id", 0)))
	if _thumb.request(url, _auth()) != OK:
		push_error("asset-library: thumbnail request failed to start")


func _on_thumb_done(result: int, code: int, _headers: PackedStringArray,
		body: PackedByteArray) -> void:
	if result != HTTPRequest.RESULT_SUCCESS or code != 200:
		_preview.texture = null
		return
	var image := Image.new()
	if image.load_png_from_buffer(body) != OK:
		push_warning("asset-library: thumbnail is not a PNG")
		_preview.texture = null
		return
	_preview.texture = ImageTexture.create_from_image(image)


func _on_blob_done(result: int, code: int, _headers: PackedStringArray,
		body: PackedByteArray) -> void:
	if result != HTTPRequest.RESULT_SUCCESS or code != 200:
		push_error("asset-library: download failed")
		return
	var dest := "res://" + _dl_name
	var file := FileAccess.open(dest, FileAccess.WRITE)
	if file == null:
		push_error("asset-library: cannot write " + dest)
		return
	file.store_buffer(body)
	file.close()
	EditorInterface.get_resource_filesystem().scan()
	print("asset-library: imported " + dest)
