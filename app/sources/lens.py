import time
import httpx
from app.models import PatentResult, SumarioItem

LENS_API_URL = "https://api.lens.org/patent/search"

LENS_QUERIES = [
    {
        "id": "Q1_PT_CME_sistema",
        "desc": "CME + rastreabilidade/sistema (PT)",
        "str": '("central de material" OR "central de esterilização" OR "CME") AND ("rastreabilidade" OR "sistema de informação" OR "software" OR "gestão")',
        "fields": ["abstract", "title", "claim"],
    },
    {
        "id": "Q2_EN_CSSD_software",
        "desc": "CSSD/SPD management software (EN)",
        "str": '("central sterile supply department" OR "sterile processing department" OR "CSSD" OR "SPD") AND ("software" OR "information system" OR "traceability" OR "tracking")',
        "fields": ["abstract", "title", "claim"],
    },
    {
        "id": "Q3_EN_decision_support",
        "desc": "Sterile processing decision support (EN)",
        "str": '("sterile processing" OR "CSSD" OR "central sterile") AND ("decision support" OR "DSS" OR "quality management" OR "PDCA")',
        "fields": ["abstract", "title", "claim"],
    },
    {
        "id": "Q4_IPC_G16H",
        "desc": "IPC G16H – Informática em saúde + esterilização",
        "str": '"sterilization" OR "sterile processing" OR "CSSD"',
        "fields": ["abstract", "title"],
        "ipc_filter": "G16H",
    },
    {
        "id": "Q5_IPC_A61L",
        "desc": "IPC A61L2 – Esterilização + software",
        "str": '"software" OR "information system" OR "tracking" OR "management"',
        "fields": ["abstract", "title"],
        "ipc_filter": "A61L",
    },
    {
        "id": "Q6_EN_non_conformance",
        "desc": "Sterile processing non-conformance / quality control",
        "str": '("sterile processing" OR "CSSD") AND ("non-conformance" OR "quality control" OR "corrective action" OR "KPI")',
        "fields": ["abstract", "title", "claim"],
    },
]

INCLUDE_FIELDS = [
    "lens_id",
    "jurisdiction",
    "doc_number",
    "kind",
    "date_published",
    "biblio.publication_reference",
    "biblio.invention_title",
    "biblio.parties.applicants",
    "biblio.classifications_ipcr",
    "abstract",
]


def _build_payload(query: dict) -> dict:
    """
    Monta payload usando bool query com multi_match + filter de data.
    Para queries com IPC usa term em class_ipcr.symbol.
    """
    fields = query.get("fields", ["abstract", "title"])
    ipc_filter = query.get("ipc_filter")

    text_clause = {
        "multi_match": {
            "query": query["str"],
            "fields": fields,
            "type": "cross_fields",
            "operator": "or",
        }
    }

    must_clauses = [text_clause]

    if ipc_filter:
        must_clauses.append({
            "query_string": {
                "query": f"class_ipcr.symbol:{ipc_filter}*",
            }
        })

    payload = {
        "query": {
            "bool": {
                "must": must_clauses,
                "filter": [
                    {
                        "range": {
                            "date_published": {
                                "gte": "2000-01-01",
                                "lte": "2025-12-31",
                            }
                        }
                    }
                ],
            }
        },
        "size": 50,
        "sort": [{"date_published": "desc"}],
        "include": INCLUDE_FIELDS,
        "stemming": True,
    }

    return payload


def _extract_number(data: dict) -> str:
    try:
        jurisdiction = data.get("jurisdiction", "")
        doc_number = data.get("doc_number", "")
        kind = data.get("kind", "")
        return f"{jurisdiction} {doc_number} {kind}".strip()
    except Exception:
        return ""


def _extract_title(biblio: dict) -> str:
    try:
        titles = biblio.get("invention_title", [])
        if not titles:
            return ""
        for t in titles:
            if t.get("lang") == "en":
                return t.get("text", "")
        return titles[0].get("text", "")
    except Exception:
        return ""


def _extract_applicants(biblio: dict) -> str:
    try:
        applicants = biblio.get("parties", {}).get("applicants", [])
        names = []
        for a in applicants[:2]:
            name = a.get("extracted_name", {}).get("value", "")
            if name:
                names.append(name)
        return "; ".join(names)
    except Exception:
        return ""


def _extract_abstract(data: dict) -> str:
    try:
        abstracts = data.get("abstract", [])
        for a in abstracts:
            if a.get("lang") == "en":
                return a.get("text", "")[:400]
        if abstracts:
            return abstracts[0].get("text", "")[:400]
        return ""
    except Exception:
        return ""


def _extract_ipc(biblio: dict) -> str:
    try:
        ipcr = biblio.get("classifications_ipcr", {})
        classifications = ipcr.get("classifications", [])
        symbols = [c.get("symbol", "") for c in classifications[:4] if c.get("symbol")]
        return "; ".join(symbols)
    except Exception:
        return ""


def search_lens(token: str, query: dict) -> tuple[list[PatentResult], int]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = _build_payload(query)

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(LENS_API_URL, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return [], 0

    total = data.get("total", 0)
    hits = data.get("data", [])

    results = []
    for hit in hits:
        biblio = hit.get("biblio", {})
        result = PatentResult(
            query_id=query["id"],
            descricao=query["desc"],
            fonte="Lens.org",
            numero=_extract_number(hit),
            titulo=_extract_title(biblio),
            depositante=_extract_applicants(biblio),
            data_pub=hit.get("date_published", ""),
            jurisdicao=hit.get("jurisdiction", ""),
            ipc=_extract_ipc(biblio),
            resumo=_extract_abstract(hit),
            lens_id=hit.get("lens_id", ""),
        )
        results.append(result)

    time.sleep(1)
    return results, total
