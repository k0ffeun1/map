# Layer 8 ↔ safe Admin-1 reconciliation

> Это только аудит. Ни одно legacy-объединение автоматически не становится normalization policy.

## Сводка

- Safe playable parents: **4561**.
- Legacy Layer-8 render records: **4027**.
- Reconstructed legacy groups: **2903**.
- Render-piece multiplicity delta: **1124**.
- 1→1 legacy groups: **2423**.
- N→1 legacy groups: **469**.
- Unmatched legacy groups: **11**.
- HIGH_CONFIDENCE: **2652**.
- REVIEW: **184**.
- REJECTED_GEOMETRY: **67**.
- Safe parents not recovered: **269**.
- Safe parents used by >1 legacy group: **0**.

## Контрольные страны

| Country | Safe | L8 records | L8 groups | 1→1 | N→1 | High | Review | Rejected |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Azerbaijan | 78 | 33 | 32 | 6 | 26 | 28 | 2 | 2 |
| Latvia | 119 | 1 | 1 | 0 | 1 | 1 | 0 | 0 |
| Macedonia | 84 | 10 | 10 | 0 | 10 | 5 | 5 | 0 |
| Malta | 68 | 2 | 2 | 0 | 2 | 0 | 0 | 2 |
| Slovenia | 193 | 2 | 2 | 0 | 2 | 0 | 2 | 0 |
| United Kingdom | 200 | 74 | 52 | 14 | 37 | 46 | 2 | 4 |

## Правило интерпретации

- `HIGH_CONFIDENCE` означает только сильное геометрическое совпадение.
- `policy_status` всегда остаётся `UNREVIEWED` на этом этапе.
- Только проверенные legacy groupings позже переносятся в explicit normalization policy.
- Старый `_merge_small_pieces` этим скриптом не вызывается и не восстанавливается.
