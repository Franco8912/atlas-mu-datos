"""Build the Atlas MU catalog from public PC launch listings."""
import argparse
import html
from datetime import date, datetime
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ARGENTINA = ZoneInfo("America/Argentina/Buenos_Aires")
USER_AGENT = "AtlasMU-Preview"
SOURCES = {
    "mu-online-list": ("MU Online List", "https://muonlinelist.com/"),
    "top-100": ("MU Online Top 100", "https://muonline-top100.com/"),
    "topg": ("TopG", "https://topg.org/mu-private-servers/new/"),
    "tuservermu": ("TuServerMU", "https://top.tuservermu.com/servers?lang=es"),
}
DETAIL_URLS = {
    "topg": re.compile(r"https://topg\.org/mu-private-servers/server-\d+/?"),
    "tuservermu": re.compile(r"https://top\.tuservermu\.com/server/[a-z0-9-]+"),
    "muonlinetop100": re.compile(r"https://www\.muonlinetop100\.com/server/[a-z0-9-]+"),
}
DOMAIN = re.compile(r"(?i)^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$")
DAY = re.compile(r"(?<!\d)(\d{2})\.(\d{2})\.(20\d{2})(?!\d)")
RATE = re.compile(r"(?i)\bx\s*(\d+)\b|\b(\d+)\s*x\b")
SEASON = re.compile(r"(?i)\b(?:season\s+\d+(?:\.\d+)?|\d{2}[a-z]–\d{2}[a-z])\b")

class VisibleText(HTMLParser):
    blocks = {"a", "article", "div", "h1", "h2", "h3", "h4", "header", "li",
              "main", "p", "section", "td", "th", "tr", "br", "span", "time"}

    def __init__(self):
        super().__init__()
        self.parts = []
        self.links = []
        self.suppressed = None

    def handle_starttag(self, tag, attrs):
        if tag == "a" and not self.suppressed:
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)
        if tag in {"script", "style", "template"}:
            self.suppressed = tag
        elif tag in self.blocks and not self.suppressed:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == self.suppressed:
            self.suppressed = None
        elif tag in self.blocks and not self.suppressed:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.suppressed:
            self.parts.append(data)

    def lines(self):
        return [" ".join(line.split()) for line in "".join(self.parts).splitlines()
                if line.strip()]

class TuServerCards(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cards = []
        self.next_page = None
        self.in_card = False
        self.in_rate = False
        self.rate = ""
        self.detail = None
        self.title = ""

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = (attrs.get("class") or "").split()
        if tag == "div" and "gt-upcoming-streaming-wrapper" in classes:
            self.in_card, self.in_rate = True, False
            self.rate, self.title, self.detail = "", "", None
        if tag == "i" and self.in_card and "fa-bolt" in classes:
            self.in_rate = True
        if tag != "a":
            return
        href = attrs.get("href") or ""
        if attrs.get("rel") == "next" and re.fullmatch(
                r"https://top\.tuservermu\.com/servers\?lang=es&page=[23]", href):
            self.next_page = href
        if self.in_card and DETAIL_URLS["tuservermu"].fullmatch(href):
            self.detail = href

    def handle_data(self, data):
        if self.in_rate:
            self.rate += data
        if self.detail:
            self.title += data

    def handle_endtag(self, tag):
        if tag == "li":
            self.in_rate = False
        if tag == "a" and self.detail:
            name = " ".join(self.title.split())
            rate = re.fullmatch(r"(?i)x?\s*(\d+)", self.rate.strip())
            if name:
                self.cards.append((name, f"x{rate[1]}" if rate else "", "", self.detail))
            self.in_card = False
            self.detail = None

def read_url(url, limit=2_000_000):
    with urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=20) as response:
        payload = response.read(limit + 1)
        if len(payload) > limit:
            raise ValueError("respuesta demasiado grande")
        return payload.decode(response.headers.get_content_charset() or "utf-8")

def robots_for(url):
    site = urlsplit(url)
    robots_url = f"{site.scheme}://{site.netloc}/robots.txt"
    rules = RobotFileParser()
    try:
        rules.parse(read_url(robots_url, 150_000).splitlines())
    except HTTPError as error:
        if error.code != 404:
            raise
        rules.parse([])
    return rules

