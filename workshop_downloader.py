import argparse
import concurrent.futures
import html
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path
import shutil

CATALOG_BASE = "https://catalogue.smods.ru"
HOME_URL = f"{CATALOG_BASE}/"
STEAM_WORKSHOP_BASE = "https://steamcommunity.com"
STEAMWORKSHOP_DL_HOME = "http://steamworkshop.download/"
STEAMWORKSHOP_DL_API = "http://steamworkshop.download/online/steamonline.php"
SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "data"
CONFIG_PATH = DATA_DIR / "py-config.json"
GAMES_CACHE_PATH = DATA_DIR / "games-cache.json"
ZH_NAME_CACHE_PATH = DATA_DIR / "zh-name-cache.json"

DEFAULT_CONFIG = {
    "download_dir": str(Path.home() / "Downloads"),
    "timeout": 25,
    "retries": 2,
    "workers": 3,
    "refresh_games_cache": False,
}

PRINT_LOCK = threading.Lock()
BANNER_ART = """███████╗████████╗███████╗ █████╗ ███╗   ███╗    ██╗    ██╗ ██████╗ ██████╗ ██╗  ██╗███████╗██╗  ██╗ ██████╗ ██████╗
██╔════╝╚══██╔══╝██╔════╝██╔══██╗████╗ ████║    ██║    ██║██╔═══██╗██╔══██╗██║ ██╔╝██╔════╝██║  ██║██╔═══██╗██╔══██╗
███████╗   ██║   █████╗  ███████║██╔████╔██║    ██║ █╗ ██║██║   ██║██████╔╝█████╔╝ ███████╗███████║██║   ██║██████╔╝
╚════██║   ██║   ██╔══╝  ██╔══██║██║╚██╔╝██║    ██║███╗██║██║   ██║██╔══██╗██╔═██╗ ╚════██║██╔══██║██║   ██║██╔═══╝
███████║   ██║   ███████╗██║  ██║██║ ╚═╝ ██║    ╚███╔███╔╝╚██████╔╝██║  ██║██║  ██╗███████║██║  ██║╚██████╔╝██║
╚══════╝   ╚═╝   ╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝     ╚══╝╚══╝  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚═╝"""


def ensure_data_dir_and_migrate():
    first_run = not DATA_DIR.exists()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    legacy_paths = {
        SCRIPT_DIR / "py-config.json": CONFIG_PATH,
        SCRIPT_DIR / "games-cache.json": GAMES_CACHE_PATH,
        SCRIPT_DIR / "zh-name-cache.json": ZH_NAME_CACHE_PATH,
    }
    for old_path, new_path in legacy_paths.items():
        if old_path.exists() and not new_path.exists():
            try:
                shutil.copy2(old_path, new_path)
            except Exception:
                pass
    return first_run
EXACT_SEARCH_NOTICE = "请使用地图/模组全称搜索，否则不保证输出可靠。"


def setup_console_utf8():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def log(message: str, level: str = "INFO"):
    with PRINT_LOCK:
        print(f"[{level}] {message}")


def load_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_json(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_config():
    cfg = DEFAULT_CONFIG.copy()
    raw = load_json(CONFIG_PATH)
    if raw is None:
        print("首次运行程序，跳过配置检查...")
        return cfg
    cfg.update({k: v for k, v in raw.items() if k in cfg})
    return cfg


def save_config(cfg):
    save_json(CONFIG_PATH, cfg)


def default_headers(referer=None):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def new_opener():
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))


def http_get(opener, url, timeout, headers=None, retries=0):
    last_error = None
    for i in range(max(0, retries) + 1):
        try:
            req = urllib.request.Request(url, headers=headers or default_headers())
            with opener.open(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="ignore")
        except Exception as e:
            last_error = e
            if i < retries:
                time.sleep(1)
    raise last_error


def http_post(opener, url, timeout, body_dict, headers=None, retries=0):
    last_error = None
    for i in range(max(0, retries) + 1):
        try:
            data = urllib.parse.urlencode(body_dict).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers=headers or default_headers(), method="POST")
            with opener.open(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="ignore")
        except Exception as e:
            last_error = e
            if i < retries:
                time.sleep(1)
    raise last_error


def load_name_cache():
    obj = load_json(ZH_NAME_CACHE_PATH)
    return obj if isinstance(obj, dict) else {}


def save_name_cache(cache_obj):
    save_json(ZH_NAME_CACHE_PATH, cache_obj)


def normalize_name(text: str):
    if not text:
        return ""
    value = text.strip().lower()
    value = re.sub(r"%[0-9a-f]{2}", " ", value)
    value = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value)
    return value


def name_variants(game_name: str, slug: str):
    variants = set()
    if game_name:
        variants.add(game_name.strip())
        for m in re.finditer(r"[\u4e00-\u9fff]{2,}", game_name):
            variants.add(m.group(0))
        for m in re.finditer(r"[A-Za-z0-9][A-Za-z0-9 '&:;,+\-.]{2,}", game_name):
            variants.add(m.group(0).strip())
    if slug:
        variants.add(slug)
        decoded = urllib.parse.unquote(slug)
        variants.add(decoded)
        variants.add(decoded.replace("-", " "))
    return sorted(v for v in variants if v)


def fetch_supported_games(timeout: int, retries: int = 0):
    log("Fetching supported games from website...", "STEP")
    opener = new_opener()
    html_text = http_get(opener, HOME_URL, timeout, default_headers(), retries=retries)
    pattern = re.compile(
        r'<div class="game-tile-wrapper">.*?<a class="game-hover" href="https?://catalogue\.smods\.ru/game/([^"]+)">.*?'
        r'<h2 class="game-title">(.*?)</h2>.*?<a class="game-buy-btn" href="https?://store\.steampowered\.com/app/(\d+)',
        re.I | re.S,
    )
    records = {}
    for m in pattern.finditer(html_text):
        appid = int(m.group(3))
        slug = m.group(1).strip()
        game_name = html.unescape(re.sub(r"<.*?>", "", m.group(2)).strip())
        records[appid] = {
            "AppId": appid,
            "Slug": slug,
            "Game": game_name,
            "Aliases": name_variants(game_name, slug),
        }
    games = sorted(records.values(), key=lambda x: x["AppId"])
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "source": HOME_URL,
        "count": len(games),
        "games": games,
    }
    save_json(GAMES_CACHE_PATH, payload)
    log(f"Games cache saved: {GAMES_CACHE_PATH} (count={len(games)})", "OK")
    return games


