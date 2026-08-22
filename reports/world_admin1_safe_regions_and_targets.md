# Safe Admin-1 → historical regions → target cells

This report belongs to the new clean logical Admin-1 layer. The legacy 4027 Layer-8 is not modified.

## Summary

- Logical Admin-1 parents: **4561**.
- Historical regions represented: **294**.
- Region assignments flagged for review: **512**.
- Fine-type parents retained for level-policy review: **564**.
- Dissolved safe-region polygon pieces: **4186**.
- Recomputed target gameplay cells: **14647**.
- Region-profile fallback parents: **15**.
- Migrated explicit cell overrides: **3 / 3**.

## Migration method

1. Intersect each clean logical Admin-1 with the old FINAL Layer-8 provinces.
2. Sum overlap area by historical region.
3. Assign the region with the largest overlap share.
4. Flag assignments with dominance < 0.80 or geometry coverage < 0.98.
5. Recompute cell targets from the existing regional workbook profile using clean geodesic area.
6. Polygon pieces never receive their own minimum-one-cell budget.

## Control cases

| Admin | Name | km² | Region | Cells | dominance | coverage | review | fine-type |
|---|---|---:|---|---:|---:|---:|---|---|
| United Kingdom | Большой Лондон | 1604.8 | Большой Лондон | 4 | 0.999 | 1.000 | False | True |
| Switzerland | Appenzell Innerrhoden | 166.4 | Швейцария | 1 | 1.000 | 1.000 | False | True |
| Spain | Madrid | 8000.8 | Новая Кастилия | 4 | 0.998 | 1.000 | False | False |
| United Kingdom | Northumberland | 5097.9 | Шотландское нагорье | 1 | 1.000 | 0.999 | False | False |
| Latvia | Jekabpils | 27.4 | Ливония и Эстония | 1 | 1.000 | 1.000 | False | False |
| Latvia | Jekabpils | 921.3 | Ливония и Эстония | 1 | 1.000 | 1.000 | False | True |
| Portugal | Lisboa | 2741.1 | Эштремадура-и-Рибатежу | 4 | 1.000 | 0.997 | False | False |
| Portugal | Porto | 2310.3 | Минью | 3 | 1.000 | 1.000 | False | False |

## Target-count distribution

| Cells | Parents |
|---:|---:|
| 1 | 2549 |
| 2 | 503 |
| 3 | 290 |
| 4 | 264 |
| 5 | 158 |
| 6 | 131 |
| 7 | 98 |
| 8 | 67 |
| 9 | 53 |
| 10 | 66 |
| 11 | 38 |
| 12 | 86 |
| 13 | 18 |
| 14 | 150 |
| 15 | 5 |
| 16 | 79 |
| 18 | 6 |

## Review policy

Review flags do not modify geometry. They only identify parents whose migrated region should be inspected before the safe layer becomes canonical.


## World-crop parent policy

- Clean source logical parents: **4564**.
- Playable/rendered logical parents: **4561**.
- Excluded after project world crop: **3**.
  - `ne10m-adm1:ATA+00?` — Antarctica / Antarctica (piece_count=0).
  - `ne10m-adm1:ATA+99?` — Antarctica / Antarctica (piece_count=0).
  - `ne10m-adm1:GRL-2738` — Greenland / Pituffik (piece_count=0).