def source_page(url, rules, parser=VisibleText):
    if not rules.can_fetch(USER_AGENT, url):
        raise ValueError("robots.txt limita la lectura automática")
    page = parser()
    page.feed(read_url(url))
    return page

def topg_pages(url, rules):
    details = {}
    for index_url, limit in ((url, 8), ("https://topg.org/mu-private-servers/", 12)):
        try:
            index = source_page(index_url, rules)
        except (OSError, ValueError) as error:
            print(f"TopG ({index_url}): {error}")
            continue
        links = dict.fromkeys(urljoin(index_url, href) for href in index.links)
        matches = [link.rstrip("/") for link in links if DETAIL_URLS["topg"].fullmatch(link)]
        details.update(dict.fromkeys(matches[:limit]))
    for detail in details:
        try:
            yield detail, source_page(detail, rules).lines()
        except (OSError, ValueError) as error:
            print(f"TopG ({detail}): {error}")

def extract_topg(pages):
    for detail, lines in pages:
        for position, line in enumerate(lines):
            if not re.match(r"(?i)^(website|sitio web)\b", line):
                continue
            site_lines = [line.split("|", 1)[-1].strip(), *lines[position + 1:position + 3]]
            domain = next((value for value in site_lines if DOMAIN.fullmatch(value)), None)
            if not domain:
                break
            tail = lines[position + 1:position + 32]
            start = next((i for i, value in enumerate(tail)
                          if re.match(r"(?i)^(type|tipo)\b", value)), None)
            if start is None:
                yield domain, "", "", detail
                break
            tags = []
            for tag in tail[start:start + 12]:
                if re.match(r"(?i)^(location|ubicación|share|rank)\b", tag):
                    break
                tags.append(tag)
            yield domain, " ".join(tags), "", detail
            break

def tuservermu_pages(url, rules):
    seen = set()
    while url and url not in seen:
        seen.add(url)
        try:
            page = source_page(url, rules, TuServerCards)
        except (OSError, ValueError) as error:
            print(f"TuServerMU ({url}): {error}")
            return
        yield from page.cards
        url = page.next_page

def day_from(text):
    match = DAY.search(text)
    if not match:
        return None
    day, month, year = map(int, match.groups())
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None

def extract_list(lines):
    section = None
    for position, line in enumerate(lines):
        lower = line.casefold()
        if lower.startswith(("opening soon", "within a week", "opening later")):
            section = "upcoming"
        elif lower.startswith(("opened recently", "opened within", "opened over")):
            section = "past"
        elif lower.startswith("mu online server list"):
            break
        if not section or not DAY.fullmatch(line) or position < 2:
            continue
        for width in (1, 2, 3):
            if position <= width:
                break
            details = " ".join(lines[position - width:position])
            name = lines[position - width - 1]
            if re.match(r"(?i)^x\d+", details) and SEASON.search(details) and not DAY.search(name):
                yield name, details, line, None
                break

def extract_top100(lines):
    in_list = False
    for position, line in enumerate(lines):
        lower = line.casefold()
        if lower.startswith("servers coming soon"):
            in_list = True
        elif lower.startswith(("today", "yesterday", "next 7 days", "version")) and in_list:
            break
        if not in_list or not DAY.match(line):
            continue
        words = line.split(maxsplit=1)
        name = words[1] if len(words) > 1 else lines[position + 1] if position + 1 < len(lines) else ""
        detail_offset = 1 if len(words) > 1 else 2
        details = " ".join(lines[position + detail_offset:position + detail_offset + 2])
        summary = re.match(r"(?i)^x\d+(?:\s+season\s+\d+(?:\.\d+)?)?", details)
        if DOMAIN.fullmatch(name) and summary:
            yield name, summary.group(), words[0], None

def name_key(name):
    return re.sub(r"[^a-z0-9]", "", name.casefold())

def project_key(name, domains, aliases):
    domain = name.casefold().removeprefix("www.")
    if DOMAIN.fullmatch(domain):
        return domains.get(domain, domain)
    return aliases.get(name_key(name), "nombre:" + name_key(name))

