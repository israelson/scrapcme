import time
import httpx
from app.models import PatentResult, SumarioItem

LENS_API_URL = "https://api.lens.org/patent/search"

LENS_QUERIES = [
    {
        "id": "Q1_PT_CME_sistema",
        "desc": "CME + rastreabilidade/sistema (PT)",
        "str": 'abstract:("central de material" OR "central de esterilização" OR "CME") AND abstract:("rastreabilidade" OR "sistema de informação" OR "software" OR "gestão")',
    },
    {
        "id": "Q2_EN_CSSD_software",
        "desc": "CSSD/SPD management software (EN)",
        "str": 'abstract:("central sterile supply department" OR "sterile processing department" OR "CSSD" OR "SPD") AND abstract:("software" OR "information system" OR "traceability" OR "tracking")',
    },
    {
        "id": "Q3_EN_decision_support",
        "desc": "Sterile processing decision support (EN)",
        "str": 'abstract:("sterile processing" OR "CSSD" OR "central sterile") AND abstract:("decision support" OR "DSS" OR "quality management" OR "PDCA")',
    },
    {
        "id": "Q4_IPC_G16H",
        "desc": "IPC G16H – Informática em saúde + esterilização",
        "str": 'classifications_ipcr.symbol:("G16H") AND abstract:("sterilization" OR "sterile processing" OR "CSSD")',
    },
    {
        "id": "Q5_IPC_A61L",
        "desc": "IPC A61L2 – Esterilização + software",
        "str": 'classifications_ipcr.symbol:("A61L 2" OR "A61L2") AND abstract:("software" OR "information system" OR "tracking" OR "management")',
    },
    {
        "id": "Q6_EN_non_conformance",
        "desc": "Sterile processing non-conformance / quality control",
        "str": 'abstract:("sterile processing" OR "CSSD") AND abstract:("non-conformance" OR "quality control" OR "corrective action" OR "KPI")',
    },
]


def _build_payload(query_str: str) -> dict:
    return {
        "query": {"query_string": {"query": query_str}},
        "size": 50,
        "sort": [{"date_published": "desc"}],
        "include": [
            "lens_id",
            "biblio.publication_reference",
            "biblio.invention_title",
            "biblio.parties.applicants",
            "abstract",
            "biblio.classifications_ipcr",
            "date_published",
            "jurisdiction",
        ],
        "filters": {
            "date_published": {"gte": "2000-01-01", "lte": "2025-12-31"}
        },
    }


def _extract_number(biblio: dict) -> str:
    try:
        ref = biblio.get("publication_reference", {})
        doc = ref.get("document_id", {})
        if isinstance(doc, list):
            doc = doc[0]
        jurisdiction = doc.get("country", "")
        doc_number = doc.get("doc_number", "")
        kind = doc.get("kind", "")
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
    payload = _build_payload(query["str"])

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(LENS_API_URL, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
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
            numero=_extract_number(biblio),
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
