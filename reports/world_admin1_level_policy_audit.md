# Аудит уровней Natural Earth Admin-1

> Ничего не объединяется автоматически. Это очередь для явных правил.

## Итог

- Source features: **4596**.
- Countries: **253**.
- Fine-type features: **592**.
- Coarse-clean countries: **228**.
- Uniform-fine countries: **11**.
- Mixed-level countries: **13**.
- Minor/dominant-fine mixed edge cases: **1**.
- Region groups worth explicit review: **33**.
- Approved explicit aggregations: **1**.

## Mixed-level countries

| Country | Features | Fine | Share | Types |
|---|---:|---:|---:|---|
| Slovenia | 193 | 181 | 93.8% | Commune|Municipality:181; Statistical Region:12 |
| Latvia | 119 | 110 | 92.4% | Municipality:110; Republican City:9 |
| United Kingdom | 232 | 97 | 41.8% | Unitary Authority:50; Metropolitan Borough:36; London Borough:28; Unitary District:26; Administrative County:26; District:24; Unitary Authority (wales):21; Unitary Single-Tier County:6 |
| Macedonia | 84 | 12 | 14.3% | Statistical Region:72; Municipality:12 |
| Azerbaijan | 78 | 11 | 14.1% | District:67; Municipality:11 |
| Bosnia and Herzegovina | 18 | 10 | 55.6% | Canton:10; :8 |
| Antigua and Barbuda | 8 | 6 | 75.0% | Parish:6; Dependency:2 |
| Grenada | 7 | 6 | 85.7% | Parish:6; Dependency:1 |
| China | 32 | 4 | 12.5% | Province:22; Autonomous Region:5; Municipality:4; :1 |
| Mongolia | 22 | 4 | 18.2% | Province:18; Municipality:4 |
| Cambodia | 24 | 3 | 12.5% | Province:21; Municipality:3 |
| Estonia | 15 | 1 | 6.7% | County:14; Municipality:1 |
| Belarus | 7 | 1 | 14.3% | Region:6; Municipality:1 |

## Top region-level review candidates

| Country | Region | Features | Fine | Non-fine | Approved |
|---|---|---:|---:|---:|---|
| Slovenia | Podravska | 33 | 32 | 1 | no |
| Slovenia | Savinjska | 33 | 32 | 1 | no |
| United Kingdom | Greater London | 33 | 29 | 4 | yes |
| Latvia | Riga | 30 | 28 | 2 | no |
| Slovenia | Pomurska | 27 | 26 | 1 | no |
| Latvia | Vidzeme | 26 | 25 | 1 | no |
| Slovenia | Osrednjeslovenska | 25 | 24 | 1 | no |
| Latvia | Zemgale | 22 | 20 | 2 | no |
| Latvia | Latgale | 21 | 19 | 2 | no |
| Latvia | Kurzeme | 20 | 18 | 2 | no |
| Slovenia | Gorenjska | 17 | 16 | 1 | no |
| United Kingdom | North West | 23 | 15 | 8 | no |
| Slovenia | Jugovzhodna Slovenija | 15 | 14 | 1 | no |
| United Kingdom | Eastern | 12 | 12 | 0 | no |
| United Kingdom | South Western | 12 | 12 | 0 | no |
| Slovenia | Goriška | 12 | 11 | 1 | no |
| Slovenia | Koroška | 12 | 11 | 1 | no |
| Macedonia | Greater Skopje | 10 | 10 | 0 | no |
| United Kingdom | Yorkshire and the Humber | 15 | 9 | 6 | no |
| Bosnia and Herzegovina | Federacija Bosna i Hercegovina | 9 | 9 | 0 | no |
| Saint Kitts and Nevis | Saint Kitts | 9 | 9 | 0 | no |
| United Kingdom | West Midlands | 14 | 7 | 7 | no |
| Slovenia | Obalno-kraška | 7 | 7 | 0 | no |
| United Kingdom | North East | 12 | 5 | 7 | no |
| Slovenia | Notranjsko-kraška | 6 | 5 | 1 | no |
| United Kingdom | Highlands and Islands | 6 | 5 | 1 | no |
| Saint Kitts and Nevis | Nevis | 5 | 5 | 0 | no |
| Azerbaijan | Aran Economic Region | 19 | 3 | 16 | no |
| Azerbaijan | Ganja-Gazakh Economic Region | 11 | 2 | 9 | no |
| China | North China | 5 | 2 | 3 | no |
| Azerbaijan | Absheron Economic Region | 4 | 2 | 2 | no |
| Slovenia | Spodnjeposavska | 3 | 2 | 1 | no |
| United Kingdom | North Eastern | 2 | 2 | 0 | no |
