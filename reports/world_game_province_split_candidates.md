# Аудит кандидатов на деление игровых провинций мира

> Это только аудит. Геометрия клеток и исходных Admin-1 не изменяется.

## Правило v1

- `< 8` клеток: не рассматриваем.
- `>= 8` клеток и площадь `< 20,000` км²: **compact_protected** — не делить.
- `>= 8` клеток и площадь `20,000–40,000` км²: **review** — вручную проверить, пока не делить.
- `>= 8` клеток и площадь `>= 40,000` км²: **split** — можно автоматически делить по готовым клеткам.
- При делении стараемся держать не более `7` клеток на игровую провинцию.

## Итог

- Исходных записей: **4027**.
- Кандидатов с 8+ клетками: **556**.
- Защищённых компактных: **104**.
- На ручную проверку: **86**.
- Автоматически делить: **366**.
- Не затрагиваются вообще: **3471**.
- Проекция числа игровых провинций, если делить только `split`: **4477** (из 4027, +450).

## Compact protected — полный список

| Страна | Провинция | Площадь, км² | Клеток | Регион |
|---|---|---:|---:|---|
| japan | Saitama | 3855.0 | 8 | Канто |
| japan | Yamanashi | 4485.9 | 8 | Канто |
| japan | Chiba | 5142.5 | 8 | Канто |
| japan | Mie | 5804.2 | 8 | Кансай |
| netherlands | Noord-Brabant | 6028.2 | 8 | Брабант |
| japan | Ibaraki | 6298.3 | 8 | Канто |
| japan | Gunma | 6324.6 | 8 | Канто |
| netherlands | Gelderland | 6453.9 | 8 | Брабант |
| japan | Tochigi | 6463.4 | 8 | Канто |
| france | Loiret | 6667.4 | 8 | Иль-де-Франс |
| japan | Okayama | 6915.5 | 10 | Кансай |
| bangladesh | Barisal | 7047.4 | 8 | Бенгальская дельта |
| egypt | Ash Sharqiyah | 7363.4 | 9 | Дельта Нила |
| italy | Bozen | 7366.1 | 8 | Венето и Фриули |
| vietnam | Bình Thuận | 7589.7 | 8 | Дельта Меконга |
| japan | Hyōgo | 7790.1 | 11 | Кансай |
| nepal | Dhawalagiri | 7802.9 | 8 | Средняя Гангская равнина |
| greece | Kriti | 8284.2 | 8 | Греческие острова |
| nepal | Narayani | 8936.3 | 9 | Средняя Гангская равнина |
| nepal | Lumbini | 9025.0 | 10 | Средняя Гангская равнина |
| nepal | Bagmati | 9056.2 | 10 | Средняя Гангская равнина |
| laos | Attapu | 9171.9 | 9 | Дельта Меконга |
| cambodia | Kâmpóng Cham | 9325.7 | 9 | Дельта Меконга |
| indonesia | Banten | 9433.3 | 13 | Ява |
| nepal | Janakpur | 9686.5 | 10 | Средняя Гангская равнина |
| vietnam | Lâm Đồng | 9919.0 | 10 | Дельта Меконга |
| south_korea | South Jeolla | 10289.1 | 8 | Корейский юг |
| thailand | Phitsanulok | 10516.9 | 8 | Центральный Таиланд |
| south_korea | Gyeonggi | 10520.1 | 8 | Корейский юг |
| austria | Tirol | 10596.3 | 12 | Венето и Фриули |
| nepal | Rapti | 10620.7 | 11 | Средняя Гангская равнина |
| nepal | Sagarmatha | 10648.5 | 11 | Средняя Гангская равнина |
| japan | Gifu | 10653.9 | 10 | Центральный Хонсю |
| egypt | Al Fayyum | 10753.4 | 12 | Дельта Нила |
| nepal | Bheri | 10816.3 | 11 | Средняя Гангская равнина |
| vietnam | Kon Tum | 10990.3 | 11 | Дельта Меконга |
| jamaica | Saint Mary | 11077.6 | 8 | Большие Антильские острова |
| czech_republic | Středočeský | 11331.4 | 8 | Богемия |
| cambodia | Stœng Trêng | 11394.2 | 11 | Дельта Меконга |
| japan | Niigata | 11488.3 | 8 | Канто |
| kyrgyzstan | Talas | 11542.6 | 9 | Ферганская долина |
| vietnam | Điện Biên | 11760.1 | 11 | Долина Красной реки |
| nepal | Gandaki | 11990.5 | 13 | Средняя Гангская равнина |
| cambodia | Krâchéh | 12000.8 | 12 | Дельта Меконга |
| spain | Lérida | 12045.0 | 9 | Каталония |
| cambodia | Rôtânôkiri | 12157.1 | 12 | Дельта Меконга |
| vietnam | Thanh Hóa | 12352.5 | 11 | Долина Красной реки |
| thailand | Phetchabun | 12489.1 | 9 | Центральный Таиланд |
| cambodia | Pouthisat | 12610.7 | 13 | Дельта Меконга |
| denmark | Midtjylland | 12960.9 | 10 | Дания |
| vietnam | Đắk Lắk | 13077.5 | 13 | Дельта Меконга |
| thailand | Chaiyaphum | 13181.5 | 9 | Центральный Таиланд |
| cambodia | Kâmpóng Thum | 13350.9 | 13 | Дельта Меконга |
| cambodia | Môndól Kiri | 13451.1 | 13 | Дельта Меконга |
| cambodia | Batdâmbâng | 13461.1 | 10 | Центральный Таиланд |
| cambodia | Preah Vihéar | 13620.5 | 14 | Дельта Меконга |
| iraq | Dhi-Qar | 13670.5 | 8 | Нижняя Месопотамия |
| japan | Nagano | 13693.1 | 12 | Центральный Хонсю |
| cambodia | Kaôh Kong | 13828.8 | 14 | Дельта Меконга |
| greece | Thessalia | 13881.1 | 8 | Материковая Греция |
| indonesia | Nusa Tenggara Timur | 13913.4 | 8 | Малые Зондские острова |
| japan | Fukushima | 13966.6 | 8 | Канто |
| egypt | Al Buhayrah | 14056.3 | 12 | Дельта Нила |
| cambodia | Siemréab | 14111.6 | 14 | Дельта Меконга |
| indonesia | Nusa Tenggara Timur | 14356.5 | 8 | Малые Зондские острова |
| indonesia | Nusa Tenggara Barat | 14554.1 | 8 | Малые Зондские острова |
| vietnam | Son La | 14645.6 | 13 | Долина Красной реки |
| cuba | Camagüey | 14715.1 | 11 | Большие Антильские острова |
| spain | Sevilla | 14849.1 | 9 | Нижняя Андалусия |
| uzbekistan | Tashkent | 15144.6 | 12 | Ферганская долина |
| laos | Champasak | 15161.3 | 14 | Дельта Меконга |
| egypt | Al Isma`iliyah | 15185.7 | 12 | Дельта Нила |
| laos | Phôngsali | 15304.4 | 14 | Долина Красной реки |
| bangladesh | Rangpur | 15383.0 | 14 | Бенгальская дельта |
| poland | Lesser Poland | 15551.4 | 9 | Малая Польша |
| greece | Peloponnisos | 15926.6 | 9 | Материковая Греция |
| germany | Thüringen | 16005.4 | 10 | Саксония и Тюрингия |
| vietnam | Gia Lai | 16070.9 | 14 | Дельта Меконга |
| iraq | Maysan | 16164.1 | 9 | Нижняя Месопотамия |
| austria | Steiermark | 16391.5 | 9 | Австрийские земли |
| thailand | Tak | 16465.8 | 12 | Центральный Таиланд |
| israel | HaDarom | 16593.2 | 12 | Левантийское побережье |
| kyrgyzstan | Batken | 16900.4 | 12 | Ферганская долина |
| vietnam | Nghệ An | 17090.6 | 14 | Долина Красной реки |
| iraq | Al-Basrah | 17147.6 | 10 | Нижняя Месопотамия |
| laos | Houaphan | 17251.5 | 14 | Долина Красной реки |
| iraq | Wasit | 17598.9 | 10 | Нижняя Месопотамия |
| poland | Kuyavian-Pomeranian | 17707.8 | 8 | Западная Польша |
| poland | Subcarpathian | 17979.1 | 10 | Малая Польша |
| north_korea | Hamgyŏng-bukto | 18089.0 | 8 | Корейский север |
| germany | Sachsen | 18170.0 | 11 | Саксония и Тюрингия |
| poland | Łódź | 18452.3 | 10 | Малая Польша |
| north_korea | Hamgyŏng-namdo | 18513.1 | 8 | Корейский север |
| poland | Pomeranian | 18601.2 | 8 | Западная Польша |
| iran | Ilam | 18819.2 | 10 | Нижняя Месопотамия |
| bangladesh | Rajshahi | 18874.5 | 14 | Бенгальская дельта |
| syria | Aleppo | 18894.3 | 8 | Внутренний Левант |
| south_korea | Gangwon | 19152.4 | 14 | Корейский юг |
| austria | Niederösterreich | 19462.7 | 11 | Австрийские земли |
| united_states_of_america | New Jersey | 19613.4 | 9 | Среднеатлантическое побережье |
| greece | Kentriki Makedonia | 19632.3 | 9 | Македония и Фракия |
| poland | Lower Silesian | 19704.0 | 9 | Западная Польша |
| turkey | Sanliurfa | 19877.1 | 8 | Верхняя Месопотамия |
| thailand | Kanchanaburi | 19943.4 | 14 | Центральный Таиланд |

## Review — полный список

| Страна | Провинция | Площадь, км² | Клеток | Регион |
|---|---|---:|---:|---|
| south_korea | North Gyeongsang | 20048.3 | 14 | Корейский юг |
| iraq | Diyala | 20383.1 | 11 | Нижняя Месопотамия |
| iran | Hamadan | 20455.4 | 9 | Каспийское побережье |
| malaysia | Perak | 20821.0 | 9 | Малайский полуостров |
| thailand | Nakhon Ratchasima | 20835.8 | 14 | Центральный Таиланд |
| united_states_of_america | Massachusetts | 20837.2 | 9 | Новая Англия |
| germany | Hessen | 20972.1 | 12 | Гессен |
| turkey | Antalya | 21251.6 | 9 | Западная Анатолия |
| india | Mizoram | 21344.4 | 9 | Ассам и Брахмапутра |
| india | Manipur | 21720.3 | 9 | Ассам и Брахмапутра |
| bangladesh | Khulna | 21817.4 | 14 | Бенгальская дельта |
| iran | Zanjan | 22250.1 | 10 | Каспийское побережье |
| bosnia_and_herzegovina | Banja Luka | 22395.6 | 10 | Босния и Герцеговина |
| syria | Hasaka (Al Haksa) | 22403.9 | 9 | Верхняя Месопотамия |
| germany | Rheinland-Pfalz | 22535.0 | 12 | Рейнская область |
| thailand | Chiang Mai | 22855.9 | 10 | Иравади |
| india | Meghalaya | 23133.7 | 10 | Ассам и Брахмапутра |
| iran | Kermanshah | 23471.4 | 13 | Нижняя Месопотамия |
| poland | West Pomeranian | 23534.5 | 11 | Западная Польша |
| united_states_of_america | New Hampshire | 23930.6 | 10 | Новая Англия |
| poland | Lublin | 24492.6 | 8 | Мазовия и Подляшье |
| poland | Warmian-Masurian | 24522.3 | 8 | Мазовия и Подляшье |
| iran | Mazandaran | 24702.6 | 11 | Каспийское побережье |
| united_states_of_america | Vermont | 24763.3 | 11 | Новая Англия |
| colombia | Córdoba | 25256.8 | 11 | Верхняя Андалусия |
| iraq | Sala ad-Din | 25418.3 | 10 | Верхняя Месопотамия |
| tajikistan | Leninabad | 25509.4 | 12 | Ферганская долина |
| indonesia | Sulawesi Tenggara | 25591.5 | 9 | Сулавеси |
| nicaragua | Atlántico Sur | 25804.7 | 8 | Центральноамериканский перешеек |
| syria | Dayr Az Zawr | 26573.6 | 10 | Верхняя Месопотамия |
| jordan | Mafraq | 26730.7 | 11 | Внутренний Левант |
| egypt | Shamal Sina' | 27289.9 | 12 | Дельта Нила |
| bangladesh | Chittagong | 28372.3 | 14 | Бенгальская дельта |
| tajikistan | Tadzhikistan Territories | 28777.6 | 12 | Ферганская долина |
| kyrgyzstan | Osh | 28909.9 | 12 | Ферганская долина |
| sweden | Västra Götaland | 28991.8 | 11 | Южная Швеция |
| egypt | Janub Sina' | 29010.3 | 12 | Дельта Нила |
| iran | Lorestan | 29082.9 | 14 | Нижняя Месопотамия |
| iraq | An-Najaf | 29292.0 | 14 | Нижняя Месопотамия |
| poland | Greater Poland | 29387.8 | 13 | Западная Польша |
| myanmar | Kayin | 29407.1 | 13 | Иравади |
| ukraine | Zhytomyr | 29599.5 | 8 | Правобережная Украина |
| iran | Kordestan | 29732.7 | 12 | Каспийское побережье |
| mexico | Guanajuato | 30499.8 | 9 | Центральная Мексика |
| bangladesh | Dhaka | 30548.8 | 14 | Бенгальская дельта |
| germany | Brandenburg | 30771.5 | 11 | Бранденбург |
| colombia | Santander | 30800.4 | 8 | Колумбийские Анды |
| morocco | Marrakech - Tensift - Al Haouz | 31960.6 | 9 | Марокканское побережье |
| nicaragua | Atlántico Norte | 32507.1 | 10 | Центральноамериканский перешеек |
| united_states_of_america | Maryland | 32598.7 | 14 | Среднеатлантическое побережье |
| belarus | Brest | 32647.9 | 8 | Беларусь |
| myanmar | Ayeyarwady | 32775.4 | 15 | Иравади |
| jordan | Ma`an | 33009.9 | 12 | Внутренний Левант |
| indonesia | Lampung | 33066.5 | 9 | Суматра |
| ukraine | Odessa | 33177.9 | 12 | Молдавия |
| myanmar | Rakhine | 33601.3 | 15 | Иравади |
| chile | La Araucanía | 33811.9 | 8 | Центральное Чили |
| kyrgyzstan | Jalal-Abad | 33862.5 | 12 | Ферганская долина |
| china | Hainan | 33978.6 | 14 | Долина Красной реки |
| peru | Cajamarca | 34338.3 | 8 | Эквадорские Анды |
| germany | Nordrhein-Westfalen | 34460.0 | 12 | Вестфалия |
| poland | Masovian | 35006.9 | 12 | Мазовия и Подляшье |
| algeria | Djelfa | 35146.3 | 9 | Алжирское побережье |
| nigeria | Kwara | 35793.9 | 9 | Бенинский залив |
| germany | Baden-Württemberg | 35813.9 | 12 | Швабия |
| indonesia | Sumatera Barat | 35865.8 | 10 | Суматра |
| malaysia | Pahang | 36061.3 | 14 | Малайский полуостров |
| myanmar | Tanintharyi | 36065.1 | 14 | Центральный Таиланд |
| guatemala | Petén | 36191.6 | 10 | Гватемальское нагорье |
| myanmar | Bago | 36442.7 | 16 | Иравади |
| myanmar | Mandalay | 36682.2 | 16 | Иравади |
| indonesia | Jawa Tengah | 37150.5 | 14 | Ява |
| myanmar | Chin | 37192.1 | 16 | Иравади |
| egypt | Al Jizah | 37442.0 | 12 | Дельта Нила |
| chile | Coquimbo | 37490.7 | 8 | Центральное Чили |
| venezuela | Zulia | 37701.9 | 8 | Карибское побережье Новой Гранады |
| iraq | Ninawa | 37789.6 | 14 | Верхняя Месопотамия |
| ivory_coast | Zanzan | 38022.2 | 8 | Золотой Берег |
| india | Kerala | 38027.4 | 14 | Малабарское побережье |
| indonesia | Jawa Barat | 38061.2 | 14 | Ява |
| yemen | Shabwah | 38357.8 | 10 | Йеменское нагорье |
| yemen | Al Jawf | 38872.8 | 10 | Йеменское нагорье |
| iran | Markazi | 39809.4 | 12 | Каспийское побережье |
| senegal | Tambacounda | 39831.3 | 8 | Сенегамбия |
| tunisia | Tataouine | 39861.1 | 11 | Ифрикия |
| ghana | Brong Ahafo | 39946.9 | 9 | Золотой Берег |

