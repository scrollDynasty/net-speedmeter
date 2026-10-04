# net-speedmeter

[![CI](https://github.com/scrollDynasty/net-speedmeter/actions/workflows/ci.yml/badge.svg)](https://github.com/scrollDynasty/net-speedmeter/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)
![mypy](https://img.shields.io/badge/mypy-strict-informational)
![License](https://img.shields.io/badge/license-MIT-green)

CLI-замерятель скорости интернета. Скрипт скачивает тяжёлый файл (по умолчанию картинку) **10 раз подряд**
и для каждого запроса ждёт полный ответ. Потом печатает:

- **среднее время запроса**;
- **объём скачанных данных**;
- **скорость** в **Mbit/s** и **MB/s**.

> **Тестовое задание:** «Написать скрипт-замерятель скорости интернета со своего компьютера. Он должен принимать адрес,
> куда стучаться (какая-нибудь тяжелая картинка), запускать последовательно 10 запросов к этому адресу, дожидаться
> ответа, вычислять среднее время запроса, объем скачанных данных и печатать в консоли скорость мб/с.»

---

## Быстрый старт

Нужен Python **3.11+**. Удобнее всего запускать через [uv](https://docs.astral.sh/uv/getting-started/installation/):

```bash
git clone https://github.com/scrollDynasty/net-speedmeter.git
cd net-speedmeter
uv run net-speedmeter                       # 10 запросов к картинке по умолчанию (14.7 MB, Wikimedia Commons)
uv run net-speedmeter "https://nbg1-speed.hetzner.com/100MB.bin"
```

<details>
<summary>Без uv — обычный pip + venv</summary>

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install .
net-speedmeter "https://speed.cloudflare.com/__down?bytes=50000000"
# или: python -m net_speedmeter <URL>
```
</details>

<details>
<summary>Docker</summary>

```bash
docker build -t net-speedmeter .
docker run --rm net-speedmeter "https://speed.cloudflare.com/__down?bytes=50000000"
```
</details>

## Пример вывода

Реальный прогон с домашнего канала:

```text
$ uv run net-speedmeter
net-speedmeter 0.1.0
URL:      https://upload.wikimedia.org/wikipedia/commons/3/3f/Fronalpstock_big.jpg
Requests: 10 sequential GET, keep-alive

[ 1/10] 200   14.68 MB    8.186 s  TTFB 380.9 ms     14.35 Mbit/s     1.79 MB/s
[ 2/10] 200   14.68 MB    4.951 s  TTFB 106.6 ms     23.72 Mbit/s     2.97 MB/s
[ 3/10] 200   14.68 MB    3.401 s  TTFB 108.6 ms     34.53 Mbit/s     4.32 MB/s
[ 4/10] 200   14.68 MB    3.668 s  TTFB 121.3 ms     32.02 Mbit/s     4.00 MB/s
[ 5/10] 200   14.68 MB    3.410 s  TTFB 109.4 ms     34.44 Mbit/s     4.31 MB/s
[ 6/10] 200   14.68 MB    4.141 s  TTFB 112.0 ms     28.36 Mbit/s     3.54 MB/s
[ 7/10] 200   14.68 MB    4.098 s  TTFB 106.2 ms     28.66 Mbit/s     3.58 MB/s
[ 8/10] 200   14.68 MB    4.643 s  TTFB 104.1 ms     25.29 Mbit/s     3.16 MB/s
[ 9/10] 200   14.68 MB    4.322 s  TTFB 110.0 ms     27.17 Mbit/s     3.40 MB/s
[10/10] 200   14.68 MB    4.985 s  TTFB 105.1 ms     23.56 Mbit/s     2.94 MB/s

Summary
Requests          10/10 succeeded
Downloaded        146.79 MB (146,794,740 bytes)
Avg request time  4.580 s
Spread            min 3.401 s, median 4.232 s, max 8.186 s, stdev 1.390 s
Avg TTFB          136.4 ms
Speed             25.64 Mbit/s = 3.20 MB/s  (total bytes / total time)
Body transfer     26.43 Mbit/s = 3.30 MB/s  (excluding TTFB)
Per-request       median 27.76 / p90 34.45 / min 14.35 / max 34.53 Mbit/s
```

У первого запроса TTFB больше: в него входит установка соединения (DNS, TCP, TLS), а скорость ниже из-за TCP slow start.
Дальше соединение переиспользуется (keep-alive).

В интерактивном терминале во время загрузки ещё показывается прогресс-бар.

## Параметры

| Параметр | По умолчанию | Описание |
|---|---|---|
| `URL` | картинка 14.7 MB с Wikimedia Commons | Что скачивать. Только `http`/`https`. |
| `-n, --count` | `10` | Сколько последовательных запросов сделать (1–1000). |
| `--timeout` | `30` | Таймаут в секундах на каждую сетевую операцию: подключение и каждое чтение. Медленная, но идущая загрузка не обрывается. |
| `--keepalive / --no-keepalive` | `--keepalive` | Переиспользовать одно соединение или открывать новое на каждый запрос. Второе — «холодный» замер, включает DNS, TCP и TLS. |
| `--chunk-size` | `262144` | Размер буфера чтения в байтах. |
| `--json` | — | Машиночитаемый вывод для скриптов и мониторинга. |
| `--version` | — | Версия. |

```bash
uv run net-speedmeter "https://speed.cloudflare.com/__down?bytes=50000000" -n 5 --no-keepalive
uv run net-speedmeter --json | jq '.summary.speed_mbit_s'
```

**Коды выхода:**

| Код | Когда |
|---|---|
| `0` | Все запросы успешны. |
| `1` | Часть запросов упала. Статистика посчитана по успешным. |
| `2` | Все запросы упали или передан неверный аргумент. |
| `3` | Сломано окружение, например неверный `HTTPS_PROXY` или отсутствующий CA-bundle. Ошибка пишется в stderr. |
| `130` | Прервано через Ctrl+C. Сводка печатается по уже завершённым запросам. |

## Методика: что и как считается

В ТЗ написано «мб/с», а это неоднозначно: мегабиты или мегабайты? Поэтому скрипт печатает **обе** величины.
Префиксы десятичные (SI), как у провайдеров и speedtest-сервисов:
1 Mbit/s = 10⁶ бит/с, 1 MB/s = 10⁶ байт/с, 1 MB/s = 8 Mbit/s.

| Метрика | Формула |
|---|---|
| Время запроса | от отправки запроса до получения последнего байта тела |
| TTFB | от отправки запроса до получения заголовков ответа |
| Объём | сумма байтов, реально полученных из сети успешными запросами |
| **Speed** (главная цифра) | `Σ байтов / Σ времени запросов` |
| Body transfer | `Σ байтов / Σ (время запроса − TTFB)` — чистая передача тела |
| Per-request | медиана, p90, min и max скоростей отдельных запросов (p90 считает и Cloudflare Speed Test) |

Ключевые решения и почему они такие:

1. **Скорость = суммарные байты / суммарное время**, а не среднее арифметическое скоростей отдельных запросов.
   Простое среднее завышает результат. Пример: 10 MB за 1 с и 10 MB за 9 с — это 20 MB за 10 с, то есть 2 MB/s.
   Среднее скоростей дало бы ~5.6 MB/s. Заодно это то же самое, что «средний объём запроса / среднее время запроса».
2. **Считаются байты из сети, а не после распаковки.**
   - Объём берётся из `httpx.Response.num_bytes_downloaded`, тело читается через `iter_raw()`.
   - Клиент шлёт `Accept-Encoding: identity`, чтобы сервер не сжимал ответ.
   - Если сервер всё равно пришлёт gzip, считается сжатый размер: именно столько прошло по каналу.
3. **Тело не держится в памяти.** Оно читается потоково, чанками по 256 KiB, и сразу выбрасывается,
   поэтому файлы на 100 MB и 1 GB не съедают RAM.
4. **Время берётся из `time.perf_counter()`.** Эти часы монотонные и высокого разрешения. `time.time()` не подходит:
   системные часы могут прыгнуть, например при синхронизации NTP.
5. **Проверяется целостность ответа.**
   - Если `Content-Length` не совпал с фактическим объёмом или сервер оборвал соединение, запрос считается неуспешным.
   - Ответы не-2xx тоже считаются неуспешными.
   - Неуспешные запросы не портят статистику, но видны в выводе и влияют на код выхода.
6. **Промежуточные кэши не подсовывают старый ответ.** Клиент шлёт `Cache-Control: no-cache`: это просит
   промежуточные кэши (например, корпоративный прокси) перепроверить ответ, а не отдавать сохранённую копию.
   Случайный query-параметр (cache-busting) не добавляется сознательно: тогда CDN Wikimedia ходил бы
   за каждым запросом на origin, а это нагрузка на чужую инфраструктуру и замер не того, что нужно.
7. **Скрипт честно представляется.** User-Agent имеет вид `net-speedmeter/<ver> (+repo-url) httpx/<ver>`.
   Этого требует [политика Wikimedia](https://foundation.wikimedia.org/wiki/Policy:User-Agent_policy):
   запросы без UA или с дефолтным `python-httpx` получают 403.
8. **Запросы идут строго последовательно** через один `httpx.Client`. Редиректы проходятся,
   и их время входит во время запроса.

### Какой URL брать

| URL | Размер | Комментарий |
|---|---|---|
| `https://upload.wikimedia.org/wikipedia/commons/3/3f/Fronalpstock_big.jpg` | 14.7 MB | По умолчанию — «тяжёлая картинка» из ТЗ. Отдаётся с CDN Wikimedia. |
| `https://speed.cloudflare.com/__down?bytes=50000000` | любой, < 100 MB | Endpoint Cloudflare Speed Test, ближайший PoP. При `bytes` ≥ 10⁸ отвечает 403. |
| `https://nbg1-speed.hetzner.com/100MB.bin` | 100 MB | Также есть `fsn1-`, `hel1-`, `ash-`, `hil-`, `sin-` и файлы `1GB.bin` / `10GB.bin`. |

Чем больше файл, тем меньше на результат влияют задержка (RTT) и TCP slow start.
Для каналов от 100 Mbit/s лучше брать файлы от 25–100 MB.

### Ограничения

- Замер идёт **в один поток** (одно TCP-соединение), и это сознательный выбор по ТЗ.
  Ookla Speedtest открывает несколько параллельных соединений и отбрасывает «медленные» сэмплы,
  поэтому на быстрых каналах его цифры будут выше. M-Lab NDT7, как и этот скрипт, меряет одним потоком.
- Измеряется скорость **до конкретного сервера**, а не «скорость интернета вообще».
  На результат влияют маршрут, загрузка CDN и сам сервер.
- Только HTTP/1.1 и только download.

## Структура проекта

```
src/net_speedmeter/
├── measure.py   # HTTP-слой: клиент, один замер, генератор серии замеров
├── stats.py     # чистые функции агрегации (mean/median/p90/stdev, throughput)
├── models.py    # frozen dataclasses: RequestResult, Distribution, Summary
├── units.py     # Mbit/s, MB/s, форматирование байтов и длительностей
└── cli.py       # Typer + Rich: аргументы, прогресс, вывод, JSON, коды выхода
tests/
├── conftest.py          # реальный локальный HTTP/1.1-сервер с keep-alive
├── test_measure.py      # httpx.MockTransport + детерминированные часы
├── test_stats.py        # агрегаты, в т.ч. «взвешенное vs наивное среднее»
├── test_units.py
├── test_integration.py  # реальные сокеты: переиспользование соединений, обрывы, ConnectError
└── test_cli.py          # CliRunner: вывод, --json, коды выхода, Ctrl+C
```

Слои не зависят от CLI. `iter_benchmark()` — генератор, поэтому CLI показывает результаты по мере готовности
и при Ctrl+C сохраняет уже полученные. Тот же код без изменений можно вызвать из Celery-таски или Django management command.

## Разработка

```bash
uv sync                              # окружение + dev-зависимости из uv.lock
uv run pytest --cov                  # 58 тестов, coverage ~97%
uv run ruff check . && uv run ruff format --check .
uv run mypy                          # strict
```

CI (GitHub Actions) прогоняет на каждый push и PR:

- ruff и mypy;
- тесты на матрице Ubuntu / Windows / macOS × Python 3.11 / 3.12 / 3.13;
- сборку и smoke-тест Docker-образа.

**Стек:**

- **httpx** — потоковое чтение, счётчик байтов из сети, тонкие таймауты;
- **Typer** и **Rich** — CLI;
- **uv** — зависимости и lock-файл;
- **pytest**, **ruff**, **mypy --strict**.

## Почему без Django / Celery

Задача — консольная утилита на один запуск. Веб-фреймворк, брокер очередей и БД здесь ничего не дают,
только добавляют зависимостей и точек отказа. Поэтому измерительное ядро сделано отдельной библиотекой без привязки к CLI.

Если понадобится регулярно мониторить скорость отдачи, например лендингов или креативов с разных гео, ядро встраивается так:

- Celery beat по расписанию запускает `iter_benchmark()`;
- `Summary` сохраняется в PostgreSQL;
- Django admin или дашборд показывает деградации.

CLI-слой для этого переписывать не придётся.

## Как использовался AI

Решение сделано в AI-assisted режиме (Claude Code). Методику я сначала проверил по первоисточникам:

- исходники httpx — где именно считается `num_bytes_downloaded`;
- описание методик Cloudflare Speed Test и M-Lab NDT7;
- политика User-Agent у Wikimedia;
- живые ответы тестовых endpoint-ов.

Затем писал код через TDD: сначала тесты, потом реализация. Проверки после этого:

- `ruff` и `mypy --strict`;
- реальные прогоны на Wikimedia, Cloudflare и Hetzner;
- запуск в Docker.

## Лицензия

MIT
