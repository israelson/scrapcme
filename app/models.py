from pydantic import BaseModel


class SearchConfig(BaseModel):
    lens_token: str = ""
    epo_key: str = ""
    epo_secret: str = ""
    use_lens: bool = True
    use_epo: bool = True
    use_inpi: bool = True


class PatentResult(BaseModel):
    query_id: str
    descricao: str
    fonte: str
    numero: str
    titulo: str
    depositante: str
    data_pub: str
    jurisdicao: str
    ipc: str
    resumo: str
    lens_id: str = ""
    relevante: str = ""
    motivo_exclusao: str = ""


class SumarioItem(BaseModel):
    query_id: str
    descricao: str
    fonte: str
    string: str
    total: str
    coletado: int
    excluidos: str = "[preencher]"
    selecionados: str = "[preencher]"


class SearchSession(BaseModel):
    session_id: str
    config: SearchConfig
    running: bool = False
    done: bool = False
    progress: int = 0
    logs: list = []
    results: list[PatentResult] = []
    sumario: list[SumarioItem] = []
    error: str = ""
