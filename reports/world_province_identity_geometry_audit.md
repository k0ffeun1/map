# Аудит identity ↔ geometry для мировых Admin-1

> Диагностический этап. Исходная геометрия, цели клеток и границы не изменяются.

## Итог

- Target records: **4027**.
- Identity records: **4027**.
- Canonical Layer-8 geometries: **4027**.
- Numeric mirror geometries: **4027**.
- Жёстких integrity failures: **0**.
- Невалидных исходных Polygon до repair: **0**.
- Расхождений stored area ↔ текущий project area: **0**.
- Geodesic discrepancy >5%: **13**.
- Geodesic discrepancy >20%: **0**.
- Смена split-класса при WGS84 площади: **0**.
- Сильных внутристрановых area-outlier: **162**.
- Из текущих 366 split-кандидатов требуют проверки integrity/area/outlier: **127**.
- Безопасно автоматически делить текущие split-кандидаты: **НЕТ**.

## Как читать диагноз

- `stored_vs_project`: проверяет, воспроизводится ли площадь тем же алгоритмом, которым строились target counts.
- `project_vs_geodesic`: независимая проверка площади на эллипсоиде WGS84.
- `country_area_ratio_to_median`: статистический сигнал; сам по себе не доказывает ошибку, но хорошо ловит неправильную identity↔geometry пару.
- Никакие записи автоматически не исправляются этим аудитом.

## Именные диагностические случаи

| Province | ID | Country | Stored km² | Project km² | WGS84 km² | Δ WGS84 | x country median | Current class | WGS84 class | Valid |
|---|---|---|---:|---:|---:|---:|---:|---|---|---|
| Appenzell Innerrhoden | province:3369 | switzerland | 41239.7 | 41239.7 | 41370.9 | 0.32% | 1.00× | split | split | yes |
| Jekabpils | province:4009 | latvia | 64112.3 | 64112.3 | 64542.6 | 0.67% | 1.00× | split | split | yes |
| Northumberland | province:1762 | united_kingdom | 13.2 | 13.2 | 13.2 | 0.53% | 0.01× | untouched | untouched | yes |
| Northumberland | province:1763 | united_kingdom | 872.5 | 872.5 | 877.0 | 0.52% | 0.43× | untouched | untouched | yes |
| Northumberland | province:1764 | united_kingdom | 11.7 | 11.7 | 11.7 | 0.50% | 0.01× | untouched | untouched | yes |
| Northumberland | province:1765 | united_kingdom | 1603.5 | 1603.5 | 1611.8 | 0.52% | 0.79× | untouched | untouched | yes |
| Northumberland | province:1766 | united_kingdom | 60.6 | 60.6 | 60.9 | 0.50% | 0.03× | untouched | untouched | yes |
| Northumberland | province:1767 | united_kingdom | 6.4 | 6.4 | 6.4 | 0.50% | 0.00× | untouched | untouched | yes |
| Northumberland | province:1768 | united_kingdom | 73138.6 | 73138.6 | 73897.9 | 1.03% | 36.42× | split | split | yes |
| Northumberland | province:1769 | united_kingdom | 105.4 | 105.4 | 105.9 | 0.43% | 0.05× | untouched | untouched | yes |
| Northumberland | province:1770 | united_kingdom | 10.1 | 10.1 | 10.1 | 0.50% | 0.00× | untouched | untouched | yes |
| Northumberland | province:1771 | united_kingdom | 8.7 | 8.7 | 8.7 | 0.48% | 0.00× | untouched | untouched | yes |

## Split-кандидаты, требующие проверки

