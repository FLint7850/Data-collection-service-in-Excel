"""Feed downloading, parsing and export helpers."""



from parser_app.runtime import *  # noqa: F401,F403



def create_export_file(rows: List[Dict[str, str]], project: Optional[Dict[str, object]] = None) -> Path:
    if project:
        filename = project_csv_filename(project)
    else:
        filename = f"export_{datetime.now().strftime('%d-%m-%Y_%H-%M-%S')}.csv"
    path = EXPORT_DIR / filename

    with path.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.writer(csv_file, delimiter=";")
        writer.writerow(["URL товара", "_MODEL_", "_PRICE_"])
        for row in rows:
            writer.writerow([output_text(row.get("url", "")), output_text(row.get("model", "")), output_text(row.get("price", ""))])

    return path

class CollectOnlyCrawler(ProductSiteCrawler):
    def __init__(self, *args, progress_callback=None, **kwargs):
        kwargs.setdefault("allow_empty_price", True)
        super().__init__(*args, **kwargs)
        self.progress_callback = progress_callback

    def update_state(self, **kwargs: object) -> None:
        if self.progress_callback:
            self.progress_callback(kwargs)

    def log(self, message: str, level: str = "info") -> None:
        if self.progress_callback:
            self.progress_callback(
                {
                    "log_message": message,
                    "log_level": level,
                }
            )

    def finish_with_excel(self, partial: bool = False) -> None:
        with self.data_lock:
            self.excel_finalized = True

def text_by_selector(soup: BeautifulSoup, selector: str) -> str:
    if not selector:
        return ""
    try:
        return first_by_selector(soup, selector)
    except Exception:
        return ""

def image_by_selector(soup: BeautifulSoup, selector: str, base_url: str) -> str:
    if not selector:
        return ""
    try:
        node = soup.select_one(selector)
    except Exception:
        return ""
    if not node:
        return ""
    if node.name == "img":
        value = node.get("src") or node.get("data-src") or node.get("data-original") or ""
    else:
        image = node.select_one("img")
        value = image.get("src") or image.get("data-src") or image.get("data-original") if image else ""
    return normalize_url(value, base_url) or "" if value else ""

def extract_photo_url(soup: BeautifulSoup, base_url: str, selector: str = "") -> str:
    selected = image_by_selector(soup, selector, base_url)
    if selected:
        return selected
    meta = soup.select_one("meta[property='og:image'], meta[name='twitter:image'], link[itemprop='image']")
    if meta:
        value = meta.get("content") or meta.get("href") or ""
        normalized = normalize_url(value, base_url)
        if normalized:
            return normalized
    for image in soup.select("img[src], img[data-src], img[data-original]"):
        value = image.get("src") or image.get("data-src") or image.get("data-original") or ""
        normalized = normalize_url(value, base_url)
        if normalized and not has_static_extension(normalized.replace(".jpg", "")):
            return normalized
        if normalized:
            return normalized
    return ""

def extract_availability(soup: BeautifulSoup, selector: str = "") -> str:
    selected = text_by_selector(soup, selector)
    if selected:
        return selected
    page_text = clean_text(soup.get_text(" ", strip=True))
    patterns = [
        r"В наличии",
        r"Нет в наличии",
        r"Под заказ",
        r"Ожидается",
        r"Сообщить о поступлении",
        r"available",
        r"out of stock",
        r"in stock",
    ]
    for pattern in patterns:
        match = re.search(pattern, page_text, flags=re.IGNORECASE)
        if match:
            return clean_text(match.group(0))
    return ""

def availability_is_excluded(availability: str, rules: object) -> bool:
    """Проверяет статус наличия по построчным правилам исключения до сравнения с фидами."""
    status = clean_text(availability).lower()
    if not status:
        return False
    for rule in normalize_patterns(rules):
        normalized_rule = clean_text(rule).lower()
        if normalized_rule and normalized_rule in status:
            return True
    return False

def extract_product_name(soup: BeautifulSoup, selector: str = "") -> str:
    selected = text_by_selector(soup, selector)
    if selected:
        return selected
    meta = soup.select_one("meta[property='og:title'], meta[name='twitter:title']")
    if meta and meta.get("content"):
        return clean_text(meta.get("content", ""))
    return first_text(soup, ["h1", "[itemprop='name']", ".product-title", ".product__title"])