def load_games(timeout: int, force_refresh=False, retries: int = 0):
    if not force_refresh:
        cached = load_json(GAMES_CACHE_PATH)
        if cached and isinstance(cached.get("games"), list) and cached["games"]:
            return cached["games"]
    return fetch_supported_games(timeout, retries=retries)


def resolve_game(games, game=None, appid=None):
    if appid:
        for g in games:
            if int(g["AppId"]) == int(appid):
                return g
        return {"AppId": int(appid), "Slug": "", "Game": "(Unknown)", "Aliases": []}

    if not game:
        raise ValueError("请提供游戏名或 AppId")

    candidate = game.strip()
    if candidate.isdigit():
        return resolve_game(games, appid=int(candidate))

    lower = candidate.lower()
    key = normalize_name(candidate)

    for g in games:
        if g["Slug"].lower() == lower or g["Game"].lower() == lower:
            return g

    for g in games:
        alias_keys = {normalize_name(a) for a in g.get("Aliases", [])}
        if key in alias_keys:
            return g

    for g in games:
        if lower in g["Slug"].lower() or lower in g["Game"].lower():
            return g
        alias_keys = {normalize_name(a) for a in g.get("Aliases", [])}
        if any(key in alias for alias in alias_keys):
            return g

    raise ValueError(f"无法匹配游戏: {candidate}")


def get_keywords(keyword=None, list_file=None):
    tasks = []
    if keyword and keyword.strip():
        tasks.append(keyword.strip())
    if list_file:
        path = Path(list_file)
        if not path.exists():
            raise FileNotFoundError(f"关键词文件不存在: {list_file}")
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            s = line.strip()
            if s and not s.startswith("#"):
                tasks.append(s)
    return tasks


def clean_keyword(text: str):
    value = (text or "").strip()
    value = re.sub(r"（[^）]*）", "", value).strip()
    return value


def normalize_exact_text(text: str):
    value = html.unescape((text or "").strip().lower())
    value = re.sub(r"\s+", " ", value)
    return value


def find_catalog_results(opener, search_text: str, timeout: int, appid: int = None, retries: int = 0):
    if appid:
        url = f"{CATALOG_BASE}/?s={urllib.parse.quote(search_text)}&app={appid}"
    else:
        url = f"{CATALOG_BASE}/?s={urllib.parse.quote(search_text)}"
    body = http_get(opener, url, timeout, default_headers(), retries=retries)
    pattern = re.compile(
        r'<h2 class="post-title entry-title">\s*<a href="https?://catalogue\.smods\.ru/archives/(\d+)"[^>]*>(.*?)</a>.*?'
        r'<a class="skymods-excerpt-btn[^"]*" href="(https?://modsbase\.com/[^"]+)"',
        re.I | re.S,
    )
    results = []
    for m in pattern.finditer(body):
        results.append(
            {
                "ArchiveId": m.group(1),
                "Title": html.unescape(re.sub(r"<.*?>", "", m.group(2)).strip()),
                "ModsLink": m.group(3),
                "SearchUrl": url,
            }
        )
    return results


def find_exact_catalog_result(opener, search_text: str, timeout: int, appid: int = None, retries: int = 0):
    results = find_catalog_results(opener, search_text, timeout, appid=appid, retries=retries)
    if not results:
        return None

    key = normalize_exact_text(search_text)
    for row in results:
        if normalize_exact_text(row["Title"]) == key:
            return row
    return None


def find_catalog_result_by_workshop_id(opener, appid: int, workshop_item_id: str, timeout: int, retries: int = 0):
    results = find_catalog_results(opener, str(workshop_item_id), timeout, appid=appid, retries=retries)
    if not results:
        return None
    return results[0]


def normalize_direct_url(url: str):
    if not url:
        return None
    if url.startswith("//"):
        url = "https:" + url
    if re.search(r"https?://modsbase\.com/.+\.zip\.html", url, re.I):
        return None
    return url


def first_match(text: str, patterns):
    for p in patterns:
        m = re.search(p, text, re.I | re.S)
        if m:
            return m.group(1)
    return None


def parse_direct_url(html_text: str):
    candidate = first_match(
        html_text,
        [
            r'href="((?:https?:)?//[^"\s]*?/cgi-bin/dl?\.cgi/[^"\s]+)"',
            r"href='((?:https?:)?//[^'\s]*?/cgi-bin/dl?\.cgi/[^'\s]+)'",
            r'href="((?:https?:)?//[^"\s]+\.zip(?!\.html)(?:\?[^"\s]*)?)"',
            r"href='((?:https?:)?//[^'\s]+\.zip(?!\.html)(?:\?[^'\s]*)?)'",
            r"(?:location\.href|window\.open)\s*\(\s*['\"]((?:https?:)?//[^'\"\s]+)['\"]\s*\)",
        ],
    )
    return normalize_direct_url(candidate)


def parse_hidden_inputs(html_text: str):
    result = {}
    for m in re.finditer(r"<input[^>]+type=['\"]hidden['\"][^>]*>", html_text, re.I | re.S):
        tag = m.group(0)
        n = first_match(tag, [r'name="([^"]+)"', r"name='([^']+)'"])
        if not n:
            continue
        v = first_match(tag, [r'value="([^"]*)"', r"value='([^']*)'"])
        result[n] = v if v is not None else ""
    return result


