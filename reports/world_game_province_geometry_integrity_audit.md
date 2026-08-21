# Аудит геометрической целостности игровых провинций мира

> Геометрию не изменяет. Проверяет, можно ли безопасно запускать автоматическое деление крупных Admin-1.

## Правило

- Перекрытие менее 1% меньшего полигона игнорируется как микроскопический шов/шум.
- От 1% до 20%: только отчёт.
- Перекрытие ≥ 20% меньшего полигона внутри одной страны: **hard block** для автоделения.
- Перекрытие ≥ 85%: почти полное вложение/дубликат, отмечается отдельно.
- Аномально большая площадь относительно медианы страны сама по себе НЕ блокирует деление: это только диагностический сигнал.

## Итог

- Исходных identity: **4027**.
- Валидных геометрий: **4027**.
- Кандидатов автоделения (8+ клеток, ≥40 000 км²): **366**.
- Заблокировано из-за существенного перекрытия: **0**.
- Прошли геометрический gate: **366**.
- Существенных пар перекрытия: **0**.
- Почти полных вложений/дубликатов: **0**.
- Диагностических area-outlier: **163**.

## Заблокированные кандидаты на деление

| Страна | Провинция | Площадь, км² | Клеток | Перекрытий | Max overlap меньшего |
|---|---|---:|---:|---:|---:|

## Существенные пары перекрытия

| Страна | A | B | overlap меньшего | A covered | B covered | severe |
|---|---|---|---:|---:|---:|---|

## Area-outlier — только диагностика

