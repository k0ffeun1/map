# Аудит логических Admin-1 и Polygon-фрагментов

> Только диагностика. Ничего не объединяется и не меняется.

## Итог

- Текущих записей геометрии/targets: **4027**.
- Уникальных групп `(страна + точное имя)`: **2903**.
- Одиночных групп: **2590**.
- Многозаписных групп: **313**.
- Записей внутри многозаписных групп: **1437**.
- Групп с явным `_2/_3/_ovN` признаком общего generated base id: **313**.
- Записей в таких подтверждённых семействах: **1437**.
- Максимум Polygon-записей на одно имя: **73**.
- Текущих target cells, назначенных по отдельным кускам в подтверждённых семействах: **2981**.

## Вывод

Таблица из 4027 записей не должна автоматически считаться таблицей 4027 логических Admin-1. Формат карты хранит отдельные Polygon-куски как отдельные записи; для cell-targets нужен отдельный parent Admin-1 identity.

## Именные случаи

### switzerland / Appenzell Innerrhoden

- Records: **1**, combined area: **41239.7 km²**, piece-level targets sum: **12**.
- Class: `same_name_multi_record_review`; same generated base: `True`.

| province_id | legacy_id | km² | target cells | region |
|---|---|---:|---:|---|
| province:3369 | switzerland__appenzell_innerrhoden | 41239.7 | 12 | Швейцария |

### latvia / Jekabpils

- Records: **1**, combined area: **64112.3 km²**, piece-level targets sum: **12**.
- Class: `same_name_multi_record_review`; same generated base: `True`.

| province_id | legacy_id | km² | target cells | region |
|---|---|---:|---:|---|
| province:4009 | latvia__jekabpils | 64112.3 | 12 | Ливония и Эстония |

### united_kingdom / Northumberland

- Records: **10**, combined area: **75830.6 km²**, piece-level targets sum: **19**.
- Class: `confirmed_piece_family`; same generated base: `True`.

| province_id | legacy_id | km² | target cells | region |
|---|---|---:|---:|---|
| province:1762 | united_kingdom__northumberland | 13.2 | 1 | Шотландское нагорье |
| province:1763 | united_kingdom__northumberland_2 | 872.5 | 1 | Шотландское нагорье |
| province:1764 | united_kingdom__northumberland_3 | 11.7 | 1 | Шотландское нагорье |
| province:1765 | united_kingdom__northumberland_4 | 1603.5 | 1 | Шотландское нагорье |
| province:1766 | united_kingdom__northumberland_5 | 60.6 | 1 | Шотландское нагорье |
| province:1767 | united_kingdom__northumberland_6 | 6.4 | 1 | Шотландское нагорье |
| province:1768 | united_kingdom__northumberland_7 | 73138.6 | 10 | Шотландское нагорье |
| province:1769 | united_kingdom__northumberland_8 | 105.4 | 1 | Шотландская низменность |
| province:1770 | united_kingdom__northumberland_9 | 10.1 | 1 | Шотландское нагорье |
| province:1771 | united_kingdom__northumberland_10 | 8.7 | 1 | Шотландское нагорье |

### solomon_islands / Rennell and Bellona

- Records: **1**, combined area: **651.5 km²**, piece-level targets sum: **1**.
- Class: `same_name_multi_record_review`; same generated base: `True`.

| province_id | legacy_id | km² | target cells | region |
|---|---|---:|---:|---|
| province:3126 | solomon_islands__rennell_and_bellona | 651.5 | 1 | Меланезийские острова |

## Самые фрагментированные группы