def build_steam_workshop_search_url(appid: int, search_text: str):
    params = {
        "appid": str(int(appid)),
        "searchtext": search_text,
        "childpublishedfileid": "0",
        "browsesort": "trend",
        "section": "readytouseitems",
        "created_date_range_filter_start": "0",
        "created_date_range_filter_end": "0",
        "updated_date_range_filter_start": "0",
        "updated_date_range_filter_end": "0",
    }
    return f"{STEAM_WORKSHOP_BASE}/workshop/browse/?{urllib.parse.urlencode(params)}"


def find_first_steam_workshop_item(opener, appid: int, search_text: str, timeout: int, retries: int = 0):
    browse_url = build_steam_workshop_search_url(appid, search_text)
    body = http_get(opener, browse_url, timeout, default_headers(), retries=retries)
    candidates = []
    pattern = re.compile(
        r'<a[^>]+href="(https?://steamcommunity\.com/sharedfiles/filedetails/\?id=(\d+)[^"]*)"[^>]*>(.*?)</a>',
        re.I | re.S,
    )
    for m in pattern.finditer(body):
        href = m.group(1)
        item_id = m.group(2)
        title = html.unescape(re.sub(r"<.*?>", "", m.group(3))).strip()
        if not title or title.lower() in {"learn more", "了解更多"}:
            continue
        candidates.append({"href": href, "item_id": item_id, "title": title})

    if not candidates:
        return None

    preferred = next((x for x in candidates if "searchtext=" in x["href"].lower()), candidates[0])
    item_id = preferred["item_id"]
    title = preferred["title"]
    item_url = f"{STEAM_WORKSHOP_BASE}/sharedfiles/filedetails/?id={item_id}"
    return {"ItemId": item_id, "AppId": int(appid), "Title": title, "ItemUrl": item_url, "SearchUrl": browse_url}


def resolve_steamworkshopdownload_url(
    opener, workshop_item_url: str, item_id: str, appid: int, timeout: int, retries: int = 0
):
    headers = default_headers(referer=workshop_item_url)
    first_page = http_post(
        opener,
        STEAMWORKSHOP_DL_HOME,
        timeout,
        {"url": workshop_item_url},
        headers=headers,
        retries=retries,
    )

    direct = parse_direct_url(first_page)
    if direct:
        return direct

    item_app = re.search(r"data:\s*\{\s*item:\s*(\d+),\s*app:\s*(\d+)\s*\}", first_page, re.I | re.S)
    target_item = item_app.group(1) if item_app else str(item_id)
    target_app = int(item_app.group(2)) if item_app else int(appid)
    referer = f"{STEAMWORKSHOP_DL_HOME.rstrip('/')}/download/view/{target_item}"

    second_page = http_post(
        opener,
        STEAMWORKSHOP_DL_API,
        timeout,
        {"item": target_item, "app": str(target_app)},
        headers=default_headers(referer=referer),
        retries=retries,
    )
    return parse_direct_url(second_page)


def resolve_direct_download_url(opener, mods_link: str, referer_url: str, timeout: int, retries: int = 0):
    headers = default_headers(referer=referer_url)
    first_page = http_get(opener, mods_link, timeout, headers, retries=retries)
    direct = parse_direct_url(first_page)
    if direct:
        return direct

    action = first_match(
        first_page,
        [
            r"<form[^>]+method=['\"]post['\"][^>]+action=['\"]([^'\"]+)['\"]",
            r"<form[^>]+action=['\"]([^'\"]+)['\"][^>]+method=['\"]post['\"]",
        ],
    )
    if not action:
        action = mods_link
    if action.startswith("/"):
        action = "https://modsbase.com" + action
    if action.startswith("//"):
        action = "https:" + action

    body = parse_hidden_inputs(first_page)
    if "method_free" not in body:
        body["method_free"] = ""

    time.sleep(3)
    second_page = http_post(opener, action, timeout, body, headers, retries=retries)
    return parse_direct_url(second_page)


def safe_filename(text: str):
    return re.sub(r'[\\/:*?"<>|]+', "_", text)


def output_filename(direct_url: str, title: str):
    file_name = ""
    try:
        path = urllib.parse.urlparse(direct_url).path
        file_name = os.path.basename(path)
    except Exception:
        file_name = ""
    if not file_name or file_name.lower() in ("dl.cgi", "d.cgi"):
        file_name = safe_filename(title) + ".zip"
    return html.unescape(file_name)


def format_bytes(num: float):
    value = float(max(0.0, num))
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while value >= 1024 and idx < len(units) - 1:
        value /= 1024.0
        idx += 1
    if idx == 0:
        return f"{int(value)}{units[idx]}"
    return f"{value:.2f}{units[idx]}"


