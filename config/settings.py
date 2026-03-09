# =============================================================================
# settings.py — пользовательские настройки url-parser
# Редактируй этот файл для изменения поведения пайплайна.
# =============================================================================

# ── База данных ───────────────────────────────────────────────────────────────
DB_PATH = "urls.db"

# ── Step 1 — импорт ───────────────────────────────────────────────────────────
DEFAULT_INPUT_FILE = "raw_links.txt"

# ── Step 2 — парсинг заголовков ───────────────────────────────────────────────
REQUEST_TIMEOUT = (5, 10)   # (connect, read) в секундах
DELAY_MIN       = 2.0       # минимальная пауза между запросами (сек)
DELAY_MAX       = 3.0       # максимальная пауза (сек)
MAX_RETRIES     = 0         # кол-во повторных попыток на URL (0 = без повторов)
RETRY_BACKOFF   = 0         # множитель backoff: 2^1=2s, 2^2=4s, 2^3=8s

USER_AGENTS = [
    # Chrome 133 / Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    # Chrome 133 / macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    # Firefox 135 / Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) Gecko/20100101 Firefox/135.0",
    # Edge 133 / Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 Edg/133.0.0.0",
    # Safari 17 / macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.6 Safari/605.1.15",
]

BASE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

# ── Step 3 — классификация (Ollama) ──────────────────────────────────────────
OLLAMA_HOST            = "http://localhost:11434"
OLLAMA_REQUEST_TIMEOUT = 120.0  # сек; батч из 20 URL может занять до ~120с

# После скольких подряд ошибок соединения прерывать обработку
MAX_CONSECUTIVE_CONN_ERRORS = 3

# Максимум токенов в ответе (защита от бесконечной генерации)
NUM_PREDICT_SINGLE  = 80   # на один URL
NUM_PREDICT_PER_URL = 30   # на каждый URL в батче (10 URL → 300 токенов)

# Температура генерации (0.0 = детерминированный вывод, рекомендуется для классификации)
OLLAMA_TEMPERATURE  = 0.0

# ── Валидация тегов ───────────────────────────────────────────────────────────
# Тег не будет сохранён в справочник если нарушает любое из правил ниже.
TAG_MAX_LEN      = 40
TAG_MAX_WORDS    = 4
BAD_TAG_PREFIXES = ("url:", "http", "title:", "category:", "the web", "the page", "i'm sorry")
BAD_TAG_WORDS    = ("web page", "web site", "sorry")

# ── Compare — отображение таблицы ────────────────────────────────────────────
COMPARE_MAX_TITLE_LEN = 45
COMPARE_MAX_TAG_LEN   = 32

# ── Dry-run лог ───────────────────────────────────────────────────────────────
DRY_RUN_LOG = "benchmark/dryrun_log.csv"