| Country | Name | Records | Combined km² | Piece-level targets | Class |
|---|---|---:|---:|---:|---|
| canada | Nunavut | 73 | 1724479.3 | 79 | confirmed_piece_family |
| united_states_of_america | Alaska | 72 | 1548255.5 | 83 | confirmed_piece_family |
| canada | British Columbia | 54 | 952099.6 | 71 | confirmed_piece_family |
| chile | Magallanes y Antártica Chilena | 39 | 118451.6 | 40 | confirmed_piece_family |
| chile | Aisén del General Carlos Ibáñez del Campo | 32 | 98216.0 | 36 | confirmed_piece_family |
| greenland | Kommuneqarfik Sermersooq | 22 | 558790.0 | 27 | confirmed_piece_family |
| canada | Newfoundland and Labrador | 20 | 372845.1 | 22 | confirmed_piece_family |
| greenland | Kommune Kujalleq | 20 | 48458.0 | 20 | confirmed_piece_family |
| indonesia | Maluku | 18 | 42229.2 | 19 | confirmed_piece_family |
| brazil | Pará | 17 | 1381043.6 | 30 | confirmed_piece_family |
| russia | Sakha (Yakutia) | 16 | 3049767.6 | 27 | confirmed_piece_family |
| canada | Québec | 15 | 1448805.0 | 37 | confirmed_piece_family |
| united_states_of_america | Florida | 15 | 148344.4 | 28 | confirmed_piece_family |
| norway | Nordland | 15 | 36428.7 | 16 | confirmed_piece_family |
| canada | Northwest Territories | 14 | 1209475.7 | 19 | confirmed_piece_family |
| greenland | Qaasuitsup Kommunia | 13 | 343357.6 | 14 | confirmed_piece_family |
| australia | Northern Territory | 12 | 1325832.2 | 23 | confirmed_piece_family |
| indonesia | Nusa Tenggara Timur | 11 | 46017.2 | 30 | confirmed_piece_family |
| norway | Møre og Romsdal | 11 | 13771.5 | 13 | confirmed_piece_family |
| indonesia | Kepulauan Riau | 11 | 5269.7 | 11 | confirmed_piece_family |
| greenland | Nationalparken | 10 | 403901.0 | 19 | confirmed_piece_family |
| united_kingdom | Northumberland | 10 | 75830.6 | 19 | confirmed_piece_family |
| venezuela | Delta Amacuro | 10 | 35693.4 | 11 | confirmed_piece_family |
| united_states_of_america | New Jersey | 9 | 23549.5 | 18 | confirmed_piece_family |
| finland | Finland Proper | 9 | 9160.2 | 10 | confirmed_piece_family |
| japan | Nagasaki | 9 | 3776.1 | 10 | confirmed_piece_family |
| australia | Queensland | 8 | 1800215.4 | 23 | confirmed_piece_family |
| russia | Sakhalin | 8 | 84803.5 | 19 | confirmed_piece_family |
| united_states_of_america | Maine | 8 | 84012.9 | 21 | confirmed_piece_family |
| indonesia | Maluku Utara | 8 | 30231.5 | 10 | confirmed_piece_family |
| philippines | Palawan | 8 | 11402.7 | 9 | confirmed_piece_family |
| united_states_of_america | Texas | 7 | 689915.8 | 22 | confirmed_piece_family |
| russia | Arkhangel'sk | 7 | 369270.2 | 15 | confirmed_piece_family |
| indonesia | Papua | 7 | 313358.1 | 18 | confirmed_piece_family |
| china | Guangdong | 7 | 176135.5 | 20 | confirmed_piece_family |
| united_states_of_america | Washington | 7 | 173654.8 | 20 | confirmed_piece_family |
| united_states_of_america | North Carolina | 7 | 128081.5 | 20 | confirmed_piece_family |
| indonesia | Papua Barat | 7 | 94914.1 | 18 | confirmed_piece_family |
| indonesia | Riau | 7 | 88226.2 | 20 | confirmed_piece_family |
| norway | Finnmark | 7 | 47713.3 | 9 | confirmed_piece_family |
| norway | Troms | 7 | 23482.3 | 7 | confirmed_piece_family |
| sweden | Stockholm | 7 | 6009.2 | 7 | confirmed_piece_family |
| russia | Chukchi Autonomous Okrug | 6 | 719768.8 | 12 | confirmed_piece_family |
| russia | Yamal-Nenets | 6 | 629191.8 | 11 | confirmed_piece_family |
| china | Fujian | 6 | 120828.7 | 19 | confirmed_piece_family |
| china | Zhejiang | 6 | 100847.0 | 17 | confirmed_piece_family |
| papua_new_guinea | Western | 6 | 100135.6 | 16 | confirmed_piece_family |
| malaysia | Sabah | 6 | 73869.3 | 13 | confirmed_piece_family |
| mexico | Baja California Sur | 6 | 72233.3 | 10 | confirmed_piece_family |
| indonesia | Sulawesi Tenggara | 6 | 34436.2 | 14 | confirmed_piece_family |
| united_states_of_america | Hawaii | 6 | 16509.8 | 11 | confirmed_piece_family |
| papua_new_guinea | Milne Bay | 6 | 12798.6 | 6 | confirmed_piece_family |
| bangladesh | Barisal | 6 | 8672.5 | 14 | confirmed_piece_family |
| solomon_islands | Western | 6 | 4316.0 | 6 | confirmed_piece_family |
| australia | Western Australia | 5 | 2579558.6 | 18 | confirmed_piece_family |
| russia | Krasnoyarsk | 5 | 2494517.4 | 16 | confirmed_piece_family |
| mexico | Sonora | 5 | 180445.5 | 10 | confirmed_piece_family |
| russia | Nenets | 5 | 174696.8 | 9 | confirmed_piece_family |
| united_states_of_america | Louisiana | 5 | 119843.0 | 20 | confirmed_piece_family |
| india | West Bengal | 5 | 92460.5 | 18 | confirmed_piece_family |
| indonesia | Sumatera Utara | 5 | 73331.7 | 18 | confirmed_piece_family |
| australia | Tasmania | 5 | 67034.5 | 13 | confirmed_piece_family |
| indonesia | Sulawesi Tengah | 5 | 60205.1 | 18 | confirmed_piece_family |
| indonesia | Sumatera Barat | 5 | 41829.3 | 14 | confirmed_piece_family |
| germany | Mecklenburg-Vorpommern | 5 | 23009.6 | 11 | confirmed_piece_family |
| cuba | Camagüey | 5 | 15806.1 | 15 | confirmed_piece_family |
| south_korea | South Jeolla | 5 | 10779.7 | 12 | confirmed_piece_family |
| south_korea | South Gyeongsang | 5 | 10346.2 | 11 | confirmed_piece_family |
| ecuador | Galápagos | 5 | 7292.6 | 5 | confirmed_piece_family |
| fiji | Northern | 5 | 6047.7 | 7 | confirmed_piece_family |
| solomon_islands | Isabel | 5 | 4005.7 | 6 | confirmed_piece_family |
| netherlands | Friesland | 5 | 3901.4 | 9 | confirmed_piece_family |
| vietnam | Hồ Chí Minh city | 5 | 1916.1 | 6 | confirmed_piece_family |
| brazil | Maranhão | 4 | 326592.8 | 19 | confirmed_piece_family |
| brazil | São Paulo | 4 | 248278.4 | 19 | confirmed_piece_family |
| mauritania | Inchiri | 4 | 61815.4 | 15 | confirmed_piece_family |
| canada | Nova Scotia | 4 | 55029.9 | 21 | confirmed_piece_family |
| germany | Niedersachsen | 4 | 48058.0 | 15 | confirmed_piece_family |
| chile | Los Lagos | 4 | 46584.9 | 5 | confirmed_piece_family |
| myanmar | Tanintharyi | 4 | 37128.2 | 17 | confirmed_piece_family |
| myanmar | Rakhine | 4 | 34739.6 | 18 | confirmed_piece_family |
| bangladesh | Chittagong | 4 | 29062.1 | 17 | confirmed_piece_family |
| norway | Nord-Trøndelag | 4 | 24426.3 | 5 | confirmed_piece_family |
| indonesia | Sulawesi Utara | 4 | 14492.5 | 7 | confirmed_piece_family |
| norway | Hordaland | 4 | 14063.1 | 6 | confirmed_piece_family |
| cambodia | Kaôh Kong | 4 | 13967.0 | 17 | confirmed_piece_family |
| greece | Dytiki Ellada | 4 | 11277.7 | 8 | confirmed_piece_family |
| south_korea | Gyeonggi | 4 | 10864.6 | 11 | confirmed_piece_family |
| japan | Hiroshima | 4 | 8227.1 | 10 | confirmed_piece_family |
| japan | Kumamoto | 4 | 7137.6 | 8 | confirmed_piece_family |
| vanuatu | Sanma | 4 | 4370.2 | 5 | confirmed_piece_family |
| croatia | Splitsko-Dalmatinska | 4 | 4105.6 | 6 | confirmed_piece_family |
| spain | Las Palmas | 4 | 4085.0 | 4 | confirmed_piece_family |
| greece | Voreio Aigaio | 4 | 3454.6 | 4 | confirmed_piece_family |
| spain | Santa Cruz de Tenerife | 4 | 3356.0 | 4 | confirmed_piece_family |
| croatia | Primorsko-Goranska | 4 | 3281.3 | 4 | confirmed_piece_family |
| united_states_of_america | Rhode Island | 4 | 2672.1 | 4 | confirmed_piece_family |
| greece | Notio Aigaio | 4 | 2544.2 | 5 | confirmed_piece_family |
| united_kingdom | Eilean Siar | 4 | 2469.4 | 4 | confirmed_piece_family |
| philippines | Albay | 4 | 2351.8 | 4 | confirmed_piece_family |

## Архитектурный контракт для исправления

1. `admin1_id` — логическая административная единица, единственная сущность для target-cell count, региона и будущего деления.
2. `piece_id` — отдельный Polygon только для геометрии/рендера; несколько `piece_id` могут ссылаться на один `admin1_id`.
3. Нельзя сливать реальные Admin-1 только потому, что они маленькие по площади или меньше соседей.
4. Исключения смешанного уровня (например Greater London) должны быть явными и воспроизводимыми, а не эвристикой по площади.