def format_duration(seconds: float):
    sec = int(max(0, round(seconds)))
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def download_file_with_progress(
    opener, direct_url: str, file_path: Path, timeout: int, label: str = "", progress_hook=None, emit_logs=True
):
    req = urllib.request.Request(direct_url, headers=default_headers())
    with opener.open(req, timeout=timeout) as resp, open(file_path, "wb") as f:
        length_header = resp.headers.get("Content-Length", "")
        total_size = int(length_header) if str(length_header).isdigit() else 0
        downloaded = 0
        start_ts = time.time()
        last_log_ts = 0.0
        next_percent_mark = 0.1
        logged_complete = False
        chunk_size = 256 * 1024
        tag = (label or file_path.name or "download")[:48]
        if progress_hook:
            progress_hook(
                {
                    "phase": "start",
                    "label": tag,
                    "downloaded": 0,
                    "total_size": total_size,
                    "speed": 0.0,
                    "eta": None,
                    "pct": 0.0,
                }
            )

        while True:
            chunk = resp.read(chunk_size)
            if not chunk:
                break
            f.write(chunk)
            downloaded += len(chunk)

            now = time.time()
            elapsed = max(0.001, now - start_ts)
            speed = downloaded / elapsed
            should_log_time = now - last_log_ts >= 1.2
            should_log_percent = bool(total_size) and (downloaded / total_size) >= next_percent_mark
            if should_log_time or should_log_percent:
                if total_size > 0:
                    pct = min(100.0, downloaded * 100.0 / total_size)
                    remain = max(0, total_size - downloaded)
                    eta = remain / max(1.0, speed)
                    if emit_logs:
                        log(
                            f"{tag} | {pct:5.1f}% | {format_bytes(downloaded)}/{format_bytes(total_size)} | "
                            f"{format_bytes(speed)}/s | ETA {format_duration(eta)}",
                            "PROG",
                        )
                    if progress_hook:
                        progress_hook(
                            {
                                "phase": "downloading",
                                "label": tag,
                                "downloaded": downloaded,
                                "total_size": total_size,
                                "speed": speed,
                                "eta": eta,
                                "pct": pct,
                            }
                        )
                    if pct >= 100.0:
                        logged_complete = True
                    while next_percent_mark <= 1.0 and (downloaded / total_size) >= next_percent_mark:
                        next_percent_mark += 0.1
                else:
                    if emit_logs:
                        log(f"{tag} | {format_bytes(downloaded)} | {format_bytes(speed)}/s | ETA --:--", "PROG")
                    if progress_hook:
                        progress_hook(
                            {
                                "phase": "downloading",
                                "label": tag,
                                "downloaded": downloaded,
                                "total_size": 0,
                                "speed": speed,
                                "eta": None,
                                "pct": None,
                            }
                        )
                last_log_ts = now

        elapsed = max(0.001, time.time() - start_ts)
        avg_speed = downloaded / elapsed
        if progress_hook:
            progress_hook(
                {
                    "phase": "done",
                    "label": tag,
                    "downloaded": downloaded,
                    "total_size": total_size,
                    "speed": avg_speed,
                    "eta": 0.0,
                    "pct": 100.0 if total_size > 0 else None,
                }
            )
        if total_size > 0 and not logged_complete:
            if emit_logs:
                log(
                    f"{tag} | 100.0% | {format_bytes(downloaded)}/{format_bytes(total_size)} | "
                    f"{format_bytes(avg_speed)}/s | ETA 00:00",
                    "PROG",
                )
        elif total_size <= 0:
            if emit_logs:
                log(f"{tag} | {format_bytes(downloaded)} | {format_bytes(avg_speed)}/s | ETA 00:00", "PROG")


def run_one_task(
    appid: int, keyword: str, timeout: int, retries: int, only_get_link: bool, out_dir: Path, progress_hook=None
):
    opener = new_opener()
    result = {
        "keyword": keyword,
        "ok": False,
        "title": "",
        "url": "",
        "workshop_url": "",
        "file": "",
        "error": "",
    }
    try:
        search_text = clean_keyword(keyword)
        if not search_text:
            result["error"] = "Empty keyword"
            return result

        direct = None
        hit = None

        if appid:
            steam_item = find_first_steam_workshop_item(opener, appid, search_text, timeout, retries=retries)
            if steam_item:
                result["title"] = steam_item["Title"] or search_text
                result["workshop_url"] = steam_item.get("ItemUrl", "")
                hit = find_catalog_result_by_workshop_id(
                    opener,
                    steam_item["AppId"],
                    steam_item["ItemId"],
                    timeout,
                    retries=retries,
                )
                if hit:
                    result["title"] = hit["Title"] or result["title"]
                    direct = resolve_direct_download_url(
                        opener, hit["ModsLink"], hit["SearchUrl"], timeout, retries=retries
                    )

                if not direct:
                    direct = resolve_steamworkshopdownload_url(
                        opener,
                        steam_item["ItemUrl"],
                        steam_item["ItemId"],
                        steam_item["AppId"],
                        timeout,
                        retries=retries,
                    )

        if not direct:
            hit = find_exact_catalog_result(opener, search_text, timeout, appid=appid, retries=retries)
            if hit:
                result["title"] = hit["Title"] or result["title"] or search_text
                direct = resolve_direct_download_url(opener, hit["ModsLink"], hit["SearchUrl"], timeout, retries=retries)

        if not direct:
            result["error"] = "No exact match or direct URL"
            return result

        result["url"] = direct
        if only_get_link:
            result["ok"] = True
            return result

        out_dir.mkdir(parents=True, exist_ok=True)
        name = output_filename(direct, result["title"] or search_text)
        file_path = out_dir / name
        last_error = None
        for i in range(max(0, retries) + 1):
            try:
                download_file_with_progress(
                    opener=opener,
                    direct_url=direct,
                    file_path=file_path,
                    timeout=timeout,
                    label=result["title"] or search_text,
                    progress_hook=progress_hook,
                    emit_logs=progress_hook is None,
                )
                last_error = None
                break
            except Exception as e:
                last_error = e
                if i < retries:
                    time.sleep(1)
        if last_error:
            raise last_error
        result["file"] = str(file_path)
        result["ok"] = True
        return result
    except Exception as e:
        result["error"] = str(e)
        return result