| Страна | Провинция | Площадь, км² | Медиана страны | x медианы | Клеток | Есть overlap |
|---|---|---:|---:|---:|---:|---|
| canada | Québec | 1353072.9 | 230.9 | 5860.3 | 10 |  |
| united_states_of_america | Alaska | 1477952.7 | 263.6 | 5607.4 | 12 |  |
| greenland | Kommuneqarfik Sermersooq | 552242.3 | 98.8 | 5592.0 | 6 |  |
| australia | Western Australia | 2578598.6 | 465.1 | 5543.9 | 14 |  |
| canada | Ontario | 1078098.7 | 230.9 | 4669.3 | 16 |  |
| canada | Northwest Territories | 1030130.7 | 230.9 | 4461.6 | 6 |  |
| greenland | Nationalparken | 392947.5 | 98.8 | 3979.0 | 10 |  |
| canada | British Columbia | 898694.4 | 230.9 | 3892.3 | 14 |  |
| australia | Queensland | 1796225.0 | 465.1 | 3861.8 | 16 |  |
| canada | Nunavut | 827857.3 | 230.9 | 3585.5 | 5 |  |
| brazil | Amazonas | 1963278.6 | 552.2 | 3555.1 | 14 |  |
| greenland | Qaasuitsup Kommunia | 331808.1 | 98.8 | 3359.9 | 2 |  |
| canada | Saskatchewan | 715163.9 | 230.9 | 3097.4 | 14 |  |
| canada | Manitoba | 655018.2 | 230.9 | 2836.9 | 12 |  |
| australia | Northern Territory | 1315050.1 | 465.1 | 2827.3 | 12 |  |
| canada | Alberta | 604342.8 | 230.9 | 2617.5 | 14 |  |
| united_states_of_america | Texas | 688911.0 | 263.6 | 2613.7 | 16 |  |
| brazil | Pará | 1330609.1 | 552.2 | 2409.5 | 14 |  |
| canada | Nunavut | 519469.6 | 230.9 | 2249.9 | 3 |  |
| australia | South Australia | 939635.9 | 465.1 | 2020.2 | 8 |  |
| canada | Yukon | 431996.7 | 230.9 | 1871.0 | 4 |  |
| australia | New South Wales | 792810.6 | 465.1 | 1704.5 | 16 |  |
| brazil | Mato Grosso | 909939.6 | 552.2 | 1647.7 | 12 |  |
| united_states_of_america | California | 408629.9 | 263.6 | 1550.3 | 14 |  |
| united_states_of_america | Montana | 383153.6 | 263.6 | 1453.7 | 14 |  |
| brazil | Minas Gerais | 678707.2 | 552.2 | 1229.0 | 16 |  |
| united_states_of_america | New Mexico | 316523.3 | 263.6 | 1200.9 | 11 |  |
| canada | Newfoundland and Labrador | 263994.8 | 230.9 | 1143.4 | 3 |  |
| united_states_of_america | Arizona | 295754.5 | 263.6 | 1122.1 | 10 |  |
| united_states_of_america | Nevada | 295233.0 | 263.6 | 1120.1 | 10 |  |
| greenland | Qeqqata Kommunia | 108896.5 | 98.8 | 1102.7 | 1 |  |
| brazil | Bahia | 579136.5 | 552.2 | 1048.7 | 16 |  |
| united_states_of_america | Colorado | 268982.0 | 263.6 | 1020.5 | 16 |  |
| united_states_of_america | Wyoming | 252895.5 | 263.6 | 959.5 | 11 |  |
| united_states_of_america | Oregon | 249877.3 | 263.6 | 948.0 | 14 |  |
| united_states_of_america | Michigan | 247820.3 | 263.6 | 940.2 | 16 |  |
| united_states_of_america | Minnesota | 222856.3 | 263.6 | 845.5 | 16 |  |
| united_states_of_america | Utah | 221625.3 | 263.6 | 840.8 | 10 |  |
| united_states_of_america | Kansas | 215066.2 | 263.6 | 816.0 | 16 |  |
| united_states_of_america | Idaho | 207245.1 | 263.6 | 786.3 | 9 |  |
| united_states_of_america | Nebraska | 200884.6 | 263.6 | 762.2 | 15 |  |
| united_states_of_america | South Dakota | 200214.3 | 263.6 | 759.6 | 15 |  |
| united_states_of_america | Oklahoma | 183390.8 | 263.6 | 695.8 | 16 |  |
| united_states_of_america | North Dakota | 181581.9 | 263.6 | 688.9 | 14 |  |
| united_states_of_america | Missouri | 180077.8 | 263.6 | 683.2 | 16 |  |
| united_states_of_america | Washington | 172968.3 | 263.6 | 656.2 | 14 |  |
| brazil | Mato Grosso do Sul | 355813.8 | 552.2 | 644.3 | 12 |  |
| united_states_of_america | Wisconsin | 167234.1 | 263.6 | 634.5 | 16 |  |
| brazil | Goiás | 348702.5 | 552.2 | 631.4 | 16 |  |
| brazil | Maranhão | 326209.9 | 552.2 | 590.7 | 16 |  |
| united_states_of_america | Georgia | 152015.0 | 263.6 | 576.7 | 16 |  |
| united_states_of_america | Illinois | 151864.4 | 263.6 | 576.2 | 16 |  |
| united_states_of_america | Florida | 147531.2 | 263.6 | 559.7 | 14 |  |
| canada | Nunavut | 127931.5 | 230.9 | 554.1 | 1 |  |
| united_states_of_america | Iowa | 145714.7 | 263.6 | 552.8 | 11 |  |
| united_states_of_america | Arkansas | 137955.3 | 263.6 | 523.4 | 16 |  |
| united_states_of_america | Alabama | 134548.3 | 263.6 | 510.5 | 16 |  |
| brazil | Tocantins | 281890.6 | 552.2 | 510.5 | 16 |  |
| united_states_of_america | New York | 133348.6 | 263.6 | 505.9 | 14 |  |
| australia | Victoria | 229220.3 | 465.1 | 492.8 | 16 |  |
| brazil | Rio Grande do Sul | 268899.7 | 552.2 | 486.9 | 16 |  |
| united_states_of_america | North Carolina | 127908.1 | 263.6 | 485.3 | 14 |  |
| greenland | Kommune Kujalleq | 46729.5 | 98.8 | 473.2 | 1 |  |
| united_states_of_america | Mississippi | 124222.1 | 263.6 | 471.3 | 16 |  |
| canada | Newfoundland and Labrador | 106894.4 | 230.9 | 463.0 | 1 |  |
| brazil | Piauí | 253962.5 | 552.2 | 459.9 | 16 |  |
| united_states_of_america | Louisiana | 119463.8 | 263.6 | 453.2 | 16 |  |
| united_states_of_america | Pennsylvania | 118442.5 | 263.6 | 449.4 | 14 |  |
| brazil | São Paulo | 247738.1 | 552.2 | 448.6 | 16 |  |
| united_states_of_america | Ohio | 116028.9 | 263.6 | 440.2 | 14 |  |
| brazil | Rondônia | 239103.1 | 552.2 | 433.0 | 14 |  |
| united_states_of_america | Tennessee | 109255.3 | 263.6 | 414.5 | 16 |  |
| united_states_of_america | Kentucky | 103561.4 | 263.6 | 392.9 | 14 |  |
| united_states_of_america | Virginia | 101980.0 | 263.6 | 386.9 | 14 |  |
| canada | Québec | 86305.4 | 230.9 | 373.8 | 14 |  |
| canada | Northwest Territories | 83415.0 | 230.9 | 361.3 | 1 |  |
| brazil | Paraná | 199087.5 | 552.2 | 360.5 | 16 |  |
| united_states_of_america | Indiana | 92369.7 | 263.6 | 350.5 | 16 |  |
| united_states_of_america | Maine | 83652.7 | 263.6 | 317.4 | 14 |  |
| canada | New Brunswick | 72249.4 | 230.9 | 312.9 | 14 |  |
| canada | Northwest Territories | 71224.5 | 230.9 | 308.5 | 1 |  |
| united_states_of_america | South Carolina | 80676.2 | 263.6 | 306.1 | 15 |  |
| brazil | Ceará | 150900.9 | 552.2 | 273.3 | 16 |  |
| chile | Antofagasta | 123222.9 | 471.8 | 261.2 | 8 |  |
| indonesia | Papua | 295663.6 | 1241.9 | 238.1 | 12 |  |
| united_states_of_america | West Virginia | 62118.1 | 263.6 | 235.7 | 9 |  |
| brazil | Pernambuco | 125430.3 | 552.2 | 227.1 | 16 |  |
| canada | Nova Scotia | 44378.7 | 230.9 | 192.2 | 14 |  |
| canada | Nunavut | 44111.7 | 230.9 | 191.1 | 1 |  |
| chile | Aisén del General Carlos Ibáñez del Campo | 86416.8 | 471.8 | 183.2 | 5 |  |
| canada | Nunavut | 42207.2 | 230.9 | 182.8 | 1 |  |
| brazil | Santa Catarina | 93859.6 | 552.2 | 170.0 | 13 |  |
| chile | Atacama | 79239.1 | 471.8 | 168.0 | 14 |  |
| indonesia | Kalimantan Timur | 195601.2 | 1241.9 | 157.5 | 14 |  |
| norway | Finnmark | 45575.6 | 293.4 | 155.3 | 3 |  |
| australia | Tasmania | 63995.8 | 465.1 | 137.6 | 9 |  |
| chile | Magallanes y Antártica Chilena | 60384.6 | 471.8 | 128.0 | 2 |  |
| indonesia | Kalimantan Tengah | 152766.4 | 1241.9 | 123.0 | 14 |  |
| indonesia | Kalimantan Barat | 147558.1 | 1241.9 | 118.8 | 14 |  |
| brazil | Paraíba | 56697.5 | 552.2 | 102.7 | 7 |  |
| russia | Sakha (Yakutia) | 3009476.2 | 29687.9 | 101.4 | 12 |  |
| algeria | Tamanghasset | 609905.8 | 6299.3 | 96.8 | 5 |  |
| brazil | Rio Grande do Norte | 52976.6 | 552.2 | 95.9 | 7 |  |
| chile | Tarapacá | 41416.5 | 471.8 | 87.8 | 3 |  |
| russia | Krasnoyarsk | 2492942.9 | 29687.9 | 84.0 | 12 |  |
| algeria | Adrar | 480861.5 | 6299.3 | 76.3 | 12 |  |
| indonesia | Papua Barat | 87466.3 | 1241.9 | 70.4 | 12 |  |
| indonesia | Sumatera Selatan | 85092.8 | 1241.9 | 68.5 | 14 |  |
| indonesia | Riau | 82041.5 | 1241.9 | 66.1 | 14 |  |
| indonesia | Sumatera Utara | 68050.7 | 1241.9 | 54.8 | 14 |  |
| egypt | Al Wadi at Jadid | 473505.1 | 9058.4 | 52.3 | 14 |  |
| indonesia | Sulawesi Tengah | 57419.0 | 1241.9 | 46.2 | 14 |  |
| indonesia | Aceh | 54047.6 | 1241.9 | 43.5 | 14 |  |
| indonesia | Jambi | 51124.5 | 1241.9 | 41.2 | 14 |  |
| indonesia | Sulawesi Selatan | 45933.5 | 1241.9 | 37.0 | 14 |  |
| united_kingdom | Northumberland | 73138.6 | 2019.8 | 36.2 | 10 |  |
| indonesia | Jawa Timur | 42142.6 | 1241.9 | 33.9 | 14 |  |
| algeria | Ouargla | 210516.4 | 6299.3 | 33.4 | 14 |  |
| venezuela | Bolívar | 252646.3 | 8002.9 | 31.6 | 14 |  |
| algeria | Illizi | 195402.6 | 6299.3 | 31.0 | 2 |  |
| russia | Khabarovsk | 798471.1 | 29687.9 | 26.9 | 14 |  |
| algeria | Béchar | 164743.4 | 6299.3 | 26.2 | 12 |  |
| russia | Irkutsk | 724365.0 | 29687.9 | 24.4 | 14 |  |
| algeria | Tindouf | 153109.4 | 6299.3 | 24.3 | 12 |  |
| egypt | Al Bahr al Ahmar | 210848.8 | 9058.4 | 23.3 | 14 |  |
| venezuela | Amazonas | 180628.8 | 8002.9 | 22.6 | 12 |  |
| united_arab_emirates | Abu Dhabi | 62194.9 | 2914.2 | 21.3 | 10 |  |
| russia | Yamal-Nenets | 624973.2 | 29687.9 | 21.1 | 6 |  |
| russia | Chukchi Autonomous Okrug | 602301.6 | 29687.9 | 20.3 | 7 |  |
| japan | Hokkaidō | 78061.3 | 3988.7 | 19.6 | 12 |  |
| egypt | Matruh | 159348.4 | 9058.4 | 17.6 | 12 |  |
| russia | Khanty-Mansiy | 514985.0 | 29687.9 | 17.3 | 5 |  |
| myanmar | Shan | 166942.2 | 9705.6 | 17.2 | 16 |  |
| finland | Lapland | 96044.6 | 5841.7 | 16.4 | 5 |  |
| russia | Kamchatka | 473856.6 | 29687.9 | 16.0 | 5 |  |
| papua_new_guinea | Western | 99353.1 | 6287.2 | 15.8 | 11 |  |
| russia | Maga Buryatdan | 459239.6 | 29687.9 | 15.5 | 5 |  |
| malaysia | Sarawak | 122781.0 | 8025.7 | 15.3 | 14 |  |
| sweden | Norrbotten | 102650.3 | 6906.7 | 14.9 | 6 |  |
| france | Guyane française | 83592.1 | 5961.1 | 14.0 | 4 |  |
| russia | Komi | 414962.1 | 29687.9 | 14.0 | 12 |  |
| russia | Chita | 408686.7 | 29687.9 | 13.8 | 9 |  |
| yemen | Hadramawt | 164894.3 | 12042.2 | 13.7 | 14 |  |
| china | Xinjiang | 1584306.0 | 120332.0 | 13.2 | 14 |  |
| russia | Amur | 364789.8 | 29687.9 | 12.3 | 14 |  |
| algeria | Ghardaïa | 75504.6 | 6299.3 | 12.0 | 14 |  |
| russia | Buryat | 348927.1 | 29687.9 | 11.8 | 10 |  |
| algeria | El Bayadh | 68325.9 | 6299.3 | 10.8 | 14 |  |
| oman | Dhofar | 128249.0 | 11936.6 | 10.7 | 12 |  |
| uzbekistan | Karakalpakstan | 173897.0 | 16420.0 | 10.6 | 12 |  |
| russia | Tomsk | 314090.9 | 29687.9 | 10.6 | 7 |  |
| peru | Loreto | 375358.3 | 36592.4 | 10.3 | 11 |  |
| russia | Arkhangel'sk | 299623.3 | 29687.9 | 10.1 | 9 |  |
| myanmar | Sagaing | 96399.2 | 9705.6 | 9.9 | 14 |  |
| venezuela | Apure | 75427.8 | 8002.9 | 9.4 | 5 |  |
| china | Xizang | 1125188.5 | 120332.0 | 9.4 | 10 |  |
| malaysia | Sabah | 72979.0 | 8025.7 | 9.1 | 8 |  |
| myanmar | Kachin | 88082.0 | 9705.6 | 9.1 | 14 |  |
| china | Inner Mongol | 1080478.0 | 120332.0 | 9.0 | 14 |  |
| sweden | Västerbotten | 58087.8 | 6906.7 | 8.4 | 4 |  |
| iraq | Al-Anbar | 143471.8 | 17173.7 | 8.4 | 14 |  |
| mexico | Chihuahua | 248620.9 | 30499.8 | 8.2 | 14 |  |
| venezuela | Guárico | 65153.8 | 8002.9 | 8.1 | 4 |  |
