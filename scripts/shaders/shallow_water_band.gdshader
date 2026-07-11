shader_type canvas_item;

// Полоса "мелководье" — ФИКСИРОВАННАЯ по расстоянию до берега (не по
// глубине): land_margin_km вглубь суши .. sea_margin_km в море. Оба
// параметра НЕ крутятся слайдером (решение пользователя 2026-07-10: "он
// будет фиксирован всегда") — задаются один раз в
// scripts/SeaZonesLayer.gd и не меняются из UI. Цвет (band_color) —
// ОБЩИЙ с зоной "шельф" в sea_depth_zones.gdshader, синхронизируется
// оттуда же (см. SeaZonesLayer.gd).
//
// Текстура кодирует РАССТОЯНИЕ СО ЗНАКОМ до берега как 16 бит на пиксель
// (R = старший байт, G = младший байт) поверх диапазона
// [encode_min_km, encode_max_km] — суша отрицательная, море положительная,
// см. scripts/tools/build_coast_distance_field.py.
//
// Плавный градиент альфы шириной edge_transition_km — ТОЛЬКО у края со
// стороны моря (sea_margin_km), цвет мелководья гаснет по мере ухода от
// берега вглубь моря. Край со стороны суши (land_margin_km) — резкий обрез
// (step), по прямой просьбе пользователя.

uniform float encode_min_km = -20.0;
uniform float encode_max_km = 1000.0;
uniform float land_margin_km = 1.0;
uniform float sea_margin_km = 10.0;
uniform float edge_transition_km : hint_range(0.0, 100.0) = 1.0;
uniform vec4 band_color : source_color = vec4(0.541, 0.776, 0.855, 1.0);

void fragment() {
	vec4 tex = texture(TEXTURE, UV);
	float combined = tex.r * 255.0 * 256.0 + tex.g * 255.0;
	float signed_km = combined / 65535.0 * (encode_max_km - encode_min_km) + encode_min_km;

	float alpha_land = step(-land_margin_km, signed_km);
	float alpha_sea = 1.0 - smoothstep(sea_margin_km - edge_transition_km, sea_margin_km + edge_transition_km, signed_km);
	float in_band = alpha_land * alpha_sea;
	COLOR = vec4(band_color.rgb, band_color.a * in_band);
}