def run_batch(selected_game, keywords, only_get_link, out_dir, timeout, retries, workers):
    appid = int(selected_game["AppId"]) if selected_game else None
    if selected_game:
        log(f"GAME: {selected_game['Game']} | AppId={appid} | Slug={selected_game.get('Slug', '')}", "GAME")
    else:
        log("MODE: Global search (all games)", "GAME")
    log(f"Tasks: {len(keywords)} | Workers: {workers} | Timeout: {timeout}s | Retries: {retries}", "INFO")
    log(f"提示：{EXACT_SEARCH_NOTICE}", "WARN")

    results = []
    progress_lock = threading.Lock()
    progress_state = {
        "total": len(keywords),
        "completed": 0,
        "success": 0,
        "failed": 0,
        "tasks": {},
        "offset": 0,
    }
    for kw in keywords:
        progress_state["tasks"][kw] = {
            "label": kw[:48],
            "phase": "queued",
            "downloaded": 0,
            "total_size": 0,
            "speed": 0.0,
            "eta": None,
            "updated_at": time.time(),
        }

    stop_event = threading.Event()
    reporter_meta = {"last_sig": "", "last_emit_ts": 0.0, "last_done": -1}

    def on_progress(kw, payload):
        with progress_lock:
            state = progress_state["tasks"].get(kw)
            if not state:
                return
            state["phase"] = payload.get("phase") or state["phase"]
            state["label"] = payload.get("label") or state["label"]
            state["downloaded"] = int(payload.get("downloaded") or 0)
            state["total_size"] = int(payload.get("total_size") or 0)
            state["speed"] = float(payload.get("speed") or 0.0)
            state["eta"] = payload.get("eta")
            state["updated_at"] = time.time()

    def render_batch_progress(force=False):
        with progress_lock:
            total = progress_state["total"]
            done = progress_state["completed"]
            ok = progress_state["success"]
            fail = progress_state["failed"]
            tasks = list(progress_state["tasks"].items())

            active = [(k, v) for k, v in tasks if v.get("phase") in {"start", "downloading"}]
            total_dl = sum(int(v.get("downloaded") or 0) for _, v in tasks)
            total_known = sum(int(v.get("total_size") or 0) for _, v in tasks if int(v.get("total_size") or 0) > 0)
            total_speed = sum(float(v.get("speed") or 0.0) for _, v in active)
            remain_known = max(0, total_known - total_dl)
            eta = remain_known / total_speed if total_speed > 1 and total_known > 0 else None
            done_pct = (done * 100.0 / total) if total else 100.0

            if not active:
                sig = f"{done}|{ok}|{fail}|none"
                now_ts = time.time()
                if (not force) and done == reporter_meta["last_done"]:
                    return
                reporter_meta["last_sig"] = sig
                reporter_meta["last_emit_ts"] = now_ts
                reporter_meta["last_done"] = done
                log(
                    f"总进度 {done}/{total}（{done_pct:5.1f}%） | 成功 {ok} 失败 {fail} | "
                    f"速度 {format_bytes(total_speed)}/s | 剩余 {format_duration(eta) if eta is not None else '--:--'}",
                    "BATCH",
                )
                if force:
                    log("Active: (none)", "BATCH")
                return

            active_sorted = sorted(active, key=lambda x: x[1].get("updated_at", 0), reverse=True)
            limit = 5
            count = len(active_sorted)
            if count > limit:
                offset = progress_state["offset"] % count
                rolled = active_sorted[offset:] + active_sorted[:offset]
                show = rolled[:limit]
                progress_state["offset"] = (progress_state["offset"] + limit) % count
            else:
                show = active_sorted

            sig_parts = [f"{done}|{ok}|{fail}|{len(active_sorted)}"]
            for kw, v in show:
                sig_parts.append(
                    f"{kw}|{int(v.get('downloaded') or 0)}|{int(v.get('total_size') or 0)}|{int(v.get('speed') or 0)}"
                )
            sig = ";".join(sig_parts)
            now_ts = time.time()
            if (not force) and sig == reporter_meta["last_sig"] and (now_ts - reporter_meta["last_emit_ts"] < 4.0):
                return
            reporter_meta["last_sig"] = sig
            reporter_meta["last_emit_ts"] = now_ts
            reporter_meta["last_done"] = done
            log(
                f"总进度 {done}/{total}（{done_pct:5.1f}%） | 成功 {ok} 失败 {fail} | "
                f"速度 {format_bytes(total_speed)}/s | 剩余 {format_duration(eta) if eta is not None else '--:--'}",
                "BATCH",
            )

            for kw, v in show:
                dl = int(v.get("downloaded") or 0)
                ts = int(v.get("total_size") or 0)
                spd = float(v.get("speed") or 0.0)
                if ts > 0:
                    pct = min(100.0, dl * 100.0 / ts)
                    eta_text = format_duration(v.get("eta")) if v.get("eta") is not None else "--:--"
                    log(
                        f"{(v.get('label') or kw)[:36]} | {pct:5.1f}% | {format_bytes(dl)}/{format_bytes(ts)} | "
                        f"{format_bytes(spd)}/s | ETA {eta_text}",
                        "ACTV",
                    )
                else:
                    log(
                        f"{(v.get('label') or kw)[:36]} | {format_bytes(dl)} | {format_bytes(spd)}/s | ETA --:--",
                        "ACTV",
                    )

    def progress_reporter():
        while not stop_event.wait(1.5):
            render_batch_progress(force=False)

    reporter_thread = None
    if (not only_get_link) and len(keywords) > 1:
        reporter_thread = threading.Thread(target=progress_reporter, daemon=True)
        reporter_thread.start()

    single_mode = len(keywords) == 1
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        def _task(kw):
            hook = (lambda payload, _kw=kw: on_progress(_kw, payload)) if (not only_get_link and len(keywords) > 1) else None
            return run_one_task(appid, kw, timeout, retries, only_get_link, out_dir, progress_hook=hook)

        future_map = {executor.submit(_task, kw): kw for kw in keywords}
        for future in concurrent.futures.as_completed(future_map):
            kw = future_map[future]
            res = future.result()
            results.append(res)
            with progress_lock:
                progress_state["completed"] += 1
                if res.get("ok"):
                    progress_state["success"] += 1
                    progress_state["tasks"][kw]["phase"] = "done"
                else:
                    progress_state["failed"] += 1
                    progress_state["tasks"][kw]["phase"] = "failed"
                progress_state["tasks"][kw]["updated_at"] = time.time()
            if res["ok"]:
                if single_mode and res.get("workshop_url"):
                    log(f"{kw} | Workshop: {res['workshop_url']}", "WORKSHOP")
                if only_get_link:
                    log(f"{kw} -> {res['url']}", "URL")
                else:
                    log(f"{kw} -> {res['file']}", "DONE")
            else:
                log(f"{kw} -> {res['error']}", "WARN")

    if reporter_thread:
        stop_event.set()
        reporter_thread.join(timeout=2.0)
        render_batch_progress(force=True)

    success = sum(1 for x in results if x["ok"])
    failed = len(results) - success
    log(f"Summary: success={success}, failed={failed}", "INFO")

    if not single_mode:
        out_dir.mkdir(parents=True, exist_ok=True)
        mapping_name = f"workshop_mapping_{time.strftime('%Y%m%d_%H%M%S')}.txt"
        mapping_path = out_dir / mapping_name
        with open(mapping_path, "w", encoding="utf-8") as f:
            f.write("keyword\tworkshop_url\ttitle\tdirect_url\tstatus\terror\n")
            for row in results:
                keyword = (row.get("keyword") or "").replace("\t", " ").replace("\n", " ").strip()
                workshop_url = (row.get("workshop_url") or "").replace("\t", " ").strip()
                title = (row.get("title") or "").replace("\t", " ").replace("\n", " ").strip()
                direct_url = (row.get("url") or "").replace("\t", " ").strip()
                status = "ok" if row.get("ok") else "failed"
                error = (row.get("error") or "").replace("\t", " ").replace("\n", " ").strip()
                f.write(f"{keyword}\t{workshop_url}\t{title}\t{direct_url}\t{status}\t{error}\n")
        log(f"Batch mapping saved: {mapping_path}", "INFO")

    return results


