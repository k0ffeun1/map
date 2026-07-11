shader_type canvas_item;

// Раскраска глубины моря в реальном времени — непрерывный градиент по 3
// цветам (color_shelf у 0 м -> color_mid у mid_point (доля от кривой) ->
// color_deep у max_depth_m, общая кривизна gradient_gamma) + изобаты
// (тонкие линии через каждые isobath_interval_m) поверх, как на настоящей
// морской карте. Крутится слайдером/цветовыбором в игре (клавиша 5), см.
// scripts/SeaZonesLayer.gd (UI-панель) и
// scripts/tools/_preview_sea_depth.py (генератор текстуры сырой глубины).
//
// Текстура кодирует глубину как 16 бит на пиксель (R = старший байт,
// G = младший байт нормированного 0..65535 значения относительно
// max_depth_m), альфа = маска море(1)/суша(0).

uniform float max_depth_m = 6000.0;
uniform vec4 color_shelf : source_color = vec4(0.541, 0.776, 0.855, 1.0);
uniform vec4 color_mid : source_color = vec4(0.220, 0.510, 0.690, 1.0);
uniform vec4 color_deep : source_color = vec4(0.117, 0.313, 0.627, 1.0);
uniform float gradient_gamma : hint_range(0.05, 3.0) = 0.4;  // <1 растягивает мелководье, >1 растягивает глубины
uniform float mid_point : hint_range(0.01, 0.99) = 0.5;  // положение color_mid на кривой (0=shelf..1=deep)
uniform bool show_isobaths = true;
uniform float isobath_interval_m : hint_range(50.0, 2000.0) = 500.0;
uniform float isobath_width_px : hint_range(0.5, 4.0) = 1.0;
uniform vec4 isobath_color : source_color = vec4(1.0, 1.0, 1.0, 0.35);

void fragment() {
	vec4 tex = texture(TEXTURE, UV);
	float sea_mask = tex.a;
	float combined = tex.r * 255.0 * 256.0 + tex.g * 255.0;
	float depth_m = combined / 65535.0 * max_depth_m;

	float t = clamp(depth_m / max_depth_m, 0.0, 1.0);
	float t_curved = pow(t, gradient_gamma);
	vec3 base_rgb;
	if (t_curved < mid_point) {
		base_rgb = mix(color_shelf.rgb, color_mid.rgb, t_curved / mid_point);
	} else {
		base_rgb = mix(color_mid.rgb, color_deep.rgb, (t_curved - mid_point) / (1.0 - mid_point));
	}

	float line_alpha = 0.0;
	if (show_isobaths) {
		float px_depth = max(fwidth(depth_m) * isobath_width_px, 0.0001);
		float m = mod(depth_m, isobath_interval_m);
		float dist = min(m, isobath_interval_m - m);
		line_alpha = (1.0 - smoothstep(0.0, px_depth, dist)) * isobath_color.a;
	}

	vec3 final_rgb = mix(base_rgb, isobath_color.rgb, line_alpha);
	COLOR = vec4(final_rgb, sea_mask);
}
