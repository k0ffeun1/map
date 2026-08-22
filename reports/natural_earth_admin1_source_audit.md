# Raw Natural Earth Admin-1 source audit

- Features: **4596**
- Countries: **253**
- Exact `(admin,name)` groups: **4566**
- Repeated exact `(admin,name)` groups in source: **29**

## Diagnostic names before project processing

| Admin | Name | type_en | adm1_code | ISO | WGS84 km² | geometry | parts |
|---|---|---|---|---|---:|---|---:|
| Latvia | Jekabpils | Municipality | LVA-5725 | LV-JKB | 921.3 | Polygon | 1 |
| Latvia | Jekabpils | Republican City | LVA-1085 | LV-JKB | 27.4 | Polygon | 1 |
| Switzerland | Appenzell Innerrhoden | Canton | CHE-3473 | CH-AI | 166.4 | MultiPolygon | 3 |
| United Kingdom | Northumberland | Unitary Single-Tier County | GBR-2034 | GB-NBL | 5097.9 | Polygon | 1 |

## Interpretation

If a watched raw feature is normal-sized here but enormous in `world_province_identity_geometry_audit.md`, the corruption is introduced by the project preprocessing stage rather than by the source dataset or area formula.