def split_game_names(game_name: str, aliases=None):
    aliases = aliases or []
    chinese_parts = re.findall(r"[\u4e00-\u9fff]+", game_name or "")
    chinese_name = " ".join(chinese_parts).strip()

    english_name = re.sub(r"[\u4e00-\u9fff]+", " ", game_name or "")
    english_name = re.sub(r"\s+", " ", english_name).strip()

    if not chinese_name:
        for a in aliases:
            c = re.findall(r"[\u4e00-\u9fff]+", a or "")
            if c:
                chinese_name = " ".join(c).strip()
                break

    if not english_name:
        english_name = game_name or ""

    return english_name, chinese_name


def _extract_cn_from_text(text: str):
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    # 优先提取括号中的中文名
    for m in re.finditer(r"[（(]([^()（）]{1,40})[）)]", text):
        candidate = m.group(1).strip()
        if re.search(r"[\u4e00-\u9fff]", candidate):
            candidate = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff·\- ]+", "", candidate).strip()
            if len(candidate) >= 2:
                return candidate
    # 其次提取纯中文片段
    parts = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    if parts:
        return parts[0]
    return ""


def _is_good_cn_name(candidate: str):
    if not candidate:
        return False
    c = candidate.strip()
    if len(c) < 2 or len(c) > 20:
        return False
    bad_terms = [
        "美国东部时间",
        "东部时间",
        "太平洋时间",
        "协调世界时",
        "维基百科",
        "百科",
        "官方网站",
        "官网",
        "Steam",
        "steam",
        "以下简称",
        "来源",
        "中文",
        "正好",
        "打到",
        "为什么",
        "事件",
        "教程",
        "攻略",
        "下载",
        "视频",
        "新闻",
    ]
    for w in bad_terms:
        if w in c:
            return False
    sentence_like = ["为什么", "如何", "怎么", "事件", "坍塌", "介绍", "攻略", "下载", "视频", "新闻", "问题", "可以", "支持", "包括"]
    if any(w in c for w in sentence_like):
        return False
    if re.search(r"[A-Za-z]{2,}", c):
        return False
    return bool(re.search(r"[\u4e00-\u9fff]", c))


def search_cn_name_from_web(opener, game_en: str, timeout: int, retries: int):
    if not game_en:
        return ""

    queries = [
        f"{game_en} 中文",
        f"\"{game_en}\" 中文",
        f"\"{game_en}\" 中文名 游戏",
    ]

    for q in queries:
        query = urllib.parse.quote(q)
        url = f"https://www.bing.com/search?q={query}&setlang=zh-hans"
        html_text = http_get(opener, url, timeout, default_headers(), retries=retries)
        chunks = []
        for m in re.finditer(r"<li class=\"b_algo\".*?</li>", html_text, re.I | re.S):
            block = m.group(0)
            plain = re.sub(r"<.*?>", " ", block)
            plain = html.unescape(re.sub(r"\s+", " ", plain)).strip()
            if plain:
                chunks.append(plain)
        for c in chunks[:8]:
            if game_en.lower() in c.lower():
                m1 = re.search(re.escape(game_en) + r".{0,20}[（(]([^()（）]{1,20})[）)]", c, re.I)
                if m1:
                    cn = m1.group(1).strip()
                    if _is_good_cn_name(cn):
                        return cn
                m2 = re.search(r"[（(]([^()（）]{1,20})[）)].{0,20}" + re.escape(game_en), c, re.I)
                if m2:
                    cn = m2.group(1).strip()
                    if _is_good_cn_name(cn):
                        return cn
    return ""


def translate_cn_fallback(opener, game_en: str, timeout: int, retries: int):
    if not game_en:
        return ""
    q = urllib.parse.quote(game_en)
    url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=zh-CN&dt=t&q={q}"
    try:
        raw = http_get(opener, url, timeout, default_headers(), retries=retries)
        data = json.loads(raw)
        if isinstance(data, list) and data and isinstance(data[0], list):
            text = "".join(x[0] for x in data[0] if isinstance(x, list) and x and x[0])
            text = text.strip()
            if _is_good_cn_name(text):
                return text
    except Exception:
        return ""
    return ""


def resolve_cn_name(opener, game_en: str, timeout: int, retries: int, cache_obj: dict):
    key = (game_en or "").strip().lower()
    if not key:
        return ""
    if key in cache_obj and _is_good_cn_name(cache_obj[key]):
        return cache_obj[key]

    cn = search_cn_name_from_web(opener, game_en, timeout, retries)
    if not _is_good_cn_name(cn):
        cn = translate_cn_fallback(opener, game_en, timeout, retries)
    cache_obj[key] = cn if _is_good_cn_name(cn) else ""
    return cache_obj[key]