def feed_source_key(url: str) -> str:
    hostname = urlparse(url).hostname or "feed"
    return safe_filename(hostname.lower().removeprefix("www."))

def feed_source_label(url: str) -> str:
    hostname = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if "mega-kuhnya" in hostname:
        return "Мега-кухня"
    if "vsya-tehnika" in hostname:
        return "Вся техника"
    return hostname or "Фид"

def source_feed_dir(source: str) -> Path:
    return FEED_DIR / safe_filename(source)

def local_feed_filename(kind: str, index: int, url: str) -> str:
    parsed = urlparse(url)
    raw_name = Path(parsed.path).name or kind
    stem = Path(raw_name).stem or kind
    suffix = Path(raw_name).suffix.lower()
    if suffix not in {".xml", ".yml"}:
        suffix = ".xml"
    return f"{index:02d}_{safe_filename(kind)}_{safe_filename(stem)}{suffix}"

def generation_file_url(url: str) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["cron"] = "file"
    return urlunparse(parsed._replace(query=urlencode(query)))

def clear_source_feeds(source: str) -> Path:
    feed_dir = source_feed_dir(source)
    if feed_dir.exists():
        for path in feed_dir.glob("*"):
            if path.is_file():
                path.unlink(missing_ok=True)
    feed_dir.mkdir(parents=True, exist_ok=True)
    return feed_dir

def make_feed_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            )
        }
    )
    return session

def trigger_feed_generation(generate_url: str) -> None:
    try:
        response = make_feed_session().get(generation_file_url(generate_url), timeout=60)
        response.raise_for_status()
    except Exception:
        pass

def download_feed_site(index: int, site: Dict[str, str]) -> Optional[Dict[str, object]]:
    url = site["feed_url"]
    try:
        response = make_feed_session().get(url, timeout=60)
        response.raise_for_status()
        source = feed_source_key(url)
        feed_dir = source_feed_dir(source)
        filename = local_feed_filename("feed", index, url)
        path = feed_dir / filename
        path.write_bytes(response.content)
        return {
            "kind": "feed",
            "source": source,
            "source_label": site.get("name") or feed_source_label(url),
            "url": url,
            "filename": filename,
            "size": path.stat().st_size,
            "downloaded_at": datetime.now(MSK_TZ).isoformat(timespec="seconds"),
        }
    except Exception:
        return None

def download_feed_files() -> List[Dict[str, object]]:
    with news_lock:
        own_sites = own_sites_from_settings(news_settings)
        feed_urls = [site["feed_url"] for site in own_sites]
        generate_urls = [site["feed_generate_url"] for site in own_sites if site.get("feed_generate_url")]
    downloaded: List[Dict[str, object]] = []
    with FEED_STORAGE_LOCK:
        expected_sources = {feed_source_key(url) for url in feed_urls}
        if FEED_DIR.exists():
            for child in FEED_DIR.iterdir():
                if child.is_dir() and child.name not in expected_sources:
                    shutil.rmtree(child, ignore_errors=True)
        for source in expected_sources:
            clear_source_feeds(source)
        if generate_urls:
            with ThreadPoolExecutor(max_workers=min(FEED_WORKER_COUNT, len(generate_urls))) as executor:
                list(executor.map(trigger_feed_generation, generate_urls))
        if own_sites:
            with ThreadPoolExecutor(max_workers=min(FEED_WORKER_COUNT, len(own_sites))) as executor:
                futures = [executor.submit(download_feed_site, index, site) for index, site in enumerate(own_sites, start=1)]
                for future in futures:
                    feed = future.result()
                    if feed:
                        downloaded.append(feed)
    return downloaded

def fetch_existing_vendor_codes() -> tuple[Set[str], List[Dict[str, object]]]:
    codes, feeds, _feed_code_sets = fetch_existing_vendor_code_sets()
    return codes, feeds

