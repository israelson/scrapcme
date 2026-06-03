import base64
import time
import httpx
from app.models import PatentResult

EPO_AUTH_URL = "https://ops.epo.org/3.2/auth/accesstoken"
EPO_SEARCH_URL = "https://ops.epo.org/3.2/rest-services/published-data/search/biblio"

EPO_QUERIES = [
    {
        "id": "EPO_Q1",
        "desc": "CSSD software traceability (CQL)",
        "cql": 'abs="central sterile supply" AND abs=software',
    },
    {
        "id": "EPO_Q2",
        "desc": "Sterilization instrument tracking system (CQL)",
        "cql": 'abs=sterilization AND abs="instrument tracking" AND abs=management',
    },
    {
        "id": "EPO_Q3",
        "desc": "IPC G16H + sterile processing (CQL)",
        "cql": "ic=G16H AND abs=sterilization",
    },
    {
        "id": "EPO_Q4",
        "desc": "IPC A61L2 + software/tracking (CQL)",
        "cql": "ic=A61L2 AND abs=software",
    },
]

_token_cache: dict = {"token": None, "expires_at": 0}


def get_epo_token(key: str, secret: str) -> str | None:
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"] - 60:
        return _token_cache["token"]

    credentials = base64.b64encode(f"{key}:{secret}".encode()).decode()
    headers = {
        "Authorization": f"Basic {credentials}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(
                EPO_AUTH_URL,
                headers=headers,
                content="grant_type=client_credentials",
            )
            resp.raise_for_status()
            data = resp.json()
            _token_cache["token"] = data["access_token"]
            _token_cache["expires_at"] = now + int(data.get("expires_in", 1200))
            return _token_cache["token"]
    except Exception:
        return None


def _ensure_token(key: str, secret: str) -> str | None:
    token = get_epo_token(key, secret)
    if not token:
        return None
    return token


def _parse_doc_ref(pub_ref: dict) -> str:
    try:
        doc_id = pub_ref.get("document-id", {})
        if isinstance(doc_id, list):
            doc_id = doc_id[0]
        country = doc_id.get("country", {})
        if isinstance(country, dict):
            country = country.get("$", "")
        doc_number = doc_id.get("doc-number", {})
        if isinstance(doc_number, dict):
            doc_number = doc_number.get("$", "")
        kind = doc_id.get("kind", {})
        if isinstance(kind, dict):
            kind = kind.get("$", "")
        return f"{country} {doc_number} {kind}".strip()
    except Exception:
        return ""


def _parse_title(exchange_doc: dict) -> str:
    try:
        biblio = exchange_doc.get("bibliographic-data", {})
        titles = biblio.get("invention-title", [])
        if isinstance(titles, dict):
            titles = [titles]
        for t in titles:
            if t.get("@lang") == "en":
                return t.get("$", "")
        if titles:
            return titles[0].get("$", "")
        return ""
    except Exception:
        return ""


def _parse_applicants(exchange_doc: dict) -> str:
    try:
        biblio = exchange_doc.get("bibliographic-data", {})
        parties = biblio.get("parties", {})
        applicants = parties.get("applicants", {}).get("applicant", [])
        if isinstance(applicants, dict):
            applicants = [applicants]
        names = []
        for a in applicants[:2]:
            name = a.get("applicant-name", {}).get("name", {})
            if isinstance(name, dict):
                name = name.get("$", "")
            if name:
                names.append(name)
        return "; ".join(names)
    except Exception:
        return ""


def _parse_date(exchange_doc: dict) -> str:
    try:
        biblio = exchange_doc.get("bibliographic-data", {})
        pub_ref = biblio.get("publication-reference", {})
        doc_id = pub_ref.get("document-id", {})
        if isinstance(doc_id, list):
            doc_id = doc_id[0]
        date = doc_id.get("date", {})
        if isinstance(date, dict):
            return date.get("$", "")
        return str(date)
    except Exception:
        return ""


def _parse_ipc(exchange_doc: dict) -> str:
    try:
        biblio = exchange_doc.get("bibliographic-data", {})
        ipc_data = biblio.get("classifications-ipcr", {}).get("classification-ipcr", [])
        if isinstance(ipc_data, dict):
            ipc_data = [ipc_data]
        symbols = []
        for ipc in ipc_data[:4]:
            text = ipc.get("text", {})
            if isinstance(text, dict):
                text = text.get("$", "")
            if text:
                symbols.append(text.strip())
        return "; ".join(symbols)
    except Exception:
        return ""


def search_epo(key: str, secret: str, query: dict) -> tuple[list[PatentResult], int]:
    token = _ensure_token(key, secret)
    if not token:
        return [], 0

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "X-OPS-Range": "1-25",
    }
    params = {"q": query["cql"]}

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.get(EPO_SEARCH_URL, headers=headers, params=params)
            if resp.status_code == 401:
                _token_cache["expires_at"] = 0
                token = _ensure_token(key, secret)
                if not token:
                    return [], 0
                headers["Authorization"] = f"Bearer {token}"
                resp = client.get(EPO_SEARCH_URL, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return [], 0

    try:
        world_data = data.get("ops:world-patent-data", {})
        biblio_search = world_data.get("ops:biblio-search", {})
        total_str = biblio_search.get("@total-result-count", "0")
        total = int(total_str)

        search_result = biblio_search.get("ops:search-result", {})
        exchange_docs = search_result.get("exchange-documents", {}).get(
            "exchange-document", []
        )
        if isinstance(exchange_docs, dict):
            exchange_docs = [exchange_docs]
    except Exception:
        return [], 0

    results = []
    for doc in exchange_docs:
        try:
            biblio = doc.get("bibliographic-data", {})
            pub_ref = biblio.get("publication-reference", {})
            numero = _parse_doc_ref(pub_ref)
            jurisdicao = ""
            try:
                doc_id = pub_ref.get("document-id", {})
                if isinstance(doc_id, list):
                    doc_id = doc_id[0]
                country = doc_id.get("country", {})
                if isinstance(country, dict):
                    jurisdicao = country.get("$", "")
                else:
                    jurisdicao = str(country)
            except Exception:
                pass

            result = PatentResult(
                query_id=query["id"],
                descricao=query["desc"],
                fonte="EPO OPS",
                numero=numero,
                titulo=_parse_title(doc),
                depositante=_parse_applicants(doc),
                data_pub=_parse_date(doc),
                jurisdicao=jurisdicao,
                ipc=_parse_ipc(doc),
                resumo="",
            )
            results.append(result)
        except Exception:
            continue

    time.sleep(1)
    return results, total