def build_catalog(previous, snapshots, day, verified_rates=None):
    projects = {item["id"]: item for item in previous["proyectos"]}
    domains = dict(previous.get("dominios", {}))
    aliases = dict(previous.get("alias", {}))
    before = set(projects)
    for source, lines in snapshots.items():
        named_projects = {}
        if source == "tuservermu":
            for item in projects.values():
                if item["tipo"] != "Privado":
                    continue
                names = {name_key(item["nombre"])}
                if DOMAIN.fullmatch(item["id"]):
                    names.add(name_key(item["id"].split(".")[0]))
                for name in names:
                    named_projects.setdefault(name, set()).add(item["id"])
        for name, details, date_text, detail in PARSERS[source](lines):
            opening = day_from(date_text)
            rates = sorted({int(first or second) for first, second in RATE.findall(details)})
            season_match = SEASON.search(details)
            key = project_key(name, domains, aliases)
            matches = named_projects.get(name_key(name), set())
            if source == "tuservermu" and key.startswith("nombre:") and len(matches) == 1:
                key = next(iter(matches))
            if key == "nombre:" or (source in {"mu-online-list", "top-100"} and (not opening or not rates)):
                continue
            if key not in projects:
                projects[key] = {"id": key, "nombre": name, "tipo": "Privado",
                                 "web": None,
                                 "opciones_exp": [], "aperturas": []}
            project = projects[key]
            project["opciones_exp"] = sorted(set(project["opciones_exp"]) | set(rates))
            project["fuentes"] = sorted(set(project.get("fuentes", [])) | {source})
            if project["tipo"] == "Privado" and detail and DETAIL_URLS[source].fullmatch(detail):
                project["web"] = detail
            if not opening:
                continue
            for rate in rates:
                identity = (opening, rate)
                launch = next((value for value in project["aperturas"]
                               if (value["fecha"], value["exp"]) == identity), None)
                if launch is None:
                    launch = {"fecha": opening, "exp": rate, "fuentes": []}
                    project["aperturas"].append(launch)
                if season_match:
                    seasons = set(launch.get("temporadas_publicadas", []))
                    seasons.add(season_match.group().title())
                    launch["temporadas_publicadas"] = sorted(seasons)
                launch["fuentes"] = sorted(set(launch["fuentes"]) | {source})
    for item in projects.values():
        rate_check = (verified_rates or {}).get(item["id"])
        if rate_check:
            item["opciones_exp"] = rate_check["opciones_exp"]
            item["fuente_exp"] = rate_check["fuente"]
        if item["tipo"] == "Privado" and not any(
                pattern.fullmatch(item.get("web") or "") for pattern in DETAIL_URLS.values()):
            item["web"] = next((SOURCES[source][1] for source in item.get("fuentes", [])
                                if source in SOURCES), None)
        for launch in item["aperturas"]:
            if launch.get("confirmada") is not True:
                launch["estado"] = "Anunciada" if launch["fecha"] >= day else "Fecha publicada pasada"
        item["aperturas"].sort(key=lambda launch: (launch["fecha"], launch["exp"] or 0))
    result = dict(previous)
    result["proyectos"] = sorted(projects.values(), key=lambda item: item["nombre"].casefold())
    result["fuentes"] = {key: {"nombre": value[0], "url": value[1]}
                         for key, value in SOURCES.items()}
    return result, sorted(set(projects) - before)

PARSERS = {"mu-online-list": extract_list, "top-100": extract_top100, "topg": extract_topg,
           "tuservermu": iter}