## Split — полный список

| Страна | Провинция | Площадь, км² | Клеток | Игровых провинций | Регион |
|---|---|---:|---:|---:|---|
| uzbekistan | Bukhoro | 40132.7 | 10 | 2 | Мавераннахр |
| turkey | Konya | 40282.9 | 9 | 2 | Центральная Анатолия |
| belarus | Gomel | 40544.3 | 10 | 2 | Беларусь |
| peru | Amazonas | 40870.5 | 9 | 2 | Эквадорские Анды |
| peru | Piura | 40920.9 | 9 | 2 | Эквадорские Анды |
| switzerland | Appenzell Innerrhoden | 41239.7 | 12 | 2 | Швейцария |
| indonesia | Jawa Timur | 42142.6 | 14 | 2 | Ява |
| india | Jammu and Kashmir | 42562.1 | 16 | 3 | Пенджаб |
| mexico | Puebla | 43365.3 | 12 | 2 | Центральная Мексика |
| colombia | Casanare | 43884.3 | 11 | 2 | Колумбийские Анды |
| canada | Nova Scotia | 44378.7 | 14 | 2 | Новая Англия |
| nigeria | Kaduna | 44698.5 | 8 | 2 | Хаусаленд |
| india | Haryana | 45328.8 | 16 | 3 | Пенджаб |
| myanmar | Magway | 45919.1 | 16 | 3 | Иравади |
| indonesia | Sulawesi Selatan | 45933.5 | 14 | 2 | Сулавеси |
| nigeria | Yobe | 46192.0 | 8 | 2 | Хаусаленд |
| algeria | El Oued | 46390.2 | 13 | 2 | Ифрикия |
| iran | East Azarbaijan | 46416.1 | 8 | 2 | Армянское нагорье |
| colombia | Chocó | 46837.5 | 12 | 2 | Колумбийские Анды |
| s_sudan | Central Equatoria | 47215.9 | 10 | 2 | Великие озёра |
| united_republic_of_tanzania | Kigoma | 47669.1 | 11 | 2 | Великие озёра |
| germany | Niedersachsen | 48014.3 | 12 | 2 | Вестфалия |
| nigeria | Bauchi | 49128.6 | 9 | 2 | Хаусаленд |
| ethiopia | Benshangul-Gumaz | 49646.5 | 8 | 2 | Эфиопское нагорье |
| russia | Dagestan | 49804.8 | 14 | 2 | Грузия и Закавказье |
| syria | Homs (Hims) | 50182.7 | 12 | 2 | Внутренний Левант |
| india | Punjab | 50307.5 | 16 | 3 | Пенджаб |
| russia | Smolensk | 50627.5 | 8 | 2 | Центральная Россия |
| indonesia | Jambi | 51124.5 | 14 | 2 | Суматра |
| iraq | Al-Muthannia | 52272.8 | 14 | 2 | Нижняя Месопотамия |
| russia | Voronezh | 52345.4 | 11 | 2 | Левобережная Украина |
| sweden | Jämtland | 53227.7 | 8 | 2 | Центральная Швеция |
| central_african_republic | Ouham | 53537.2 | 8 | 2 | Камерунское нагорье |
| indonesia | Aceh | 54047.6 | 14 | 2 | Малайский полуостров |
| colombia | Guaviare | 55227.7 | 14 | 2 | Колумбийские Анды |
| india | Himachal Pradesh | 55555.4 | 16 | 3 | Пенджаб |
| mexico | Campeche | 56874.3 | 8 | 2 | Юкатан |
| indonesia | Sulawesi Tengah | 57419.0 | 14 | 2 | Сулавеси |
| morocco | Oriental | 57961.5 | 10 | 2 | Атлас |
| morocco | Meknès - Tafilalet | 58709.5 | 10 | 2 | Атлас |
| mexico | Michoacán | 59025.8 | 16 | 3 | Центральная Мексика |
| democratic_republic_of_the_congo | Nord-Kivu | 59916.6 | 13 | 2 | Великие озёра |
| nigeria | Taraba | 60732.0 | 9 | 2 | Камерунское нагорье |
| mauritania | Inchiri | 61626.8 | 12 | 2 | Сенегамбия |
| cameroon | Adamaoua | 61998.3 | 10 | 2 | Камерунское нагорье |
| united_states_of_america | West Virginia | 62118.1 | 9 | 2 | Аппалачи |
| united_arab_emirates | Abu Dhabi | 62194.9 | 10 | 2 | Персидский залив — побережье |
| colombia | Antioquia | 63568.3 | 16 | 3 | Колумбийские Анды |
| democratic_republic_of_the_congo | Sud-Kivu | 63676.9 | 14 | 2 | Великие озёра |
| yemen | Al Mahrah | 63720.1 | 14 | 2 | Йеменское нагорье |
| australia | Tasmania | 63995.8 | 9 | 2 | Тасмания |
| mexico | San Luis Potosí | 64007.6 | 16 | 3 | Центральная Мексика |
| latvia | Jekabpils | 64112.3 | 12 | 2 | Ливония и Эстония |
| india | Ladakh | 64228.0 | 16 | 3 | Пенджаб |
| mexico | Guerrero | 65032.5 | 16 | 3 | Центральная Мексика |
| oman | Al Wusta | 65286.8 | 10 | 2 | Оманское побережье |
| iran | Hormozgan | 65564.1 | 10 | 2 | Оманское побережье |
| russia | Stavropol' | 66555.4 | 14 | 2 | Северный Кавказ |
| united_republic_of_tanzania | Lindi | 66677.3 | 10 | 2 | Побережье Суахили |
| cameroon | Nord | 66925.7 | 10 | 2 | Камерунское нагорье |
| russia | Tatarstan | 67628.7 | 8 | 2 | Поволжье |
| mozambique | Inhambane | 68028.4 | 8 | 2 | Южноафриканский Хайвельд |
| indonesia | Sumatera Utara | 68050.7 | 14 | 2 | Суматра |
| s_sudan | Eastern Equatoria | 68094.0 | 10 | 2 | Кенийское нагорье |
| algeria | El Bayadh | 68325.9 | 14 | 2 | Алжирское побережье |
| cameroon | Centre | 68921.1 | 11 | 2 | Камерунское нагорье |
| madagascar | Atsimo-Andrefana | 69125.2 | 8 | 2 | Мадагаскарское нагорье |
| germany | Bayern | 69855.3 | 14 | 2 | Бавария и Франкония |
| mexico | Veracruz | 70844.6 | 14 | 2 | Мексиканское побережье Мексиканского залива |
| mauritania | Trarza | 71201.8 | 14 | 2 | Сенегамбия |
| colombia | Guainía | 71600.3 | 16 | 3 | Колумбийские Анды |
| morocco | Souss - Massa - Draâ | 72001.4 | 14 | 2 | Марокканское побережье |
| canada | New Brunswick | 72249.4 | 14 | 2 | Новая Англия |
| russia | Kalmyk | 72890.0 | 10 | 2 | Южная Россия и Предкавказье |
| malaysia | Sabah | 72979.0 | 8 | 2 | Борнео |
| turkmenistan | Tashauz | 73092.0 | 12 | 2 | Хорезм и нижняя Амударья |
| united_kingdom | Northumberland | 73138.6 | 10 | 2 | Шотландское нагорье |
| morocco | Laâyoune - Boujdour - Sakia El Hamra | 73224.1 | 14 | 2 | Марокканское побережье |
| mexico | Chiapas | 73863.5 | 14 | 2 | Гватемальское нагорье |
| peru | Cusco | 74446.5 | 8 | 2 | Перуанские Анды |
| russia | Nizhegorod | 74600.3 | 8 | 2 | Поволжье |
| russia | Sakhalin | 75420.1 | 12 | 2 | Хоккайдо |
| algeria | Ghardaïa | 75504.6 | 14 | 2 | Алжирское побережье |
| morocco | Oued el Dahab | 75629.1 | 14 | 2 | Сенегамбия |
| s_sudan | Upper Nile | 76227.4 | 8 | 2 | Суданская долина Нила |
| mozambique | Gaza | 76394.5 | 8 | 2 | Южноафриканский Хайвельд |
| argentina | San Luis | 76970.9 | 14 | 2 | Центральное Чили |
| iran | Khuzestan | 77040.1 | 14 | 2 | Фарс и Хузестан |
| japan | Hokkaidō | 78061.3 | 12 | 2 | Хоккайдо |
| india | Jharkhand | 78096.5 | 14 | 2 | Бенгальская дельта |
| argentina | Entre Ríos | 78126.1 | 11 | 2 | Месопотамия Южной Америки |
| mozambique | Nampula | 78137.2 | 9 | 2 | Мадагаскарское нагорье |
| nigeria | Niger | 78211.0 | 16 | 3 | Бенинский залив |
| mozambique | Cabo Delgado | 78262.0 | 11 | 2 | Побережье Суахили |
| ghana | Northern | 78288.2 | 14 | 2 | Золотой Берег |
| sudan | Southern Darfur | 78958.2 | 9 | 2 | Суданская долина Нила |
| chile | Atacama | 79239.1 | 14 | 2 | Центральное Чили |
| india | Assam | 80122.4 | 14 | 2 | Ассам и Брахмапутра |
| belarus | Vitebsk | 80425.9 | 14 | 2 | Беларусь |
| mexico | Zacatecas | 80600.3 | 12 | 2 | Тихоокеанское побережье Мексики |
| united_states_of_america | South Carolina | 80676.2 | 15 | 3 | Юго-Восток США |
| india | Arunachal Pradesh | 80775.9 | 14 | 2 | Ассам и Брахмапутра |
| s_sudan | Western Equatoria | 81570.4 | 16 | 3 | Великие озёра |
| indonesia | Riau | 82041.5 | 14 | 2 | Суматра |
| mali | Mopti | 82435.4 | 10 | 2 | Средний Нигер |
| kenya | Coast | 82481.4 | 12 | 2 | Кенийское нагорье |
| russia | Krasnodar | 83004.7 | 12 | 2 | Южная Россия и Предкавказье |
| iran | South Khorasan | 83064.7 | 10 | 2 | Хорасан |
| peru | Madre de Dios | 83101.5 | 9 | 2 | Перуанские Анды |
| russia | Tver' | 83339.0 | 10 | 2 | Северо-Западная Россия |
| united_states_of_america | Maine | 83652.7 | 14 | 2 | Новая Англия |
| russia | Leningrad | 84987.8 | 10 | 2 | Северо-Западная Россия |
| indonesia | Sumatera Selatan | 85092.8 | 14 | 2 | Суматра |
| mexico | Jalisco | 85668.8 | 13 | 2 | Тихоокеанское побережье Мексики |
| canada | Québec | 86305.4 | 14 | 2 | Новая Англия |
| colombia | Meta | 86620.4 | 16 | 3 | Колумбийские Анды |
| indonesia | Papua Barat | 87466.3 | 12 | 2 | Молукки и Папуа |
| s_sudan | Western Bahr el Ghazal | 87724.0 | 10 | 2 | Суданская долина Нила |
| myanmar | Kachin | 88082.0 | 14 | 2 | Ассам и Брахмапутра |
| argentina | San Juan | 88771.4 | 14 | 2 | Центральное Чили |
| argentina | Corrientes | 88791.6 | 13 | 2 | Месопотамия Южной Америки |
| iran | Semnan | 89725.2 | 13 | 2 | Центральное Иранское плато |
| saudi_arabia | Najran | 89753.6 | 14 | 2 | Йеменское нагорье |
| argentina | La Rioja | 90213.7 | 14 | 2 | Старая Кастилия |
| colombia | Caquetá | 90448.6 | 16 | 3 | Колумбийские Анды |
| india | West Bengal | 92091.5 | 14 | 2 | Бенгальская дельта |
| united_states_of_america | Indiana | 92369.7 | 16 | 3 | Район Великих озёр |
| mexico | Oaxaca | 92378.9 | 14 | 2 | Мексиканское побережье Мексиканского залива |
| saudi_arabia | `Asir | 92408.7 | 14 | 2 | Йеменское нагорье |
| niger | Tillabéri | 92651.0 | 12 | 2 | Средний Нигер |
| turkmenistan | Chardzhou | 92815.8 | 14 | 2 | Мавераннахр |
| south_africa | KwaZulu-Natal | 93651.3 | 13 | 2 | Натал и Драконовы горы |
| brazil | Santa Catarina | 93859.6 | 13 | 2 | Южная Бразилия |
| south_africa | Mpumalanga | 94219.4 | 10 | 2 | Южноафриканский Хайвельд |
| india | Bihar | 94467.6 | 18 | 3 | Средняя Гангская равнина |
| ethiopia | Afar | 94857.9 | 14 | 2 | Эфиопское нагорье |
| myanmar | Sagaing | 96399.2 | 14 | 2 | Ассам и Брахмапутра |
| papua_new_guinea | Western | 99353.1 | 11 | 2 | Высокогорья Новой Гвинеи |
| russia | Rostov | 99735.0 | 14 | 2 | Южная Россия и Предкавказье |
| saudi_arabia | Tabuk | 100133.1 | 12 | 2 | Хиджаз |
| china | Zhejiang | 100139.0 | 12 | 2 | Дельта Янцзы |
| morocco | Guelmim - Es-Semara | 101530.7 | 12 | 2 | Атлас |
| united_states_of_america | Virginia | 101980.0 | 14 | 2 | Аппалачи |
| pakistan | K.P. | 102680.0 | 9 | 2 | Кабул и Гиндукуш |
| russia | Saratov | 102721.3 | 11 | 2 | Поволжье |
| united_states_of_america | Kentucky | 103561.4 | 14 | 2 | Аппалачи |
| peru | Ucayali | 104163.5 | 12 | 2 | Перуанские Анды |
| niger | Tahoua | 104915.4 | 13 | 2 | Средний Нигер |
| south_africa | North West | 105043.9 | 12 | 2 | Южноафриканский Хайвельд |
| china | Jiangsu | 105261.8 | 12 | 2 | Дельта Янцзы |
| united_states_of_america | Tennessee | 109255.3 | 16 | 3 | Юго-Восток США |
| cameroon | Est | 109315.8 | 14 | 2 | Камерунское нагорье |
| uzbekistan | Navoi | 111094.3 | 14 | 2 | Мавераннахр |
| iran | Esfahan | 111828.6 | 14 | 2 | Центральное Иранское плато |
| kazakhstan | Atyrau | 111931.1 | 16 | 3 | Южная Россия и Предкавказье |
| russia | Volgograd | 113889.8 | 16 | 3 | Южная Россия и Предкавказье |
| ethiopia | Southern Nations, Nationalities and Peoples | 114639.4 | 14 | 2 | Эфиопское нагорье |
| kazakhstan | South Kazakhstan | 114883.8 | 12 | 2 | Ферганская долина |
| india | Telangana | 115054.2 | 18 | 3 | Декан |
| united_states_of_america | Ohio | 116028.9 | 14 | 2 | Аппалачи |
| saudi_arabia | Al Jawf | 117154.0 | 12 | 2 | Внутренний Левант |
| united_states_of_america | Pennsylvania | 118442.5 | 14 | 2 | Среднеатлантическое побережье |
| united_states_of_america | Louisiana | 119463.8 | 16 | 3 | Долина Миссисипи |
| russia | Kirov | 119843.9 | 13 | 2 | Поволжье |
| china | Fujian | 120332.0 | 14 | 2 | Южнокитайское побережье |
| s_sudan | Jonglei | 121156.3 | 14 | 2 | Эфиопское нагорье |
| mexico | Durango | 121831.5 | 9 | 2 | Северная Мексика |
| saudi_arabia | Ha'il | 121922.4 | 12 | 2 | Хиджаз |
| russia | Orenburg | 122049.1 | 8 | 2 | Урал |
| malaysia | Sarawak | 122781.0 | 14 | 2 | Борнео |
| chile | Antofagasta | 123222.9 | 8 | 2 | Альтиплано |
| united_states_of_america | Mississippi | 124222.1 | 16 | 3 | Долина Миссисипи |
| saudi_arabia | Al Hudud ash Shamaliyah | 124656.1 | 14 | 2 | Нижняя Месопотамия |
| brazil | Pernambuco | 125430.3 | 16 | 3 | Северо-Восточная Бразилия |
| iran | Fars | 125452.6 | 14 | 2 | Фарс и Хузестан |
| south_africa | Limpopo | 126015.0 | 14 | 2 | Южноафриканский Хайвельд |
| zambia | North-Western | 126186.8 | 9 | 2 | Замбези |
| kenya | North-Eastern | 127407.2 | 14 | 2 | Кенийское нагорье |
| democratic_republic_of_the_congo | Maniema | 127775.2 | 16 | 3 | Великие озёра |
| iran | Yazd | 127795.0 | 14 | 2 | Центральное Иранское плато |
| united_states_of_america | North Carolina | 127908.1 | 14 | 2 | Аппалачи |
| oman | Dhofar | 128249.0 | 12 | 2 | Оманское побережье |
| zambia | Western | 129189.3 | 9 | 2 | Замбези |
| mozambique | Niassa | 129656.6 | 10 | 2 | Танзанийское плато |
| south_africa | Free State | 129767.3 | 14 | 2 | Южноафриканский Хайвельд |
| south_africa | Western Cape | 130497.3 | 14 | 2 | Капская область |
| argentina | Santa Fe | 131592.4 | 14 | 2 | Месопотамия Южной Америки |
| india | Tamil Nadu | 131801.8 | 14 | 2 | Тамильское побережье |
| united_states_of_america | New York | 133348.6 | 14 | 2 | Среднеатлантическое побережье |
| bolivia | La Paz | 134245.3 | 8 | 2 | Альтиплано |
| united_states_of_america | Alabama | 134548.3 | 16 | 3 | Юго-Восток США |
| india | Chhattisgarh | 135353.7 | 16 | 3 | Центральная Индия |
| iran | Razavi Khorasan | 137363.9 | 14 | 2 | Хорасан |
| united_states_of_america | Arkansas | 137955.3 | 16 | 3 | Долина Миссисипи |
| sudan | South Kordufan | 139569.4 | 14 | 2 | Суданская долина Нила |
| china | Anhui | 139635.0 | 12 | 2 | Дельта Янцзы |
| kazakhstan | Zhambyl | 140304.3 | 10 | 2 | Тянь-Шань |
| pakistan | Sind | 140540.1 | 16 | 3 | Долина Инда |
| iraq | Al-Anbar | 143471.8 | 14 | 2 | Верхняя Месопотамия |
| argentina | La Pampa | 143497.0 | 16 | 3 | Пампа |
| russia | Bashkortostan | 143595.3 | 9 | 2 | Урал |
| saudi_arabia | Al Madinah | 144584.9 | 12 | 2 | Хиджаз |
| united_states_of_america | Iowa | 145714.7 | 11 | 2 | Великие равнины |
| niger | Diffa | 146157.3 | 9 | 2 | Озеро Чад |
| mali | Kidal | 146496.9 | 16 | 3 | Средний Нигер |
| china | Liaoning | 146910.9 | 14 | 2 | Корейский север |
| sudan | River Nile | 147294.6 | 14 | 2 | Суданская долина Нила |
| united_states_of_america | Florida | 147531.2 | 14 | 2 | Флорида |
| indonesia | Kalimantan Barat | 147558.1 | 14 | 2 | Борнео |
| saudi_arabia | Makkah | 149965.3 | 12 | 2 | Хиджаз |
| argentina | Mendoza | 150069.8 | 14 | 2 | Центральное Чили |
| brazil | Ceará | 150900.9 | 16 | 3 | Северо-Восточная Бразилия |
| mexico | Coahuila | 151517.3 | 11 | 2 | Северная Мексика |
| united_states_of_america | Illinois | 151864.4 | 16 | 3 | Долина Миссисипи |
| united_states_of_america | Georgia | 152015.0 | 16 | 3 | Юго-Восток США |
| kazakhstan | West Kazakhstan | 152722.4 | 16 | 3 | Поволжье |
| indonesia | Kalimantan Tengah | 152766.4 | 14 | 2 | Борнео |
| algeria | Tindouf | 153109.4 | 12 | 2 | Атлас |
| china | Shanxi | 155531.2 | 16 | 3 | Лёссовое плато |
| china | Shandong | 155959.6 | 14 | 2 | Шаньдун |
| argentina | Salta | 156088.8 | 9 | 2 | Гран-Чако |
| india | Odisha | 156220.4 | 14 | 2 | Бенгальская дельта |
| ethiopia | Amhara | 157245.6 | 14 | 2 | Эфиопское нагорье |
| kenya | Eastern | 158270.5 | 14 | 2 | Кенийское нагорье |
| botswana | Central | 159261.0 | 16 | 3 | Южноафриканский Хайвельд |
| egypt | Matruh | 159348.4 | 12 | 2 | Дельта Нила |
| india | Andhra Pradesh | 160951.4 | 18 | 3 | Декан |
| russia | Perm' | 161963.6 | 10 | 2 | Урал |
| russia | Primor'ye | 163301.6 | 9 | 2 | Амур и Приморье |
| algeria | Béchar | 164743.4 | 12 | 2 | Атлас |
| yemen | Hadramawt | 164894.3 | 14 | 2 | Йеменское нагорье |
| kazakhstan | Mangghystau | 165002.7 | 12 | 2 | Хорезм и нижняя Амударья |
| china | Henan | 166021.1 | 16 | 3 | Северокитайская равнина |
| myanmar | Shan | 166942.2 | 16 | 3 | Иравади |
| united_states_of_america | Wisconsin | 167234.1 | 16 | 3 | Район Великих озёр |
| argentina | Córdoba | 167693.7 | 14 | 2 | Верхняя Андалусия |
| somaliland | Somaliland | 168170.4 | 8 | 2 | Африканский Рог |
| china | Jiangxi | 169149.5 | 16 | 3 | Средняя Янцзы |
| south_africa | Eastern Cape | 169710.5 | 14 | 2 | Натал и Драконовы горы |
| united_states_of_america | Washington | 172968.3 | 14 | 2 | Тихоокеанский Северо-Запад |
| mali | Gao | 173474.2 | 16 | 3 | Средний Нигер |
| uzbekistan | Karakalpakstan | 173897.0 | 12 | 2 | Хорезм и нижняя Амударья |
| china | Guizhou | 174985.1 | 16 | 3 | Юньнань и Гуйчжоу |
| china | Guangdong | 175703.7 | 14 | 2 | Южнокитайское побережье |
| united_states_of_america | Missouri | 180077.8 | 16 | 3 | Долина Миссисипи |
| venezuela | Amazonas | 180628.8 | 12 | 2 | Венесуэльские Льянос |
| united_states_of_america | North Dakota | 181581.9 | 14 | 2 | Великие равнины |
| united_states_of_america | Oklahoma | 183390.8 | 16 | 3 | Техас и нижний Рио-Гранде |
| china | Hubei | 184971.8 | 16 | 3 | Средняя Янцзы |
| iran | Kerman | 185192.9 | 14 | 2 | Центральное Иранское плато |
| niger | Zinder | 185736.5 | 16 | 3 | Хаусаленд |
| mauritania | Hodh ech Chargui | 185794.4 | 10 | 2 | Западный Сахель |
| india | Gujarat | 186337.2 | 14 | 2 | Гуджарат |
| russia | Sverdlovsk | 187755.5 | 12 | 2 | Урал |
| china | Jilin | 190950.1 | 16 | 3 | Маньчжурия |
| chad | Ennedi | 191324.2 | 12 | 2 | Озеро Чад |
| india | Karnataka | 195469.8 | 18 | 3 | Декан |
| indonesia | Kalimantan Timur | 195601.2 | 14 | 2 | Борнео |
| brazil | Paraná | 199087.5 | 16 | 3 | Южная Бразилия |
| angola | Cuando Cubango | 199112.0 | 12 | 2 | Ангольское нагорье |
| angola | Moxico | 199189.2 | 12 | 2 | Ангольское нагорье |
| united_states_of_america | South Dakota | 200214.3 | 15 | 3 | Великие равнины |
| kazakhstan | Qostanay | 200658.4 | 9 | 2 | Казахская степь |
| united_states_of_america | Nebraska | 200884.6 | 15 | 3 | Великие равнины |
| sudan | Red Sea | 201069.8 | 12 | 2 | Хиджаз |
| china | Shaanxi | 203153.0 | 16 | 3 | Лёссовое плато |
| united_states_of_america | Idaho | 207245.1 | 9 | 2 | Скалистые горы |
| algeria | Ouargla | 210516.4 | 14 | 2 | Ифрикия |
| egypt | Al Bahr al Ahmar | 210848.8 | 14 | 2 | Долина Нила |
| bolivia | El Beni | 211646.8 | 13 | 2 | Альтиплано |
| china | Hunan | 212588.9 | 16 | 3 | Средняя Янцзы |
| pakistan | Punjab | 215048.1 | 16 | 3 | Пенджаб |
| united_states_of_america | Kansas | 215066.2 | 16 | 3 | Великие равнины |
| china | Hebei | 217630.4 | 16 | 3 | Северокитайская равнина |
| kenya | Rift Valley | 220733.0 | 14 | 2 | Кенийское нагорье |
| mauritania | Adrar | 221364.6 | 12 | 2 | Западный Сахель |
| united_states_of_america | Utah | 221625.3 | 10 | 2 | Скалистые горы |
| united_states_of_america | Minnesota | 222856.3 | 16 | 3 | Район Великих озёр |
| kazakhstan | Qyzylorda | 223017.2 | 10 | 2 | Казахская степь |
| kazakhstan | Almaty | 223108.6 | 12 | 2 | Тянь-Шань |
| australia | Victoria | 229220.3 | 16 | 3 | Юго-Восточная Австралия |
| china | Guangxi | 237702.8 | 14 | 2 | Долина Красной реки |
| argentina | Santa Cruz | 237759.9 | 12 | 2 | Южные Анды |
| brazil | Rondônia | 239103.1 | 14 | 2 | Альтиплано |
| india | Uttar Pradesh | 239618.9 | 18 | 3 | Верхняя Гангская равнина |
| sudan | North Kordufan | 244982.5 | 14 | 2 | Суданская долина Нила |
| brazil | São Paulo | 247738.1 | 16 | 3 | Юго-Восточная Бразилия |
| united_states_of_america | Michigan | 247820.3 | 16 | 3 | Район Великих озёр |
| chad | Borkou | 247902.0 | 14 | 2 | Озеро Чад |
| mexico | Chihuahua | 248620.9 | 14 | 2 | Северная Мексика |
| united_states_of_america | Oregon | 249877.3 | 14 | 2 | Тихоокеанский Северо-Запад |
| venezuela | Bolívar | 252646.3 | 14 | 2 | Венесуэльские Льянос |
| united_states_of_america | Wyoming | 252895.5 | 11 | 2 | Скалистые горы |
| brazil | Piauí | 253962.5 | 16 | 3 | Северо-Восточная Бразилия |
| mauritania | Tiris Zemmour | 257872.4 | 12 | 2 | Атлас |
| brazil | Rio Grande do Sul | 268899.7 | 16 | 3 | Южная Бразилия |
| united_states_of_america | Colorado | 268982.0 | 16 | 3 | Великие равнины |
| brazil | Tocantins | 281890.6 | 16 | 3 | Бразильское внутреннее плато |
| sudan | North Darfur | 293634.7 | 14 | 2 | Суданская долина Нила |
| united_states_of_america | Nevada | 295233.0 | 10 | 2 | Межгорный Запад |
| indonesia | Papua | 295663.6 | 12 | 2 | Молукки и Папуа |
| united_states_of_america | Arizona | 295754.5 | 10 | 2 | Юго-Западные пустыни |
| democratic_republic_of_the_congo | Bandundu | 297403.4 | 14 | 2 | Нижнее Конго |
| russia | Arkhangel'sk | 299623.3 | 9 | 2 | Русский Север |
| argentina | Buenos Aires | 301106.5 | 16 | 3 | Пампа |
| kazakhstan | Aqtöbe | 304516.3 | 14 | 2 | Казахская степь |
| india | Madhya Pradesh | 308114.0 | 16 | 3 | Центральная Индия |
| india | Maharashtra | 310022.6 | 18 | 3 | Декан |
| ethiopia | Somali | 312653.9 | 12 | 2 | Африканский Рог |
| united_states_of_america | New Mexico | 316523.3 | 11 | 2 | Юго-Западные пустыни |
| brazil | Maranhão | 326209.9 | 16 | 3 | Северо-Восточная Бразилия |
| india | Rajasthan | 343369.1 | 14 | 2 | Раджастхан |
| pakistan | Baluchistan | 347741.0 | 12 | 2 | Белуджистан |
| brazil | Goiás | 348702.5 | 16 | 3 | Бразильское внутреннее плато |
| russia | Buryat | 348927.1 | 10 | 2 | Прибайкалье |
| ethiopia | Oromiya | 355240.3 | 14 | 2 | Эфиопское нагорье |
| brazil | Mato Grosso do Sul | 355813.8 | 12 | 2 | Пантанал |
| bolivia | Santa Cruz | 364362.4 | 12 | 2 | Пантанал |
| russia | Amur | 364789.8 | 14 | 2 | Амур и Приморье |
| sudan | Northern | 365032.8 | 14 | 2 | Суданская долина Нила |
| peru | Loreto | 375358.3 | 11 | 2 | Верхняя Амазонка |
| south_africa | Northern Cape | 377236.5 | 14 | 2 | Капская область |
| united_states_of_america | Montana | 383153.6 | 14 | 2 | Скалистые горы |
| china | Yunnan | 384879.1 | 16 | 3 | Юньнань и Гуйчжоу |
| greenland | Nationalparken | 392947.5 | 10 | 2 | Северная Норвегия |
| democratic_republic_of_the_congo | Équateur | 406713.5 | 12 | 2 | Бассейн Конго |
| united_states_of_america | California | 408629.9 | 14 | 2 | Калифорнийское побережье |
| russia | Chita | 408686.7 | 9 | 2 | Забайкалье |
| russia | Komi | 414962.1 | 12 | 2 | Русский Север |
| kazakhstan | Qaraghandy | 420777.6 | 14 | 2 | Казахская степь |
| china | Heilongjiang | 436745.4 | 14 | 2 | Амур и Приморье |
| china | Gansu | 457448.2 | 16 | 3 | Лёссовое плато |
| egypt | Al Wadi at Jadid | 473505.1 | 14 | 2 | Долина Нила |
| algeria | Adrar | 480861.5 | 12 | 2 | Атлас |
| democratic_republic_of_the_congo | Katanga | 487820.0 | 14 | 2 | Замбези |
| democratic_republic_of_the_congo | Orientale | 503278.7 | 16 | 3 | Великие озёра |
| mali | Timbuktu | 506391.5 | 16 | 3 | Средний Нигер |
| saudi_arabia | Ash Sharqiyah | 553178.5 | 12 | 2 | Персидский залив — побережье |
| china | Sichuan | 572096.7 | 16 | 3 | Сычуаньская котловина |
| brazil | Bahia | 579136.5 | 16 | 3 | Северо-Восточная Бразилия |
| canada | Alberta | 604342.8 | 14 | 2 | Британская Колумбия |
| canada | Manitoba | 655018.2 | 12 | 2 | Канадский щит |
| brazil | Minas Gerais | 678707.2 | 16 | 3 | Юго-Восточная Бразилия |
| united_states_of_america | Texas | 688911.0 | 16 | 3 | Техас и нижний Рио-Гранде |
| canada | Saskatchewan | 715163.9 | 14 | 2 | Канадские прерии |
| china | Qinghai | 719383.8 | 10 | 2 | Такла-Макан и Джунгария |
| russia | Irkutsk | 724365.0 | 14 | 2 | Прибайкалье |
| australia | New South Wales | 792810.6 | 16 | 3 | Юго-Восточная Австралия |
| russia | Khabarovsk | 798471.1 | 14 | 2 | Амур и Приморье |
| canada | British Columbia | 898694.4 | 14 | 2 | Британская Колумбия |
| brazil | Mato Grosso | 909939.6 | 12 | 2 | Пантанал |
| australia | South Australia | 939635.9 | 8 | 2 | Внутренняя Австралия |
| canada | Ontario | 1078098.7 | 16 | 3 | Район Великих озёр |
| china | Inner Mongol | 1080478.0 | 14 | 2 | Внутренняя Монголия |
| china | Xizang | 1125188.5 | 10 | 2 | Тибет |
| australia | Northern Territory | 1315050.1 | 12 | 2 | Северная Австралия |
| brazil | Pará | 1330609.1 | 14 | 2 | Амазонская сельва |
| canada | Québec | 1353072.9 | 10 | 2 | Лабрадор и север Квебека |
| united_states_of_america | Alaska | 1477952.7 | 12 | 2 | Аляска |
| china | Xinjiang | 1584306.0 | 14 | 2 | Синьцзянские оазисы |
| libya | Wadi al Hayaa | 1644331.3 | 12 | 2 | Киренаика |
| australia | Queensland | 1796225.0 | 16 | 3 | Восточное побережье Австралии |
| brazil | Amazonas | 1963278.6 | 14 | 2 | Амазонская сельва |
| russia | Krasnoyarsk | 2492942.9 | 12 | 2 | Центральная сибирская тайга |
| australia | Western Australia | 2578598.6 | 14 | 2 | Юго-Западная Австралия |
| russia | Sakha (Yakutia) | 3009476.2 | 12 | 2 | Якутия |

## Важное ограничение

Этот отчёт работает по текущим 4027 исходным записям. Перед фактической мировой генерацией необходимо отдельно объединить записи, которые являются геометрическими частями одной логической Admin-1 (например, островные/разорванные куски с одинаковым родителем), чтобы маленькие острова не становились самостоятельными игровыми провинциями по ошибке.