| Province | Country | Cells | Stored km² | WGS84 km² | Δ | x median | Reasons |
|---|---|---:|---:|---:|---:|---:|---|
| Québec | canada | 10 | 1353072.9 | 1411133.1 | 4.11% | 6101.43× | country_area_outlier_ge8x |
| Western Australia | australia | 14 | 2578598.6 | 2526489.0 | 2.06% | 5426.20× | country_area_outlier_ge8x |
| Alaska | united_states_of_america | 12 | 1477952.7 | 1427678.7 | 3.52% | 5426.18× | country_area_outlier_ge8x |
| Ontario | canada | 16 | 1078098.7 | 1077150.9 | 0.09% | 4657.37× | country_area_outlier_ge8x |
| British Columbia | canada | 14 | 898694.4 | 912270.6 | 1.49% | 3944.46× | country_area_outlier_ge8x |
| Nationalparken | greenland | 10 | 392947.5 | 390611.4 | 0.60% | 3926.50× | country_area_outlier_ge8x |
| Queensland | australia | 16 | 1796225.0 | 1728148.8 | 3.94% | 3711.58× | country_area_outlier_ge8x |
| Amazonas | brazil | 14 | 1963278.6 | 1944326.6 | 0.97% | 3536.65× | country_area_outlier_ge8x |
| Alberta | canada | 14 | 604342.8 | 667295.5 | 9.43% | 2885.24× | country_area_outlier_ge8x |
| Northern Territory | australia | 12 | 1315050.1 | 1341141.4 | 1.95% | 2880.40× | country_area_outlier_ge8x |
| Manitoba | canada | 12 | 655018.2 | 651408.8 | 0.55% | 2816.55× | country_area_outlier_ge8x |
| Saskatchewan | canada | 14 | 715163.9 | 649927.8 | 10.04% | 2810.15× | country_area_outlier_ge8x |
| Texas | united_states_of_america | 16 | 688911.0 | 684826.2 | 0.60% | 2602.82× | country_area_outlier_ge8x |
| Pará | brazil | 14 | 1330609.1 | 1318586.4 | 0.91% | 2398.46× | country_area_outlier_ge8x |
| South Australia | australia | 8 | 939635.9 | 968323.1 | 2.96% | 2079.69× | country_area_outlier_ge8x |
| New South Wales | australia | 16 | 792810.6 | 801087.4 | 1.03% | 1720.51× | country_area_outlier_ge8x |
| Mato Grosso | brazil | 12 | 909939.6 | 902665.0 | 0.81% | 1641.91× | country_area_outlier_ge8x |
| California | united_states_of_america | 14 | 408629.9 | 409746.6 | 0.27% | 1557.32× | country_area_outlier_ge8x |
| Montana | united_states_of_america | 14 | 383153.6 | 387567.1 | 1.14% | 1473.03× | country_area_outlier_ge8x |
| Minas Gerais | brazil | 16 | 678707.2 | 675822.7 | 0.43% | 1229.29× | country_area_outlier_ge8x |
| New Mexico | united_states_of_america | 11 | 316523.3 | 316255.5 | 0.08% | 1201.99× | country_area_outlier_ge8x |
| Arizona | united_states_of_america | 10 | 295754.5 | 295440.4 | 0.11% | 1122.88× | country_area_outlier_ge8x |
| Nevada | united_states_of_america | 10 | 295233.0 | 286968.3 | 2.88% | 1090.68× | country_area_outlier_ge8x |
| Bahia | brazil | 16 | 579136.5 | 581159.1 | 0.35% | 1057.11× | country_area_outlier_ge8x |
| Colorado | united_states_of_america | 16 | 268982.0 | 269169.6 | 0.07% | 1023.03× | country_area_outlier_ge8x |
| Wyoming | united_states_of_america | 11 | 252895.5 | 253290.6 | 0.16% | 962.68× | country_area_outlier_ge8x |
| Michigan | united_states_of_america | 16 | 247820.3 | 249845.3 | 0.81% | 949.59× | country_area_outlier_ge8x |
| Oregon | united_states_of_america | 14 | 249877.3 | 249487.2 | 0.16% | 948.23× | country_area_outlier_ge8x |
| Minnesota | united_states_of_america | 16 | 222856.3 | 223869.6 | 0.45% | 850.86× | country_area_outlier_ge8x |
| Utah | united_states_of_america | 10 | 221625.3 | 219119.0 | 1.14% | 832.81× | country_area_outlier_ge8x |
| Idaho | united_states_of_america | 9 | 207245.1 | 214834.7 | 3.53% | 816.52× | country_area_outlier_ge8x |
| Kansas | united_states_of_america | 16 | 215066.2 | 211964.1 | 1.46% | 805.61× | country_area_outlier_ge8x |
| South Dakota | united_states_of_america | 15 | 200214.3 | 200781.7 | 0.28% | 763.11× | country_area_outlier_ge8x |
| Nebraska | united_states_of_america | 15 | 200884.6 | 199959.9 | 0.46% | 759.99× | country_area_outlier_ge8x |
| Oklahoma | united_states_of_america | 16 | 183390.8 | 184521.9 | 0.61% | 701.31× | country_area_outlier_ge8x |
| North Dakota | united_states_of_america | 14 | 181581.9 | 181929.6 | 0.19% | 691.46× | country_area_outlier_ge8x |
| Missouri | united_states_of_america | 16 | 180077.8 | 180094.3 | 0.01% | 684.48× | country_area_outlier_ge8x |
| Washington | united_states_of_america | 14 | 172968.3 | 173962.0 | 0.57% | 661.18× | country_area_outlier_ge8x |
| Mato Grosso do Sul | brazil | 12 | 355813.8 | 356031.0 | 0.06% | 647.61× | country_area_outlier_ge8x |
| Wisconsin | united_states_of_america | 16 | 167234.1 | 168985.9 | 1.04% | 642.26× | country_area_outlier_ge8x |
| Goiás | brazil | 16 | 348702.5 | 346982.5 | 0.50% | 631.15× | country_area_outlier_ge8x |
| Maranhão | brazil | 16 | 326209.9 | 325034.2 | 0.36% | 591.22× | country_area_outlier_ge8x |
| Georgia | united_states_of_america | 16 | 152015.0 | 152010.8 | 0.00% | 577.75× | country_area_outlier_ge8x |
| Illinois | united_states_of_america | 16 | 151864.4 | 150602.0 | 0.84% | 572.39× | country_area_outlier_ge8x |
| Iowa | united_states_of_america | 11 | 145714.7 | 146250.0 | 0.37% | 555.85× | country_area_outlier_ge8x |
| Florida | united_states_of_america | 14 | 147531.2 | 145860.4 | 1.15% | 554.37× | country_area_outlier_ge8x |
| Arkansas | united_states_of_america | 16 | 137955.3 | 137946.0 | 0.01% | 524.29× | country_area_outlier_ge8x |
| Alabama | united_states_of_america | 16 | 134548.3 | 133834.8 | 0.53% | 508.67× | country_area_outlier_ge8x |
| Tocantins | brazil | 16 | 281890.6 | 278933.0 | 1.06% | 507.37× | country_area_outlier_ge8x |
| New York | united_states_of_america | 14 | 133348.6 | 132517.6 | 0.63% | 503.66× | country_area_outlier_ge8x |
| Rio Grande do Sul | brazil | 16 | 268899.7 | 272400.2 | 1.29% | 495.49× | country_area_outlier_ge8x |
| Victoria | australia | 16 | 229220.3 | 227624.8 | 0.70% | 488.87× | country_area_outlier_ge8x |
| North Carolina | united_states_of_america | 14 | 127908.1 | 127360.4 | 0.43% | 484.06× | country_area_outlier_ge8x |
| Mississippi | united_states_of_america | 16 | 124222.1 | 123640.6 | 0.47% | 469.92× | country_area_outlier_ge8x |
| Piauí | brazil | 16 | 253962.5 | 251992.5 | 0.78% | 458.36× | country_area_outlier_ge8x |
| Louisiana | united_states_of_america | 16 | 119463.8 | 119233.1 | 0.19% | 453.17× | country_area_outlier_ge8x |
| Pennsylvania | united_states_of_america | 14 | 118442.5 | 119192.1 | 0.63% | 453.01× | country_area_outlier_ge8x |
| São Paulo | brazil | 16 | 247738.1 | 248075.4 | 0.14% | 451.24× | country_area_outlier_ge8x |
| Ohio | united_states_of_america | 14 | 116028.9 | 116217.9 | 0.16% | 441.71× | country_area_outlier_ge8x |
| Rondônia | brazil | 14 | 239103.1 | 237863.9 | 0.52% | 432.67× | country_area_outlier_ge8x |
| Tennessee | united_states_of_america | 16 | 109255.3 | 109226.3 | 0.03% | 415.14× | country_area_outlier_ge8x |
| Kentucky | united_states_of_america | 14 | 103561.4 | 104385.7 | 0.79% | 396.74× | country_area_outlier_ge8x |
| Virginia | united_states_of_america | 14 | 101980.0 | 101877.4 | 0.10% | 387.21× | country_area_outlier_ge8x |
| Québec | canada | 14 | 86305.4 | 86327.8 | 0.03% | 373.26× | country_area_outlier_ge8x |
| Paraná | brazil | 16 | 199087.5 | 198583.3 | 0.25% | 361.22× | country_area_outlier_ge8x |
| Indiana | united_states_of_america | 16 | 92369.7 | 94303.4 | 2.05% | 358.42× | country_area_outlier_ge8x |
| Maine | united_states_of_america | 14 | 83652.7 | 83569.3 | 0.10% | 317.62× | country_area_outlier_ge8x |
| New Brunswick | canada | 14 | 72249.4 | 72372.0 | 0.17% | 312.92× | country_area_outlier_ge8x |
| South Carolina | united_states_of_america | 15 | 80676.2 | 80137.4 | 0.67% | 304.58× | country_area_outlier_ge8x |
| Ceará | brazil | 16 | 150900.9 | 150289.1 | 0.41% | 273.37× | country_area_outlier_ge8x |
| Antofagasta | chile | 8 | 123222.9 | 122913.7 | 0.25% | 259.50× | country_area_outlier_ge8x |
| Papua | indonesia | 12 | 295663.6 | 294761.6 | 0.31% | 238.42× | country_area_outlier_ge8x |
| West Virginia | united_states_of_america | 9 | 62118.1 | 62680.6 | 0.90% | 238.23× | country_area_outlier_ge8x |
| Pernambuco | brazil | 16 | 125430.3 | 125089.0 | 0.27% | 227.53× | country_area_outlier_ge8x |
| Nova Scotia | canada | 14 | 44378.7 | 44220.1 | 0.36% | 191.20× | country_area_outlier_ge8x |
| Santa Catarina | brazil | 13 | 93859.6 | 94409.9 | 0.58% | 171.73× | country_area_outlier_ge8x |
| Atacama | chile | 14 | 79239.1 | 79270.2 | 0.04% | 167.36× | country_area_outlier_ge8x |
| Kalimantan Timur | indonesia | 14 | 195601.2 | 194545.1 | 0.54% | 157.36× | country_area_outlier_ge8x |
| Tasmania | australia | 9 | 63995.8 | 64372.6 | 0.59% | 138.25× | country_area_outlier_ge8x |
| Kalimantan Tengah | indonesia | 14 | 152766.4 | 152013.3 | 0.50% | 122.95× | country_area_outlier_ge8x |
| Kalimantan Barat | indonesia | 14 | 147558.1 | 146861.3 | 0.47% | 118.79× | country_area_outlier_ge8x |
| Sakha (Yakutia) | russia | 12 | 3009476.2 | 3032557.4 | 0.76% | 101.83× | country_area_outlier_ge8x |
| Krasnoyarsk | russia | 12 | 2492942.9 | 2403514.4 | 3.72% | 80.71× | country_area_outlier_ge8x |
| Adrar | algeria | 12 | 480861.5 | 473393.1 | 1.58% | 75.18× | country_area_outlier_ge8x |
| Papua Barat | indonesia | 12 | 87466.3 | 87071.5 | 0.45% | 70.43× | country_area_outlier_ge8x |
| Sumatera Selatan | indonesia | 14 | 85092.8 | 84716.5 | 0.44% | 68.52× | country_area_outlier_ge8x |
| Riau | indonesia | 14 | 82041.5 | 81667.5 | 0.46% | 66.06× | country_area_outlier_ge8x |
| Sumatera Utara | indonesia | 14 | 68050.7 | 67725.7 | 0.48% | 54.78× | country_area_outlier_ge8x |
| Al Wadi at Jadid | egypt | 14 | 473505.1 | 474813.2 | 0.28% | 52.43× | country_area_outlier_ge8x |
| Sulawesi Tengah | indonesia | 14 | 57419.0 | 57141.9 | 0.49% | 46.22× | country_area_outlier_ge8x |
| Aceh | indonesia | 14 | 54047.6 | 53751.6 | 0.55% | 43.48× | country_area_outlier_ge8x |
| Jambi | indonesia | 14 | 51124.5 | 50896.8 | 0.45% | 41.17× | country_area_outlier_ge8x |
| Sulawesi Selatan | indonesia | 14 | 45933.5 | 45736.3 | 0.43% | 36.99× | country_area_outlier_ge8x |
| Northumberland | united_kingdom | 10 | 73138.6 | 73897.9 | 1.03% | 36.42× | country_area_outlier_ge8x |
| Jawa Timur | indonesia | 14 | 42142.6 | 41949.2 | 0.46% | 33.93× | country_area_outlier_ge8x |
| Ouargla | algeria | 14 | 210516.4 | 211160.4 | 0.30% | 33.54× | country_area_outlier_ge8x |
| Bolívar | venezuela | 14 | 252646.3 | 251269.5 | 0.55% | 31.52× | country_area_outlier_ge8x |
| Khabarovsk | russia | 14 | 798471.1 | 820531.8 | 2.69% | 27.55× | country_area_outlier_ge8x |
| Béchar | algeria | 12 | 164743.4 | 165084.8 | 0.21% | 26.22× | country_area_outlier_ge8x |
| Irkutsk | russia | 14 | 724365.0 | 773401.2 | 6.34% | 25.97× | country_area_outlier_ge8x |
| Tindouf | algeria | 12 | 153109.4 | 152017.3 | 0.72% | 24.14× | country_area_outlier_ge8x |
| Al Bahr al Ahmar | egypt | 14 | 210848.8 | 211131.5 | 0.13% | 23.31× | country_area_outlier_ge8x |
| Amazonas | venezuela | 12 | 180628.8 | 179753.5 | 0.49% | 22.55× | country_area_outlier_ge8x |
| Hokkaidō | japan | 12 | 78061.3 | 78401.3 | 0.43% | 19.65× | country_area_outlier_ge8x |
| Matruh | egypt | 12 | 159348.4 | 158981.8 | 0.23% | 17.55× | country_area_outlier_ge8x |
| Shan | myanmar | 16 | 166942.2 | 165933.0 | 0.61% | 17.13× | country_area_outlier_ge8x |
| Western | papua_new_guinea | 11 | 99353.1 | 98912.1 | 0.45% | 15.80× | country_area_outlier_ge8x |
| Sarawak | malaysia | 14 | 122781.0 | 122267.2 | 0.42% | 15.30× | country_area_outlier_ge8x |
| Chita | russia | 9 | 408686.7 | 432385.8 | 5.48% | 14.52× | country_area_outlier_ge8x |
| Komi | russia | 12 | 414962.1 | 418015.0 | 0.73% | 14.04× | country_area_outlier_ge8x |
| Hadramawt | yemen | 14 | 164894.3 | 164124.6 | 0.47% | 13.67× | country_area_outlier_ge8x |
| Xinjiang | china | 14 | 1584306.0 | 1630013.1 | 2.80% | 13.60× | country_area_outlier_ge8x |
| Amur | russia | 14 | 364789.8 | 360835.3 | 1.10% | 12.12× | country_area_outlier_ge8x |
| Ghardaïa | algeria | 14 | 75504.6 | 75464.7 | 0.05% | 11.99× | country_area_outlier_ge8x |
| Buryat | russia | 10 | 348927.1 | 352987.7 | 1.15% | 11.85× | country_area_outlier_ge8x |
| El Bayadh | algeria | 14 | 68325.9 | 68290.2 | 0.05% | 10.85× | country_area_outlier_ge8x |
| Dhofar | oman | 12 | 128249.0 | 128519.7 | 0.21% | 10.79× | country_area_outlier_ge8x |
| Karakalpakstan | uzbekistan | 12 | 173897.0 | 172474.8 | 0.82% | 10.45× | country_area_outlier_ge8x |
| Arkhangel'sk | russia | 9 | 299623.3 | 307097.0 | 2.43% | 10.31× | country_area_outlier_ge8x |
| Loreto | peru | 11 | 375358.3 | 373636.5 | 0.46% | 10.25× | country_area_outlier_ge8x |
| Sagaing | myanmar | 14 | 96399.2 | 96679.1 | 0.29% | 9.98× | country_area_outlier_ge8x |
| Inner Mongol | china | 14 | 1080478.0 | 1144565.6 | 5.60% | 9.55× | country_area_outlier_ge8x |
| Xizang | china | 10 | 1125188.5 | 1129808.2 | 0.41% | 9.43× | country_area_outlier_ge8x |
| Sabah | malaysia | 8 | 72979.0 | 72716.1 | 0.36% | 9.10× | country_area_outlier_ge8x |
| Kachin | myanmar | 14 | 88082.0 | 87925.3 | 0.18% | 9.08× | country_area_outlier_ge8x |
| Al-Anbar | iraq | 14 | 143471.8 | 143155.6 | 0.22% | 8.35× | country_area_outlier_ge8x |
| Chihuahua | mexico | 14 | 248620.9 | 247839.2 | 0.32% | 8.15× | country_area_outlier_ge8x |

## Hard integrity failures

- Нет.
