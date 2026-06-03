import time
import requests
from bs4 import BeautifulSoup
from app.models import PatentResult

INPI_BASE = "https://busca.inpi.gov.br/pePI"

INPI_QUERIES = [
    {"id": "INPI_Q1", "desc": "CME + rastreabilidade", "str": "CME* RASTREAB*"},
    {"id": "INPI_Q2", "desc": "Esterilização + sistema/software", "str": "ESTERILIZ* SISTEM*"},
    {"id": "INPI_Q3", "desc": "Central esterilização + software", "str": "CENTRAL* ESTERILIZ* SOFTW*"},
    {"id": "INPI_Q4", "desc": "Esterilização + gestão processos", "str": "ESTERILIZ* GESTAO* PROCESS*"},
    {"id": "INPI_Q5", "desc": "Instrumental cirúrgico + rastreabilidade", "str": "INSTRUMENT* CIRURG* RASTREAB*"},
    {"id": "INPI_Q6", "desc": "Tomada de decisão + esterilização", "str": "DECISAO* HOSPITALAR* ESTERILIZ*"},
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Referer": f"{INPI_BASE}/servlet/LoginController?action=login",
}


def create_inpi_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    return session


def login_inpi(session: requests.Session) -> bool:
    try:
        session.get(f"{INPI_BASE}/", timeout=15)
        resp = session.get(
            f"{INPI_BASE}/servlet/LoginController",
            params={"action": "login"},
            timeout=15,
        )
        return resp.status_code == 200
    except Exception:
        return False


def _parse_results(html: str, query: dict) -> tuple[list[PatentResult], int, bool]:
    soup = BeautifulSoup(html, "lxml")
    results = []

    total = 0
    total_text = soup.get_text()
    for phrase in ["encontrados", "resultado", "registros"]:
        idx = total_text.lower().find(phrase)
        if idx != -1:
            fragment = total_text[max(0, idx - 30) : idx]
            for word in reversed(fragment.split()):
                cleaned = word.replace(".", "").replace(",", "")
                if cleaned.isdigit():
                    total = int(cleaned)
                    break
            break

    tables = soup.find_all("table")
    for table in tables:
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 3:
                continue
            texts = [c.get_text(strip=True) for c in cells]
            numero = texts[0] if len(texts) > 0 else ""
            titulo = texts[1] if len(texts) > 1 else ""
            depositante = texts[2] if len(texts) > 2 else ""
            data_pub = texts[3] if len(texts) > 3 else ""
            ipc = texts[4] if len(texts) > 4 else ""

            if not numero or not titulo:
                continue
            if numero.lower() in ("número", "pedido", "patente", "#"):
                continue

            result = PatentResult(
                query_id=query["id"],
                descricao=query["desc"],
                fonte="INPI pePI",
                numero=numero,
                titulo=titulo,
                depositante=depositante,
                data_pub=data_pub,
                jurisdicao="BR",
                ipc=ipc,
                resumo="",
            )
            results.append(result)

    has_next = bool(
        soup.find("a", string=lambda t: t and ("próxima" in t.lower() or "next" in t.lower() or ">>" in t))
    )
    return results, total, has_next


def _do_search(session: requests.Session, query: dict, page: int) -> requests.Response | None:
    params = {
        "Action": "BasicSearch",
        "CodTipoPesq": "PA",
        "Resumo": query["str"],
        "DataDe": "20000101",
        "DataAte": "20251231",
        "PaginaAtual": str(page),
        "MaxResults": "25",
    }
    try:
        resp = session.get(
            f"{INPI_BASE}/servlet/PatenteSearchBasico",
            params=params,
            timeout=20,
        )
        return resp
    except Exception:
        return None


def search_inpi(
    session: requests.Session, query: dict, log_fn=None
) -> tuple[list[PatentResult], int]:
    all_results: list[PatentResult] = []
    total = 0

    for page in range(1, 6):
        resp = _do_search(session, query, page)

        if resp is None:
            break

        if resp.status_code == 403 or (resp.history and "login" in resp.url.lower()):
            if log_fn:
                log_fn(f"INPI: sessão expirada na pág {page}, reconectando...")
            if login_inpi(session):
                resp = _do_search(session, query, page)
                if resp is None or resp.status_code != 200:
                    break
            else:
                break

        if resp.status_code != 200:
            break

        page_results, page_total, has_next = _parse_results(resp.text, query)

        if page == 1 and page_total > 0:
            total = page_total

        all_results.extend(page_results)

        if not page_results or not has_next:
            break

        time.sleep(2)

    time.sleep(3)
    return all_results, total
