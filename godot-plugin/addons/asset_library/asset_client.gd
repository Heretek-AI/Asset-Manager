class_name AssetLibraryClient
extends RefCounted
## Pure helpers for talking to the library server (headless-testable).


## Build a GET URL with only the non-empty params attached.
static func search_url(base: String, params: Dictionary) -> String:
	var parts: PackedStringArray = []
	for key: String in params.keys():
		var value := str(params[key])
		if value != "":
			parts.append(key.uri_encode() + "=" + value.uri_encode())
	if parts.is_empty():
		return base
	return base + "?" + "&".join(parts)


## Parse a list-assets response body into an Array of Dictionaries.
static func parse_assets(text: String) -> Array:
	var data: Variant = JSON.parse_string(text)
	if typeof(data) != TYPE_DICTIONARY:
		return []
	var assets: Variant = (data as Dictionary).get("assets", [])
	if typeof(assets) != TYPE_ARRAY:
		return []
	return assets