def make_index(catalog):
    rows = []
    for item in catalog["proyectos"]:
        title = html.escape(item["nombre"])
        rates = " · ".join(f"x{n}" for n in item["opciones_exp"])
        web = item.get("web")
        link = f'<p><a href="{html.escape(web, quote=True)}">Ver ficha</a></p>' if web else ""
        details = []
        if item.get("nota"):
            details.append(f"<p>{html.escape(item['nota'])}</p>")
        for launch in item["aperturas"]:
            label = date.fromisoformat(launch["fecha"]).strftime("%d/%m/%Y")
            exp = f" · x{launch['exp']}" if launch["exp"] else ""
            seasons = launch.get("temporadas_publicadas", [])
            season = f" · {html.escape(' / '.join(seasons))}" if seasons else ""
            details.append(f"<li>{label}{season}{exp} · {html.escape(launch['estado'])}</li>")
        if not details:
            details.append("<p>Sin fecha de apertura registrada.</p>")
        rows.append(f'<details><summary><strong>{title}</strong> · {html.escape(item["tipo"])}'
                    f'{(" · " + rates) if rates else ""}</summary>'
                    f'<ul>{"".join(value for value in details if value.startswith("<li>"))}</ul>'
                    f'{"".join(value for value in details if value.startswith("<p>"))}'
                    f'{link}</details>')
    stamp = html.escape(catalog["actualizado"])
    return f"""<!doctype html>
<html lang="es-AR"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Atlas MU · Listado para PC</title>
<style>
  :root {{ color-scheme: dark; font-family: system-ui,sans-serif; background:#17121b; color:#f5ede7; }}
  body {{ max-width:48rem; margin:2rem auto; padding:0 1rem; }}
  h1 {{ font-family:Georgia,serif; margin-bottom:.2rem; }}
  header p {{ color:#cbbcc8; }} a {{ color:#efc27f; }}
  details {{ background:#261d2a; border:1px solid #4b3c51; border-radius:.65rem; margin:.5rem 0; }}
  summary {{ padding:.85rem; cursor:pointer; overflow-wrap:anywhere; }}
  details p, details ul {{ margin:.15rem 1rem 1rem; }} ul:empty {{ display:none; }}
</style>
<header><h1>Atlas MU</h1><p>Listado general de MU para PC · Corte {stamp}</p></header>
<main aria-label="Proyectos de MU">{''.join(rows)}</main>
</html>"""

def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--salida", type=Path, default=HERE / "public")
    parser.add_argument("--anterior-url")
    parser.add_argument("--muestras", type=Path, help="carpeta local con los textos de la prueba")
    parser.add_argument("--fecha", help="fecha de corte AAAA-MM-DD para una prueba reproducible")
    args = parser.parse_args()
    base = json.loads((HERE / "data" / "base.json").read_text(encoding="utf-8"))
    previous = base
    if args.anterior_url:
        try:
            previous = json.loads(read_url(args.anterior_url))
            if previous.get("version") != 1 or not isinstance(previous.get("proyectos"), list):
                raise ValueError("formato inválido de la lista anterior")
            existing = {item["id"] for item in previous["proyectos"]}
            previous["proyectos"].extend(item for item in base["proyectos"] if item["id"] not in existing)
        except HTTPError as error:
            if error.code != 404:
                raise
    snapshots = {}
    for key, (name, url) in SOURCES.items():
        try:
            if args.muestras:
                if key == "topg":
                    records = [(None, path.read_text(encoding="utf-8").splitlines())
                               for path in sorted(args.muestras.glob("topg-*.txt"))]
                elif key == "tuservermu":
                    records = []
                    for path in sorted(args.muestras.glob("tuservermu*.html")):
                        page = TuServerCards()
                        page.feed(path.read_text(encoding="utf-8"))
                        records.extend(page.cards)
                else:
                    records = (args.muestras / (key + ".txt")).read_text(encoding="utf-8").splitlines()
            else:
                rules = robots_for(url)
                if key == "topg":
                    records = list(topg_pages(url, rules))
                elif key == "tuservermu":
                    records = list(tuservermu_pages(url, rules))
                else:
                    records = source_page(url, rules).lines()
            if not list(PARSERS[key](records)):
                raise ValueError("no se reconocieron fichas")
            snapshots[key] = records
        except (OSError, URLError, ValueError) as error:
            print(f"{name}: {error}")
    if not snapshots:
        raise SystemExit("Ninguna fuente respondió con datos válidos. Se conserva la lista publicada.")
    now = datetime.now(ARGENTINA)
    day = args.fecha or now.date().isoformat()
    catalog, added = build_catalog(previous, snapshots, day, base.get("exp_verificada"))
    catalog["actualizado"] = day
    catalog["fuentes_leidas"] = list(snapshots)
    args.salida.mkdir(parents=True, exist_ok=True)
    for name, content in (
        ("servidores.json", json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"),
        ("index.html", make_index(catalog)),
    ):
        temporary = args.salida / (name + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(args.salida / name)
    print(f"{len(catalog['proyectos'])} proyectos, {len(added)} nuevos, {len(snapshots)} fuentes leídas.")

if __name__ == "__main__":
    run()
