# Clean Admin-1 source lineage / migration audit

## Source identity layer

- Raw Natural Earth features: **4596**.
- Stable source feature IDs: **4596**.
- Logical parents after explicit-only aggregation: **4564**.
- Source features participating in explicit aggregation: **33**.
- Fine-type source features requiring an explicit level policy: **592**.
- Heuristic area/neighbour merges: **0**.

## Migration of current 4027 records

- Current target records: **4027**.
- Records that can be linked to exactly one raw source feature by legacy base: **3996**.
- Records whose legacy base matches multiple raw source features: **30**.
- Records with no raw source-name base match: **1**.
- Polygon-piece records (`_2/_3/_ovN`) resolved to a parent base: **1124**.
- Distinct clean source parents referenced by uniquely matched current records: **2881**.

## Why the old 4027 count cannot be the new parent count

A single raw Admin-1 may be a MultiPolygon or later split into many render pieces. Each piece must share one parent identity and one target-cell budget. Conversely, exact display names are not sufficient as a primary key: Natural Earth can contain different source features with the same name and ISO code but different `adm1_code` (Jekabpils is the concrete example).

## Watched source parents

| Source ID | Admin | Name | type | adm1_code | ISO | km² | parts | logical parent |
|---|---|---|---|---|---|---:|---:|---|
| ne10m-adm1:LVA-1085 | Latvia | Jekabpils | Republican City | LVA-1085 | LV-JKB | 27.4 | 1 | ne10m-adm1:LVA-1085 |
| ne10m-adm1:LVA-5725 | Latvia | Jekabpils | Municipality | LVA-5725 | LV-JKB | 921.3 | 1 | ne10m-adm1:LVA-5725 |
| ne10m-adm1:CHE-3473 | Switzerland | Appenzell Innerrhoden | Canton | CHE-3473 | CH-AI | 166.4 | 3 | ne10m-adm1:CHE-3473 |
| ne10m-adm1:GBR-2034 | United Kingdom | Northumberland | Unitary Single-Tier County | GBR-2034 | GB-NBL | 5097.9 | 1 | ne10m-adm1:GBR-2034 |

## Ambiguous current records — first 50

| Current ID | legacy_id | name | candidate source IDs |
|---|---|---|---|
| province:38 | malawi__chitipa | Chitipa | ne10m-adm1:MWI-1194, ne10m-adm1:MWI-1873 |
| province:288 | azerbaijan__lankaran | Lankaran | ne10m-adm1:AZE-1735, ne10m-adm1:AZE-1707, ne10m-adm1:AZE-5562 |
| province:301 | uzbekistan__tashkent | Tashkent | ne10m-adm1:UZB-372, ne10m-adm1:UZB-4828 |
| province:327 | malawi__chitipa_2 | Chitipa | ne10m-adm1:MWI-1194, ne10m-adm1:MWI-1873 |
| province:433 | azerbaijan__ki | Şəki | ne10m-adm1:AZE-1727, ne10m-adm1:AZE-5564 |
| province:561 | mozambique__maputo | Maputo | ne10m-adm1:MOZ-1927, ne10m-adm1:MOZ-5854 |
| province:615 | republic_of_serbia__pomoravski | Pomoravski | ne10m-adm1:SRB-833, ne10m-adm1:SRB-832 |
| province:683 | croatia__brodsko_posavska | Brodsko-Posavska | ne10m-adm1:HRV-1602, ne10m-adm1:HRV-1604 |
| province:2573 | ireland__waterford | Waterford | ne10m-adm1:IRL-1444, ne10m-adm1:IRL-5571 |
| province:2574 | ireland__cork | Cork | ne10m-adm1:IRL-78, ne10m-adm1:IRL-5569 |
| province:2575 | ireland__cork_2 | Cork | ne10m-adm1:IRL-78, ne10m-adm1:IRL-5569 |
| province:2578 | ireland__limerick | Limerick | ne10m-adm1:IRL-726, ne10m-adm1:IRL-5570 |
| province:2580 | ireland__galway | Galway | ne10m-adm1:IRL-713, ne10m-adm1:IRL-5568 |
| province:2581 | ireland__galway_2 | Galway | ne10m-adm1:IRL-713, ne10m-adm1:IRL-5568 |
| province:2950 | kiribati__kiribati | Kiribati | ne10m-adm1:KIR+00?, ne10m-adm1:KIR+99? |
| province:3175 | philippines__cebu | Cebu | ne10m-adm1:PHL-5522, ne10m-adm1:PHL-2514 |
| province:3176 | philippines__cebu_2 | Cebu | ne10m-adm1:PHL-5522, ne10m-adm1:PHL-2514 |
| province:3180 | philippines__iloilo | Iloilo | ne10m-adm1:PHL-2529, ne10m-adm1:PHL-5526 |
| province:3309 | moldova__rezina | Rezina | ne10m-adm1:MDA-1645, ne10m-adm1:MDA-1644 |
| province:3416 | republic_of_serbia__pomoravski_2 | Pomoravski | ne10m-adm1:SRB-833, ne10m-adm1:SRB-832 |
| province:3465 | philippines__cotabato | Cotabato | ne10m-adm1:PHL-5527, ne10m-adm1:PHL-2579 |
| province:3566 | croatia__brodsko_posavska_2 | Brodsko-Posavska | ne10m-adm1:HRV-1602, ne10m-adm1:HRV-1604 |
| province:3653 | afghanistan__uruzgan | Uruzgan | ne10m-adm1:AFG-1752, ne10m-adm1:AFG-1753 |
| province:3655 | afghanistan__parwan | Parwan | ne10m-adm1:AFG-1769, ne10m-adm1:AFG-1772 |
| province:3662 | afghanistan__parwan_2 | Parwan | ne10m-adm1:AFG-1769, ne10m-adm1:AFG-1772 |
| province:3667 | afghanistan__uruzgan_2 | Uruzgan | ne10m-adm1:AFG-1752, ne10m-adm1:AFG-1753 |
| province:3670 | uganda__mbarara | Mbarara | ne10m-adm1:UGA-3374, ne10m-adm1:UGA-3371 |
| province:3683 | uganda__mbarara_2 | Mbarara | ne10m-adm1:UGA-3374, ne10m-adm1:UGA-3371 |
| province:3869 | hungary__veszpr_m | Veszprém | ne10m-adm1:HUN-3158, ne10m-adm1:HUN-4909 |
| province:4009 | latvia__jekabpils | Jekabpils | ne10m-adm1:LVA-5725, ne10m-adm1:LVA-1085 |

## Contract locked by this manifest

1. `source_feature_id` identifies an untouched Natural Earth feature and prefers `adm1_code`.
2. `logical_admin1_id` owns region assignment and target-cell count.
3. Polygon/render pieces are children and never receive independent minimum-one-cell budgets.
4. Small area, neighbour size and `type_en` are review signals only; they cannot silently merge boundaries.
5. Mixed-level corrections are explicit named aggregations with lineage, not destructive geometry heuristics.
