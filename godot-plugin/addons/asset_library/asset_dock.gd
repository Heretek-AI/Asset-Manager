@tool
extends VBoxContainer
## Dock panel: search the remote library, download into res://.

const CONFIG_PATH := "user://asset_library.cfg"

var _items: Array = []
var _http: HTTPRequest
var _dl: HTTPRequest
var _dl_name := ""


func _ready() -> void:
	_http = HTTPRequest.new()
	add_child(_http)
	_http.request_completed.connect(_on_list_done)
	_dl = HTTPRequest.new()
	add_child(_dl)
	_dl.request_completed.connect(_on_blob_done)
	%Go.pressed.connect(_on_search)
	%Download.pressed.connect(_on_download)
	_load_config()


func _load_config() -> void:
	var cfg := ConfigFile.new()
	if cfg.load(CONFIG_PATH) == OK:
		%URL.text = str(cfg.get_value("server", "url", ""))
		%Token.text = str(cfg.get_value("server", "token", ""))


func _save_config() -> void:
	var cfg := ConfigFile.new()
	cfg.set_value("server", "url", %URL.text)
	cfg.set_value("server", "token", %Token.text)
	cfg.save(CONFIG_PATH)


func _api(path: String) -> String:
	return %URL.text.strip_edges().trim_suffix("/") + path


func _auth() -> PackedStringArray:
	return PackedStringArray(
		["Authorization: Bearer " + %Token.text])


func _on_search() -> void:
	_save_config()
	var url := AssetLibraryClient.search_url(
		_api("/api/v1/assets"), {"q": %Query.text})
	if _http.request(url, _auth()) != OK:
		push_error("asset-library: search request failed to start")


func _on_list_done(result: int, _code: int, _headers: PackedStringArray,
		body: PackedByteArray) -> void:
	if result != HTTPRequest.RESULT_SUCCESS:
		push_error("asset-library: search failed")
		return
	_items = AssetLibraryClient.parse_assets(body.get_string_from_utf8())
	%Results.clear()
	for item: Variant in _items:
		%Results.add_item(str((item as Dictionary).get("name", "?")))


func _on_download() -> void:
	var selected: PackedInt32Array = %Results.get_selected_items()
	if selected.is_empty():
		return
	var item: Dictionary = _items[selected[0]]
	_dl_name = str(item.get("name", "download.bin"))
	var url := _api("/api/v1/assets/%d/blob" % int(item.get("id", 0)))
	if _dl.request(url, _auth()) != OK:
		push_error("asset-library: download request failed to start")


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