def prefill_cn_cache(games, timeout: int, retries: int, workers: int = 8):
    cache_obj = load_name_cache()
    lock = threading.Lock()

    def _work(game_item):
        english_name, chinese_name = split_game_names(game_item.get("Game", ""), game_item.get("Aliases", []))
        key = english_name.strip().lower()
        if key and _is_good_cn_name(cache_obj.get(key, "")):
            return True
        if chinese_name:
            with lock:
                cache_obj[key] = chinese_name
            return True
        opener = new_opener()
        cn = resolve_cn_name(opener, english_name, timeout, retries, cache_obj={})
        with lock:
            cache_obj[key] = cn or ""
        return bool(cn)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = [executor.submit(_work, g) for g in games]
        done = 0
        ok = 0
        total = len(futures)
        for f in concurrent.futures.as_completed(futures):
            done += 1
            try:
                if f.result():
                    ok += 1
            except Exception:
                pass
            if done % 20 == 0 or done == total:
                log(f"Prefill progress: {done}/{total} (have_cn={ok})", "INFO")
                save_name_cache(cache_obj)

    save_name_cache(cache_obj)
    log(f"CN cache saved: {ZH_NAME_CACHE_PATH} (count={len(cache_obj)})", "OK")


def _match_game(item, search_text: str):
    if not search_text:
        return True

    query_has_cn = bool(re.search(r"[\u4e00-\u9fff]", search_text))
    q = search_text.strip().lower()

    english_name, chinese_name = split_game_names(item.get("Game", ""), item.get("Aliases", []))
    slug = urllib.parse.unquote(item.get("Slug", "")).lower()
    aliases = [str(a).lower() for a in item.get("Aliases", [])]

    if query_has_cn:
        target_cn = (chinese_name + " " + " ".join(item.get("Aliases", []))).strip()
        return search_text in target_cn

    english_blob = (english_name + " " + slug + " " + " ".join(aliases)).lower()
    if q in english_blob:
        return True

    english_tokens = re.split(r"[^a-z0-9]+", english_blob)
    english_tokens = [t for t in english_tokens if t]
    return any(token.startswith(q) for token in english_tokens)


def filter_games(games, search_text: str):
    return [g for g in games if _match_game(g, search_text)]


def interactive_pick_game(games, cfg):
    while True:
        game_kw = input("请输入游戏关键词筛选（中英文均可，留空=全局）: ").strip()
        if not game_kw:
            return None

        candidates = filter_games(games, game_kw)
        if not candidates:
            log("未找到匹配游戏，请重试", "WARN")
            continue

        print_games(
            candidates,
            limit=30,
            search="",
            timeout=cfg["timeout"],
            retries=cfg["retries"],
            auto_fill_cn=False,
        )
        app_text = input("请输入 AppId（R=重新搜索，回车=全局）: ").strip()
        if not app_text:
            return None
        if app_text.lower() == "r":
            continue
        if app_text.isdigit():
            return resolve_game(games, appid=int(app_text))
        log("AppId 输入无效，请重试", "WARN")


def print_games(games, limit=0, search="", timeout=25, retries=1, auto_fill_cn=True):
    sorted_games = sorted(games, key=lambda x: (x.get("Game", ""), int(x.get("AppId", 0))))
    if search:
        sorted_games = [x for x in sorted_games if _match_game(x, search)]
    if limit > 0:
        sorted_games = sorted_games[:limit]

    print(f"{'AppId':<8} {'Game':<45} 中文名")
    print(f"{'-'*8} {'-'*45} {'-'*20}")
    opener = new_opener() if auto_fill_cn else None
    name_cache = load_name_cache() if auto_fill_cn else {}
    for g in sorted_games:
        english_name, chinese_name = split_game_names(g.get("Game", ""), g.get("Aliases", []))
        if auto_fill_cn and not chinese_name:
            chinese_name = resolve_cn_name(opener, english_name, timeout, retries, name_cache)
        print(f"{g['AppId']:<8} {english_name:<45} {chinese_name}")
    if auto_fill_cn:
        save_name_cache(name_cache)


def show_banner():
    print(BANNER_ART)
    print("-" * 78)
    print("本程序仅用于学习交流，请遵守相关平台规则与法律。")
    print(f"提示：{EXACT_SEARCH_NOTICE}")
    print()