def fetch_existing_vendor_code_sets() -> tuple[Set[str], List[Dict[str, object]], List[Dict[str, object]]]:
    downloaded_feeds = download_feed_files()
    codes: Set[str] = set()
    feeds: List[Dict[str, object]] = []
    feed_code_sets: List[Dict[str, object]] = []
    for feed in downloaded_feeds:
        filename = str(feed.get("filename") or "")
        path = source_feed_dir(str(feed.get("source") or "")) / filename
        try:
            feed_codes = parse_vendor_codes_from_xml(path.read_bytes())
            codes.update(feed_codes)
            feeds.append({**feed, "codes_count": len(feed_codes)})
            feed_code_sets.append({**feed, "codes_count": len(feed_codes), "codes": feed_codes})
        except Exception as exc:
            feeds.append({**feed, "codes_count": 0, "error": str(exc)})
            feed_code_sets.append({**feed, "codes_count": 0, "codes": set(), "error": str(exc)})
    with news_lock:
        news_settings["feed_storage"] = feeds
        save_news_settings()
    save_logs()
    return codes, feeds, feed_code_sets

def product_compare_keys(product: Dict[str, str]) -> Set[str]:
    keys = {
        normalize_model_key(str(product.get("model", ""))),
        normalize_model_key(str(product.get("vendor_code", ""))),
    }
    keys.discard("")
    return keys

def build_missing_summary(new_items: List[Dict[str, str]], feed_code_sets: List[Dict[str, object]]) -> List[Dict[str, object]]:
    summary: List[Dict[str, object]] = []
    for feed in feed_code_sets:
        feed_codes = feed.get("codes", set())
        if not isinstance(feed_codes, set):
            feed_codes = set(feed_codes) if isinstance(feed_codes, list) else set()
        count = 0
        for item in new_items:
            keys = product_compare_keys(item)
            if keys and not (keys & feed_codes):
                count += 1
        summary.append(
            {
                "source": str(feed.get("source") or ""),
                "source_label": str(feed.get("source_label") or feed.get("url") or "Фид"),
                "url": str(feed.get("url") or ""),
                "count": count,
                "codes_count": int(feed.get("codes_count") or 0),
                "error": str(feed.get("error") or ""),
            }
        )
    return summary

def parse_vendor_codes_from_xml(content: bytes) -> Set[str]:
    codes: Set[str] = set()
    try:
        for _event, node in ET.iterparse(io.BytesIO(content), events=("end",)):
            children = list(node)
            if children:
                values: Dict[str, str] = {}
                for child in children:
                    key = str(child.tag).split("}")[-1].lower()
                    if key in {"vendorcode", "model", "name", "title"}:
                        values[key] = clean_text(child.text or "")
                vendor_code = normalize_model_key(values.get("vendorcode", ""))
                model = values.get("model") or values.get("name") or values.get("title") or vendor_code
                model_key = normalize_model_key(model)
                if vendor_code:
                    codes.add(vendor_code)
                if model_key:
                    codes.add(model_key)
                node.clear()
    except ET.ParseError:
        raise
    return codes

def parse_feed_products_from_xml(content: bytes) -> List[Dict[str, object]]:
    products: List[Dict[str, object]] = []
    root = ET.fromstring(content)
    for node in root.iter():
        children = list(node)
        if not children:
            continue
        values: Dict[str, str] = {}
        for child in children:
            key = str(child.tag).split("}")[-1].lower()
            values[key] = clean_text(child.text or "")
        vendor_code = normalize_model_key(values.get("vendorcode", ""))
        model = values.get("model") or values.get("name") or values.get("title") or vendor_code
        model_key = normalize_model_key(model)
        if not vendor_code and not model_key:
            continue
        products.append(
            {
                "vendor_code": vendor_code,
                "model_key": model_key,
                "name": values.get("name") or values.get("model") or values.get("title") or "",
                "url": values.get("url") or "",
                "raw": values,
            }
        )
    return products

def validate_monitor_selectors(monitor: Dict[str, object]) -> None:
    selector_fields = []
    rules = monitor.get("extraction_rules", {}) if isinstance(monitor.get("extraction_rules"), dict) else {}
    selectors = monitor.get("selector_settings", {}) if isinstance(monitor.get("selector_settings"), dict) else {}
    for key in ("product_card_selector", "product_url_selector", "model_selector", "price_selector"):
        if rules.get(key):
            selector_fields.append((key, str(rules[key])))
    for key in ("name_selector", "availability_selector", "photo_selector"):
        if selectors.get(key):
            selector_fields.append((key, str(selectors[key])))
    soup = BeautifulSoup("", "html.parser")
    for key, selector in selector_fields:
        try:
            soup.select(selector)
        except Exception as exc:
            raise ValueError(f"Ошибка CSS-селектора {key}: {selector}. {exc}") from exc
