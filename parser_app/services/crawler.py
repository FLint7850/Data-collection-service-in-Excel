"""Concurrent product-site crawler."""



from parser_app.runtime import *  # noqa: F401,F403



class ProductSiteCrawler:
    def __init__(
        self,
        start_urls: List[str],
        run_id: int,
        stop_signal: threading.Event,
        finish_signal: threading.Event,
        thread_count: int,
        project: Optional[Dict[str, object]] = None,
        exclusions: Optional[List[str]] = None,
        product_url_filters: Optional[List[str]] = None,
        extraction_rules: Optional[Dict[str, str]] = None,
        connection_method: str = "requests",
        auto_connection_fallback: bool = True,
        connection_method_state: Optional[Dict[str, object]] = None,
        allow_empty_price: bool = False,
    ):
        self.run_id = run_id
        self.stop_signal = stop_signal
        self.finish_signal = finish_signal
        self.thread_count = max(1, min(int(thread_count or 4), 16))
        self.start_urls = normalize_start_urls(start_urls)
        self.start_url = self.start_urls[0]
        self.root_netloc = urlparse(self.start_url).netloc
        self.project = project
        self.exclusions = exclusions if exclusions is not None else DEFAULT_EXCLUSIONS.copy()
        self.extraction_rules = normalize_extraction_rules(extraction_rules or {})
        self.product_url_filters = product_url_filter_patterns(product_url_filters or [], self.extraction_rules)
        self.connection_method = normalize_connection_method(connection_method)
        self.auto_connection_fallback = bool(auto_connection_fallback)
        self.allow_empty_price = bool(allow_empty_price)
        if connection_method_state is None:
            connection_method_state = {
                "active_method": self.connection_method,
                "lock": threading.Lock(),
            }
        else:
            connection_method_state.setdefault("active_method", self.connection_method)
            connection_method_state.setdefault("lock", threading.Lock())
        self.connection_method_state = connection_method_state
        self.active_connection_method = str(connection_method_state.get("active_method") or self.connection_method)
        self.thread_local = threading.local()
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        }
        self.queue: Queue[str] = Queue()
        self.queued: Set[str] = set()
        self.in_progress: Set[str] = set()
        self.visited: Set[str] = set()
        self.skipped_urls: Set[str] = set()
        self.result_urls: Set[str] = set()
        self.pending_prices: Dict[str, str] = {}
        self.results: List[Dict[str, str]] = []
        self.failed_attempts: Dict[str, int] = {}
        self.permanent_failures: Set[str] = set()
        self.data_lock = threading.Lock()
        self.excel_finalized = False
        self.started_at = 0.0
        self.elapsed_before_resume = 0.0
        self.last_progress_at = time.time()
        self.last_progress_signature: tuple = ()
        self.fatal_error = ""

    def update_state(self, **kwargs: object) -> None:
        if self.project is not None:
            if self.run_id != int(self.project.get("run_id", self.run_id)):
                return
            update_project_state(self.project, **kwargs)
        else:
            update_state(self.run_id, **kwargs)

    def reset_state(self, status: str = "idle") -> None:
        if self.project is not None:
            if self.run_id != int(self.project.get("run_id", self.run_id)):
                return
            reset_project_state(self.project, status)
        else:
            reset_state(status, self.run_id, self.thread_count)

    def log(self, message: str, level: str = "info") -> None:
        if self.project is not None:
            if self.run_id != int(self.project.get("run_id", self.run_id)):
                return
            add_project_log(self.project, message, level)

    def get_session(self) -> requests.Session:
        session = getattr(self.thread_local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update(self.headers)
            self.thread_local.session = session
        return session

    def fetch_with_requests(self, url: str) -> Optional[str]:
        last_error = ""
        candidate_urls = [url]
        for attempt in range(1, MAX_RETRIES + 1):
            if self.stop_signal.is_set():
                return None
            for candidate_url in candidate_urls:
                try:
                    response = self.get_session().get(candidate_url, timeout=REQUEST_TIMEOUT)
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "")
                    if "text/html" not in content_type and "application/xhtml" not in content_type:
                        return None
                    if not looks_blocked_or_empty(response.text):
                        return response.text

                    last_error = "страница похожа на блокировку или пустой JS-шаблон"
                    break
                except requests.RequestException as exc:
                    last_error = str(exc)
                    if isinstance(exc, requests.HTTPError) and exc.response is not None and exc.response.status_code in {404, 410}:
                        with self.data_lock:
                            self.permanent_failures.add(url)
                        self.log(f"URL пропущен: страница вернула {exc.response.status_code}: {url}", "warning")
                        return None
                    if isinstance(exc, requests.HTTPError) and exc.response is not None and exc.response.status_code in {401, 403}:
                        continue
                    break
            if last_error == "страница похожа на блокировку или пустой JS-шаблон":
                break
            if self.stop_signal.is_set():
                return None
            if attempt < MAX_RETRIES:
                time.sleep(min(attempt, 3))
        if last_error:
            self.log(f"requests не смог загрузить {url}: {last_error}", "warning")
        return None

    def fetch_by_method(self, url: str, method: str) -> Optional[str]:
        target_url = url
        if method == "requests":
            return self.fetch_with_requests(target_url)
        if method == "botasaurus-request":
            return fetch_with_botasaurus_request(target_url)
        if method == "botasaurus-browser":
            return fetch_with_botasaurus_browser(target_url, "google")
        if method == "botasaurus-browser-direct":
            return fetch_with_botasaurus_browser(target_url, "direct")
        if method == "botasaurus-visible":
            return fetch_with_botasaurus_visible_browser(target_url)
        if method == "botasaurus-debug-visible":
            return fetch_with_botasaurus_debug_visible_browser(target_url)
        if method == "crawl4ai":
            return fetch_with_crawl4ai(target_url)
        if method == "firecrawl":
            if not os.environ.get("FIRECRAWL_API_KEY", "").strip():
                self.log("Метод firecrawl пропущен: не задан FIRECRAWL_API_KEY", "warning")
                return None
            return fetch_with_firecrawl(target_url)
        if method == "scrapy":
            return fetch_with_scrapy(target_url)
        if method == "crawlee":
            return fetch_with_crawlee(target_url)
        if method == "playwright":
            return fetch_with_playwright(target_url)
        if method == "scrapegraphai":
            return fetch_with_scrapegraphai(target_url)
        return None

    def fetch_by_method_with_timeout(self, url: str, method: str) -> Optional[str]:
        if method in BROWSER_RENDER_METHODS:
            try:
                return self.fetch_by_method(url, method)
            except Exception as error:
                self.log(f"Метод подключения {method} завершился ошибкой для {url}: {error}", "warning")
                return None

        result_queue: Queue = Queue(maxsize=1)

        def run_method() -> None:
            try:
                result_queue.put(("ok", self.fetch_by_method(url, method)), block=False)
            except Exception as error:
                result_queue.put(("error", error), block=False)

        thread = threading.Thread(target=run_method, daemon=True)
        thread.start()
        try:
            status, value = result_queue.get(timeout=CONNECTION_METHOD_TIMEOUT_SECONDS)
        except Empty:
            self.log(
                f"Метод подключения {method} превысил таймаут {CONNECTION_METHOD_TIMEOUT_SECONDS} сек. для {url}",
                "warning",
            )
            return None
        if status == "error":
            self.log(f"Метод подключения {method} завершился ошибкой для {url}: {value}", "warning")
            return None
        return value if isinstance(value, str) else None

    def fallback_method_sequence(self) -> List[str]:
        """Возвращает полный цикл fallback-методов из БД в порядке id."""
        return [
            method
            for method in ordered_db_connection_methods()
            if method not in DEBUG_VISIBLE_METHODS or method == self.connection_method
        ]

    def current_connection_method(self) -> str:
        lock = self.connection_method_state["lock"]
        with lock:
            current = normalize_connection_method(self.connection_method_state.get("active_method"))
            self.connection_method_state["active_method"] = current
            self.active_connection_method = current
            return current

    def set_active_connection_method(self, method: str) -> None:
        lock = self.connection_method_state["lock"]
        with lock:
            current = normalize_connection_method(method)
            self.connection_method_state["active_method"] = current
            self.active_connection_method = current

    def html_has_expected_content(self, url: str, html: str) -> bool:
        """Reject technically non-empty pages that contain no usable project data.

        Browser engines can return a consent shell, navigation-only document or a
        partially rendered SPA. Treating that as success stops fallback too early
        and produces a completed project with an empty CSV.
        """
        if not html or looks_blocked_or_empty(html):
            return False

        # A known product page is parsed later with project rules. At this point a
        # complete, non-blocked document is enough; demanding a price here would
        # incorrectly reject pages where price is injected into a custom selector.
        if self.is_current_product_page(url):
            return True

        requires_catalog_signals = self.is_start_url_path(url) or is_catalog_url(url)
        if not requires_catalog_signals:
            return True

        if PRICE_RE.search(html):
            return True

        if extract_listing_products(url, html, self.extraction_rules, self.product_url_filters):
            return True

        # A category without inline prices is still useful when it exposes links to
        # product pages. This also supports sites whose prices appear only on detail pages.
        soup = BeautifulSoup(html, "html.parser")
        for link in soup.select("a[href]"):
            product_url = canonicalize_product_url_by_filters(
                normalize_url(link.get("href", ""), url),
                self.product_url_filters,
            )
            if not product_url or product_url == url or not same_site(product_url, self.root_netloc):
                continue
            if self.is_product_url(product_url) and self.is_product_allowed(product_url):
                return True

        return False

    def fetch_with_connection_method(self, url: str, method: str) -> Optional[str]:
        self.log(f"Пробую метод подключения {method} для {url}", "info")
        html = self.fetch_by_method_with_timeout(url, method)
        if html and self.html_has_expected_content(url, html):
            return html
        if html and not looks_blocked_or_empty(html):
            self.log(
                f"Метод подключения {method} вернул HTML без товаров, цен или товарных ссылок для {url}",
                "warning",
            )
        else:
            self.log(f"Метод подключения {method} не сработал для {url}", "warning")
        return None

    def fetch(self, url: str) -> Optional[str]:
        current_method = self.current_connection_method()
        last_method = current_method

        if self.stop_signal.is_set():
            return None

        html = self.fetch_with_connection_method(url, current_method)
        if html:
            return html

        with self.data_lock:
            if url in self.permanent_failures:
                return None

        if not self.auto_connection_fallback:
            self.update_state(
                error=(
                    f"Не удалось загрузить {url}. Последний метод: {last_method}. "
                    "Проверьте способ подключения или включите автопереключение."
                ),
            )
            self.log(f"Не удалось загрузить {url}. Последний метод: {last_method}", "error")
            return None

        for method in self.fallback_method_sequence():
            if self.stop_signal.is_set():
                return None
            if method == current_method:
                continue
            last_method = method
            html = self.fetch_with_connection_method(url, method)
            if html:
                if method != current_method:
                    self.set_active_connection_method(method)
                    self.log(f"Автопереключение подключения: {method} для {url}", "warning")
                return html
            with self.data_lock:
                if url in self.permanent_failures:
                    break

        self.update_state(
            error=(
                f"Не удалось загрузить {url}. Последний метод: {last_method}. "
                "Проверьте способ подключения или включите автопереключение."
            ),
        )
        self.log(f"Не удалось загрузить {url}. Последний метод: {last_method}", "error")
        return None

    def is_excluded(self, url: str) -> bool:
        patterns = self.exclusions

        matched = any(exclusion_matches(url, pattern) for pattern in patterns)
        if matched and url not in self.skipped_urls:
            with self.data_lock:
                self.skipped_urls.add(url)
                skipped_count = len(self.skipped_urls)
            self.update_state(skipped=skipped_count)
        return matched

    def is_product_allowed(self, url: str) -> bool:
        return product_url_matches_filters(url, self.product_url_filters)

    def is_filter_marked_product(self, url: str) -> bool:
        return bool(self.product_url_filters) and product_url_matches_filters(url, self.product_url_filters)

    def is_product_url(self, url: str) -> bool:
        return is_product_url_for_filters(url, self.product_url_filters)

    def is_start_url_path(self, url: str) -> bool:
        parsed = urlparse(url)
        normalized_path = (parsed.path or "/").rstrip("/") or "/"
        for start_url in self.start_urls:
            start_parsed = urlparse(start_url)
            if not same_site(url, start_parsed.netloc or self.root_netloc):
                continue
            start_path = (start_parsed.path or "/").rstrip("/") or "/"
            if normalized_path == start_path:
                return True
        return False

    def is_current_product_page(self, url: str) -> bool:
        return self.is_product_url(url) and not self.is_start_url_path(url)

    def remember_listing_price(self, product_url: str, price: str) -> None:
        product_url = canonicalize_product_url_by_filters(product_url, self.product_url_filters)
        with self.data_lock:
            if product_url and price:
                self.pending_prices[product_url] = price

    def get_listing_price(self, product_url: str) -> str:
        product_url = canonicalize_product_url_by_filters(product_url, self.product_url_filters)
        with self.data_lock:
            return self.pending_prices.get(product_url, "")

    def enqueue(self, url: Optional[str], force: bool = False) -> None:
        url = canonicalize_product_url_by_filters(url or "", self.product_url_filters)
        if not url or url in self.visited or url in self.queued or url in self.in_progress:
            return
        is_product = self.is_product_url(url)
        if is_product and not self.is_product_allowed(url):
            return
        with self.data_lock:
            if url in self.result_urls:
                return
        if not force:
            if is_product:
                if not same_site(url, self.root_netloc) or has_static_extension(url):
                    return
            elif not should_follow_project_url(url, self.start_urls, self.root_netloc):
                return
        if force and (not same_site(url, self.root_netloc) or has_static_extension(url)):
            return
        if self.is_excluded(url):
            return
        self.queue.put(url)
        self.queued.add(url)

    def requeue_pending(self, pending_urls: Iterable[str]) -> None:
        with self.data_lock:
            for url in pending_urls:
                self.in_progress.discard(url)
        for url in pending_urls:
            self.enqueue(url, force=True)

    def extract_links(self, html: str, current_url: str) -> None:
        soup = BeautifulSoup(html, "html.parser")
        for link in soup.select("a[href]"):
            normalized = normalize_url(link.get("href", ""), current_url)
            self.enqueue(normalized)

    def add_products(self, products: Iterable[Dict[str, str]]) -> int:
        added = 0
        with self.data_lock:
            for product in products:
                product_url = canonicalize_product_url_by_filters(product.get("url", ""), self.product_url_filters)
                model = product.get("model", "")
                price = product.get("price", "")
                if product_url and not self.is_product_allowed(product_url):
                    continue
                if not product_url or not model or (not price and not self.allow_empty_price) or product_url in self.result_urls:
                    continue
                product["url"] = product_url
                self.result_urls.add(product_url)
                self.results.append(product)
                added += 1
        return added

    def snapshot_counts(self) -> Dict[str, int]:
        with self.data_lock:
            return {
                "visited": len(self.visited),
                "results": len(self.results),
                "skipped": len(self.skipped_urls),
                "queued": self.queue.qsize(),
                "active": len(self.in_progress),
                "failed": len(self.failed_attempts),
            }

    def snapshot_results(self) -> List[Dict[str, str]]:
        with self.data_lock:
            return [dict(item) for item in self.results]

    def refresh_progress(self, current_url: str = "") -> None:
        remaining = self.queue.qsize()
        counts = self.snapshot_counts()
        processed = counts["visited"]
        total_known = processed + remaining
        percent = int((processed / total_known) * 100) if total_known else 0
        elapsed = self.elapsed_seconds()
        eta = None
        if processed > 0 and remaining > 0:
            eta = int((elapsed / processed) * remaining)
        self.update_state(
            percent=percent,
            currenturl=current_url,
            totalprocessed=processed,
            processed_products=counts["results"],
            found_products=counts["results"],
            in_memory_products=counts["results"],
            queue_size=remaining,
            active_tasks=counts["active"],
            active_urls=sorted(self.in_progress)[:8],
            failed_pages=counts["failed"],
            stall_seconds=max(0, int(time.time() - self.last_progress_at)),
            skipped=counts["skipped"],
            thread_count=self.thread_count,
            elapsed_seconds=int(elapsed),
            eta_seconds=eta,
        )

    def progress_signature(self, pending_urls: Iterable[str]) -> tuple:
        counts = self.snapshot_counts()
        return (
            counts["visited"],
            counts["results"],
            counts["skipped"],
            self.queue.qsize(),
            tuple(sorted(pending_urls)),
        )

    def note_progress_activity(self, pending_urls: Iterable[str]) -> None:
        signature = self.progress_signature(pending_urls)
        if signature != self.last_progress_signature:
            self.last_progress_signature = signature
            self.last_progress_at = time.time()

    def mark_stalled(self, pending_urls: Iterable[str]) -> None:
        active_urls = list(pending_urls)
        counts = self.snapshot_counts()
        message = (
            f"Сбор не двигается {NEWS_SCAN_STALL_TIMEOUT} секунд. "
            f"Активных задач: {len(active_urls)}; очередь: {self.queue.qsize()}; "
            f"товаров в памяти: {counts['results']}. "
            f"Активные URL: {', '.join(active_urls[:5])}"
        )
        self.fatal_error = message
        self.update_state(
            status="error",
            error=message,
            currenturl=active_urls[0] if active_urls else "",
            active_urls=active_urls[:8],
            active_tasks=len(active_urls),
            queue_size=self.queue.qsize(),
            in_memory_products=counts["results"],
            stall_seconds=NEWS_SCAN_STALL_TIMEOUT,
        )
        self.log(message, "error")
        self.stop_signal.set()

    def elapsed_seconds(self) -> float:
        if self.started_at:
            return self.elapsed_before_resume + max(0.0, time.time() - self.started_at)
        return self.elapsed_before_resume

    def process_page(self, url: str, html: str) -> None:
        current_is_product = self.is_current_product_page(url)
        listing_products: List[Dict[str, str]] = []
        listing_price = self.get_listing_price(url)

        if current_is_product:
            product = extract_product_data(
                url,
                html,
                listing_price,
                self.extraction_rules,
                assume_product=True,
                allow_empty_price=self.allow_empty_price,
            )
            if product:
                self.add_products([product])
                if is_technopark_url(url):
                    self.log(f"Страница обработана: {url}. Найдено товаров на странице: 1", "info")
                return

            current_is_product = False

        listing_products = extract_listing_products(url, html, self.extraction_rules, self.product_url_filters)

        if not current_is_product and not listing_products and (is_catalog_url(url) or not is_probable_product_url(url)) and not PRICE_RE.search(html):
            self.update_state(
                error=f"На странице каталога нет цен в HTML. Рендерю через Botasaurus: {url}",
            )
            self.log(f"Рендеринг каталога через Botasaurus: {url}", "warning")
            rendered_html = fetch_with_botasaurus_browser(url)
            if rendered_html and not looks_blocked_or_empty(rendered_html):
                html = rendered_html
                listing_products = extract_listing_products(url, html, self.extraction_rules, self.product_url_filters)
                self.update_state(error="")

        for product in listing_products:
            product_url = canonicalize_product_url_by_filters(product.get("url", ""), self.product_url_filters)
            product["url"] = product_url
            self.remember_listing_price(product_url, product.get("price", ""))
            self.enqueue(product_url, force=True)
        if not self.product_url_filters:
            self.add_products(listing_products)

        should_extract_current_product = (
            not self.is_start_url_path(url)
            and (not listing_products or bool(self.get_listing_price(url)))
        )
        product = None if not should_extract_current_product else extract_product_data(
            url,
            html,
            self.get_listing_price(url),
            self.extraction_rules,
            assume_product=self.is_product_url(url),
            allow_empty_price=self.allow_empty_price,
        )
        if product:
            self.add_products([product])

        if is_technopark_url(url):
            self.log(f"Страница обработана: {url}. Найдено товаров на странице: {len(listing_products)}", "info")

        if not current_is_product:
            self.extract_links(html, url)

    def finish_with_excel(self, partial: bool = False) -> None:
        with self.data_lock:
            if self.excel_finalized:
                return
            self.excel_finalized = True

        rows = self.snapshot_results()
        counts = self.snapshot_counts()
        filename = create_export_file(rows, self.project)
        if self.project is not None:
            delete_project_csv_for_project(self.project, keep_filename=filename.name)
        final_error = ""
        if partial:
            final_error = "Сбор приостановлен. CSV сформирован по уже найденным товарам."
        elif not self.results:
            final_error = (
                "Сбор завершен, но товары не найдены. Проверьте стартовый URL и исключения; "
                "для защищенных страниц убедитесь, что Botasaurus установился через run.ps1."
            )

        self.update_state(
            status="partial" if partial else "completed",
            percent=100 if not partial else int((self.project or {}).get("state", {}).get("percent", 0) or 0),
            currenturl="",
            totalprocessed=counts["visited"],
            processed_products=counts["results"],
            found_products=counts["results"],
            skipped=counts["skipped"],
            download_ready=True,
            download_url="/download",
            filename=filename.name,
            error=final_error,
            thread_count=self.thread_count,
            elapsed_seconds=int(self.elapsed_seconds()),
            eta_seconds=None,
            finished_at=now_iso() if not partial else "",
            paused_with_result=partial,
        )
        self.log(f"CSV сформирован: {filename.name}. Товаров: {counts['results']}", "success")
        if self.project is not None:
            save_projects()

    def run(self, resume: bool = False) -> None:
        if not self.started_at:
            self.started_at = time.time()
        self.update_state(
            status="running",
            thread_count=self.thread_count,
            started_at=(self.project or {}).get("state", {}).get("started_at") or now_iso(),
            paused_with_result=False,
        )
        self.log("Сбор продолжен" if resume else "Сбор запущен", "info")
        if not resume:
            for start_url in self.start_urls:
                self.enqueue(start_url)

        executor = ThreadPoolExecutor(max_workers=self.thread_count)
        pending = {}
        pending_urls_to_requeue = []
        self.note_progress_activity([])

        try:
            while not self.stop_signal.is_set():
                while len(pending) < self.thread_count:
                    try:
                        url = self.queue.get_nowait()
                    except Empty:
                        break

                    self.queued.discard(url)
                    if url in self.visited or url in self.in_progress:
                        continue
                    with self.data_lock:
                        if url in self.result_urls and is_probable_product_url(url):
                            continue
                    self.in_progress.add(url)
                    self.update_state(
                        currenturl=url,
                        active_urls=sorted(self.in_progress)[:8],
                        active_tasks=len(self.in_progress),
                        queue_size=self.queue.qsize(),
                    )
                    pending[executor.submit(self.fetch, url)] = url
                    self.note_progress_activity(pending.values())
                    time.sleep(REQUEST_DELAY_SECONDS)

                if not pending:
                    if self.queue.empty():
                        break
                    continue

                done, _pending = wait(pending.keys(), timeout=0.5, return_when=FIRST_COMPLETED)
                if not done:
                    self.refresh_progress()
                    self.note_progress_activity(pending.values())
                    if pending and time.time() - self.last_progress_at >= NEWS_SCAN_STALL_TIMEOUT:
                        self.mark_stalled(pending.values())
                    continue

                for future in done:
                    url = pending.pop(future)
                    self.note_progress_activity(pending.values())
                    with self.data_lock:
                        self.in_progress.discard(url)
                        self.visited.add(url)
                    html = None
                    try:
                        html = future.result()
                    except Exception as exc:  # noqa: BLE001 - ошибку показываем в интерфейсе.
                        self.update_state(error=f"Ошибка обработки {url}: {exc}")
                        self.log(f"Ошибка обработки {url}: {exc}", "error")

                    if html and not self.stop_signal.is_set():
                        self.process_page(url, html)
                    elif not self.stop_signal.is_set():
                        with self.data_lock:
                            permanent_failure = url in self.permanent_failures
                        if permanent_failure:
                            self.log(f"URL пропущен без повторов: {url}", "warning")
                            self.refresh_progress(url)
                            continue
                        retry_count = self.failed_attempts.get(url, 0) + 1
                        self.failed_attempts[url] = retry_count
                        if retry_count <= 2:
                            with self.data_lock:
                                self.visited.discard(url)
                            self.enqueue(url, force=True)
                            self.log(f"Повторная попытка загрузки {retry_count}/2: {url}", "warning")
                        else:
                            self.log(f"URL пропущен после повторных попыток загрузки: {url}", "error")

                    self.refresh_progress(url)
        finally:
            if self.stop_signal.is_set():
                pending_urls_to_requeue = list(pending.values())
                self.requeue_pending(pending_urls_to_requeue)
            executor.shutdown(wait=False, cancel_futures=True)

        if self.stop_signal.is_set():
            self.elapsed_before_resume = self.elapsed_seconds()
            self.started_at = 0.0
            stop_mode = str((self.project or {}).get("stop_mode") or "")
            if self.finish_signal.is_set():
                self.finish_with_excel(partial=True)
            elif stop_mode == "pause":
                self.update_state(
                    status="paused",
                    currenturl="",
                    elapsed_seconds=int(self.elapsed_before_resume),
                    eta_seconds=None,
                    error="Сбор на паузе",
                )
                if (self.project or {}).get("state", {}).get("status") == "paused":
                    self.log("Сбор поставлен на паузу", "warning")
            else:
                self.update_state(
                    status="idle",
                    currenturl="",
                    active_urls=[],
                    active_tasks=0,
                    queue_size=0,
                    elapsed_seconds=int(self.elapsed_before_resume),
                    eta_seconds=None,
                    error="",
                    paused_with_result=False,
                )
                if stop_mode == "stop":
                    self.log("Сбор остановлен", "warning")
            return

        self.elapsed_before_resume = self.elapsed_seconds()
        self.started_at = 0.0
        self.finish_with_excel()