def menu_loop(cfg):
    while True:
        show_banner()
        print(f"当前下载目录: {cfg['download_dir']}")
        print(f"当前线程数: {cfg['workers']} | 超时: {cfg['timeout']}秒 | 重试: {cfg['retries']}次")
        print("1. 单条下载（可全局）")
        print("2. 单条仅解析直链（可全局）")
        print("3. 批量下载（可全局，文件一行一个关键词）")
        print("4. 批量仅解析直链（可全局）")
        print("5. 列出支持游戏")
        print("6. 刷新支持游戏缓存")
        print("7. 设置")
        print("8. 退出")
        choice = input("请输入选项编号: ").strip()

        if choice == "8":
            break

        try:
            if choice in {"1", "2", "3", "4"}:
                games = load_games(cfg["timeout"], cfg.get("refresh_games_cache", False), cfg["retries"])
                selected = interactive_pick_game(games, cfg)

                only_link = choice in {"2", "4"}
                if choice in {"1", "2"}:
                    keyword = input("请输入创意工坊项目关键词: ").strip()
                    keywords = get_keywords(keyword=keyword)
                else:
                    list_file = input("请输入项目关键词文件路径（每行一个关键词）: ").strip()
                    keywords = get_keywords(list_file=list_file)

                run_batch(
                    selected_game=selected,
                    keywords=keywords,
                    only_get_link=only_link,
                    out_dir=Path(cfg["download_dir"]),
                    timeout=int(cfg["timeout"]),
                    retries=int(cfg["retries"]),
                    workers=int(cfg["workers"]),
                )
                input("\n回车继续...")
            elif choice == "5":
                games = load_games(cfg["timeout"], cfg.get("refresh_games_cache", False), cfg["retries"])
                q = input("输入关键词筛选（中英文均可，留空显示全部）: ").strip()
                print_games(games, search=q, timeout=cfg["timeout"], retries=cfg["retries"], auto_fill_cn=True)
                input("\n回车继续...")
            elif choice == "6":
                fetch_supported_games(cfg["timeout"], retries=cfg["retries"])
                input("\n回车继续...")
            elif choice == "7":
                print("1) 下载目录  2) 线程数  3) 超时  4) 重试次数  5) 返回")
                sub = input("请选择设置项: ").strip()
                if sub == "1":
                    v = input("请输入下载目录（留空取消）: ").strip()
                    if v:
                        cfg["download_dir"] = v
                        save_config(cfg)
                elif sub == "2":
                    v = input("请输入线程数(1-16): ").strip()
                    if v.isdigit():
                        cfg["workers"] = max(1, min(16, int(v)))
                        save_config(cfg)
                elif sub == "3":
                    v = input("请输入超时秒数(5-180): ").strip()
                    if v.isdigit():
                        cfg["timeout"] = max(5, min(180, int(v)))
                        save_config(cfg)
                elif sub == "4":
                    v = input("请输入重试次数(0-10): ").strip()
                    if v.isdigit():
                        cfg["retries"] = max(0, min(10, int(v)))
                        save_config(cfg)
            else:
                log("无效选项", "WARN")
                time.sleep(1)
        except Exception as e:
            log(str(e), "ERR")
            input("\n回车继续...")


def build_arg_parser():
    parser = argparse.ArgumentParser(description="Steam workshop downloader via catalogue.smods.ru")
    parser.add_argument("--menu", action="store_true", help="Run interactive menu")
    parser.add_argument("--list-games", action="store_true", help="List supported games")
    parser.add_argument("--refresh-games-cache", action="store_true", help="Refresh games-cache.json")
    parser.add_argument("--game", help="Game name or slug")
    parser.add_argument("--appid", type=int, help="Steam AppId")
    parser.add_argument("--global-search", action="store_true", help="Search across all games")
    parser.add_argument("--keyword", help="Single search keyword")
    parser.add_argument("--list-file", help="Keyword list file, one keyword per line")
    parser.add_argument("--out-dir", help="Output directory")
    parser.add_argument("--workers", type=int, help="Download workers")
    parser.add_argument("--timeout", type=int, help="Request timeout seconds")
    parser.add_argument("--retries", type=int, help="Retry count for network failures")
    parser.add_argument("--search-games", help="Filter supported games by keyword (CN/EN)")
    parser.add_argument("--prefill-cn-cache", action="store_true", help="Prefill Chinese names for all games")
    parser.add_argument("--prefill-workers", type=int, default=8, help="Workers for CN cache prefill")
    parser.add_argument("--only-get-link", action="store_true", help="Resolve direct links only")
    parser.add_argument("--no-cn-fill", action="store_true", help="Disable web+translation CN-name fill for game list")
    parser.add_argument("--limit", type=int, default=0, help="Limit keyword count")
    return parser


def main():
    setup_console_utf8()
    first_run = ensure_data_dir_and_migrate()
    if first_run:
        log(f"已创建数据目录: {DATA_DIR}", "INFO")
    cfg = load_config()
    parser = build_arg_parser()
    args = parser.parse_args()

    if args.workers:
        cfg["workers"] = max(1, min(16, int(args.workers)))
    if args.timeout:
        cfg["timeout"] = max(5, min(180, int(args.timeout)))
    if args.retries is not None:
        cfg["retries"] = max(0, min(10, int(args.retries)))
    if args.out_dir:
        cfg["download_dir"] = args.out_dir

    has_action_args = any(
        [
            args.menu,
            args.list_games,
            args.refresh_games_cache,
            args.prefill_cn_cache,
            args.keyword,
            args.list_file,
            args.search_games,
            args.game,
            args.appid,
            args.global_search,
        ]
    )

    if args.menu or not has_action_args:
        menu_loop(cfg)
        return

    if args.list_games or args.search_games:
        games = load_games(cfg["timeout"], args.refresh_games_cache, cfg["retries"])
        print_games(
            games,
            search=args.search_games or "",
            timeout=cfg["timeout"],
            retries=cfg["retries"],
            auto_fill_cn=not args.no_cn_fill,
        )
        return

    if args.prefill_cn_cache:
        games = load_games(cfg["timeout"], args.refresh_games_cache, cfg["retries"])
        prefill_cn_cache(games, timeout=cfg["timeout"], retries=cfg["retries"], workers=max(1, args.prefill_workers))
        return

    if args.refresh_games_cache and not (args.keyword or args.list_file):
        load_games(cfg["timeout"], True, cfg["retries"])
        return

    keywords = get_keywords(keyword=args.keyword, list_file=args.list_file)
    if not keywords:
        raise ValueError("请提供 --keyword 或 --list-file")
    if args.limit and args.limit > 0:
        keywords = keywords[: args.limit]

    selected = None
    if not args.global_search:
        if args.game or args.appid:
            games = load_games(cfg["timeout"], args.refresh_games_cache, cfg["retries"])
            selected = resolve_game(games, game=args.game, appid=args.appid)
        else:
            log("未指定游戏，自动使用全局搜索", "INFO")

    run_batch(
        selected_game=selected,
        keywords=keywords,
        only_get_link=args.only_get_link,
        out_dir=Path(cfg["download_dir"]),
        timeout=int(cfg["timeout"]),
        retries=int(cfg["retries"]),
        workers=int(cfg["workers"]),
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("用户中断", "WARN")
        sys.exit(130)
    except Exception as ex:
        log(str(ex), "ERR")
        sys.exit(1)
