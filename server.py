"""MCP server para a Calculadora de Tributos RTC (CBS, IBS e Imposto Seletivo — LC 214/2025).

Envolve a API REST do projeto calculadora-rtc-regime-regular
(https://github.com/bispado/calculadora-rtc-regime-regular), expondo um conjunto
enxuto de ferramentas: cálculo de tributos, base de cálculo unificada e as
consultas às tabelas oficiais (CST, cClassTrib, NCM, NBS, alíquotas, municípios,
fundamentação legal e NFS-e).

Quando o Claude conecta, o servidor avisa no Windows e, se a API Java (local) estiver
parada, sobe a API sozinho. Quando o Claude desconecta, a API iniciada por ele é encerrada.

Run with:  python server.py    (stdio transport, suitable for Claude Code)
"""

from __future__ import annotations

import atexit
import glob
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
import uuid
from datetime import date
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import BaseModel, Field


HERE = Path(__file__).parent
# Instalado (executável do PyInstaller): <instalação>\mcp\calculadora-rtc-mcp.exe,
# com o Java em <instalação>\runtime e a API em <instalação>\api.
EMPACOTADO = bool(getattr(sys, "frozen", False))
APP_DIR = Path(sys.executable).parent if EMPACOTADO else HERE
RAIZ_INSTALACAO = APP_DIR.parent if EMPACOTADO else None
load_dotenv(APP_DIR / ".env")


def _flag(nome: str, padrao: bool) -> bool:
    valor = os.getenv(nome)
    if valor is None:
        return padrao
    return valor.strip().lower() not in ("0", "false", "no", "nao", "não", "off", "")


RTC_BASE_URL = os.getenv("RTC_BASE_URL", "http://localhost:8080/api").rstrip("/")
RTC_HTTP_TIMEOUT = float(os.getenv("RTC_HTTP_TIMEOUT", "60"))
RTC_MAX_RESULTS = int(os.getenv("RTC_MAX_RESULTS", "50"))

# Ciclo de vida da API Java
RTC_AUTOSTART = _flag("RTC_AUTOSTART", True)
RTC_STOP_ON_EXIT = _flag("RTC_STOP_ON_EXIT", True)
RTC_NOTIFY = _flag("RTC_NOTIFY", True)
RTC_STARTUP_TIMEOUT = float(os.getenv("RTC_STARTUP_TIMEOUT", "180"))
RTC_API_DIR = Path(
    os.getenv("RTC_API_DIR")
    or (RAIZ_INSTALACAO / "api" if RAIZ_INSTALACAO else HERE.parent / "calculadora-rtc-regime-regular")
)
RTC_HOME = Path(os.getenv("RTC_HOME") or (Path.home() / ".calculadora-rtc"))
API_LOG = RTC_HOME / "api.log"

CALC = f"{RTC_BASE_URL}/calculadora"
DADOS = f"{CALC}/dados-abertos"

logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="[calculadora-rtc] %(message)s")
log = logging.getLogger("calculadora-rtc")

mcp = FastMCP("calculadora-rtc")


# ------------------------------------------------------- AVISOS NO WINDOWS

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _notificar(titulo: str, mensagem: str) -> None:
    """Mostra um aviso (balão) na bandeja do Windows, sem bloquear o MCP."""
    log.info("%s: %s", titulo, mensagem)
    if not RTC_NOTIFY or os.name != "nt":
        return
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; "
        "$n = New-Object System.Windows.Forms.NotifyIcon; "
        "$n.Icon = [System.Drawing.SystemIcons]::Information; "
        "$n.BalloonTipTitle = $env:RTC_AVISO_TITULO; $n.BalloonTipText = $env:RTC_AVISO_TEXTO; "
        "$n.Visible = $true; $n.ShowBalloonTip(6000); Start-Sleep -Seconds 7; $n.Dispose()"
    )
    env = os.environ.copy()
    env["RTC_AVISO_TITULO"] = titulo
    env["RTC_AVISO_TEXTO"] = mensagem
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
            env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW,
        )
    except OSError as exc:
        log.warning("Não foi possível mostrar o aviso: %s", exc)


# ------------------------------------------------- CICLO DE VIDA DA API JAVA

def _url_local() -> bool:
    return (urlparse(RTC_BASE_URL).hostname or "") in ("localhost", "127.0.0.1", "::1")


def _encontrar_java() -> str | None:
    exe = "java.exe" if os.name == "nt" else "java"
    embutido = str(RAIZ_INSTALACAO / "runtime") if RAIZ_INSTALACAO else None
    for home in (os.getenv("RTC_JAVA_HOME"), embutido, os.getenv("JAVA_HOME")):
        if home and (Path(home) / "bin" / exe).exists():
            return str(Path(home) / "bin" / exe)
    if os.name == "nt":
        for padrao in (
            r"C:\Program Files\Eclipse Adoptium\jdk-2*\bin\java.exe",
            r"C:\Program Files\Microsoft\jdk-2*\bin\java.exe",
            r"C:\Program Files\Java\jdk-2*\bin\java.exe",
        ):
            achados = sorted(glob.glob(padrao), reverse=True)
            if achados:
                return achados[0]
    return shutil.which("java")


def _job_que_mata_ao_fechar() -> Any:
    """Windows: cria um Job Object que encerra os processos dele quando o MCP morre.

    Assim a API não fica órfã mesmo se o Claude matar o MCP à força.
    """
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class IoCounters(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class Basic(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD)]

    class Extended(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", Basic), ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]

    job = k32.CreateJobObjectW(None, None)
    if not job:
        return None
    info = Extended()
    info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
        return None
    return k32, job


class GerenciadorApi:
    """Sobe, acompanha e encerra a API Java local da calculadora."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._aviso_lock = threading.Lock()
        self.proc: subprocess.Popen | None = None
        self.estado = "verificando"
        self.erro: str | None = None
        self.iniciada_em: float | None = None
        self.pronta_em: float | None = None
        self._avisou_pronta = False
        self._job: Any = None

    def online(self) -> bool:
        try:
            return httpx.get(f"{DADOS}/versao", timeout=3).status_code < 500
        except httpx.HTTPError:
            return False

    def iniciada_por_este_mcp(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def garantir(self, esperar: bool = True) -> bool:
        """Garante a API no ar. Sobe a API se preciso; com `esperar`, aguarda ficar pronta."""
        with self._lock:
            if self.online():
                self.estado, self.erro = "online", None
                return True
            if not RTC_AUTOSTART or not _url_local():
                self.estado = "offline"
                self.erro = "API fora do ar e o início automático está desligado (RTC_AUTOSTART=0)." \
                    if not RTC_AUTOSTART else f"API remota fora do ar: {RTC_BASE_URL}"
                return False
            if not self.iniciada_por_este_mcp() and not self._iniciar():
                return False
        return self._aguardar() if esperar else False

    def _iniciar(self) -> bool:
        java = _encontrar_java()
        if not java:
            return self._falhou("Java 21+ não encontrado. Instale o JDK ou defina RTC_JAVA_HOME.")
        if not RTC_API_DIR.exists():
            return self._falhou(f"Pasta da API não encontrada: {RTC_API_DIR}. Defina RTC_API_DIR.")
        if not (RTC_API_DIR / "calculadora" / "db" / "calculadora-pro.db").exists():
            return self._falhou(
                "Banco da API não gerado. Na pasta da API rode: mvnw.cmd flyway:migrate "
                "\"-Dflyway.configFiles=flyway\\flyway-pro.conf\"")

        tmp = RTC_HOME / "tmp"
        tmp.mkdir(parents=True, exist_ok=True)
        porta = urlparse(RTC_BASE_URL).port or 8080
        # Windows: o Java cria um socket interno na pasta TEMP; com caminho longo dá
        # "Unable to establish loopback connection". Por isso uma pasta temporária curta.
        jvm = [f"-Djava.io.tmpdir={tmp}", f"-Djdk.net.unixdomain.tmpdir={tmp}",
               "-Djava.net.preferIPv4Stack=true"]
        porta_gestao = 9101 if porta == 8080 else porta + 1021  # padrão da API: 8080 -> 9101
        jar = next((j for j in (RTC_API_DIR / "api-regime-geral.jar",
                                RTC_API_DIR / "target" / "api-regime-geral.jar") if j.exists()), None)
        if jar:
            cmd = [java, *jvm, "-Dspring.profiles.active=offline", "-jar", str(jar),
                   f"--server.port={porta}", f"--management.server.port={porta_gestao}"]
        else:
            mvnw = RTC_API_DIR / ("mvnw.cmd" if os.name == "nt" else "mvnw")
            cmd = [str(mvnw), "spring-boot:run", "-Dspring-boot.run.profiles=offline",
                   f"-Dspring-boot.run.jvmArguments={' '.join(jvm)}",
                   f"-Dspring-boot.run.arguments=--server.port={porta},"
                   f"--management.server.port={porta_gestao}"]

        env = os.environ.copy()
        env["JAVA_HOME"] = str(Path(java).parent.parent)
        env["TEMP"] = env["TMP"] = str(tmp)
        flags = (subprocess.CREATE_NEW_PROCESS_GROUP | _NO_WINDOW) if os.name == "nt" else 0

        RTC_HOME.mkdir(parents=True, exist_ok=True)
        saida = open(API_LOG, "ab")
        saida.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} iniciando: {' '.join(cmd)}\n".encode())
        saida.flush()
        try:
            self.proc = subprocess.Popen(
                cmd, cwd=RTC_API_DIR, stdin=subprocess.DEVNULL, stdout=saida,
                stderr=subprocess.STDOUT, env=env, creationflags=flags,
            )
        except OSError as exc:
            return self._falhou(f"Não foi possível iniciar a API: {exc}")
        finally:
            saida.close()

        if RTC_STOP_ON_EXIT and os.name == "nt":
            try:
                self._job = self._job or _job_que_mata_ao_fechar()
                if self._job:
                    k32, job = self._job
                    k32.AssignProcessToJobObject(job, int(self.proc._handle))  # type: ignore[attr-defined]
            except Exception as exc:  # noqa: BLE001 - segue sem o job, com atexit
                log.warning("Sem vínculo de encerramento automático: %s", exc)

        self.estado, self.erro = "iniciando", None
        self.iniciada_em, self.pronta_em, self._avisou_pronta = time.time(), None, False
        log.info("API Java iniciada (PID %s). Log: %s", self.proc.pid, API_LOG)
        return True

    def _aguardar(self) -> bool:
        limite = time.time() + RTC_STARTUP_TIMEOUT
        while time.time() < limite:
            if self.online():
                self.estado, self.erro = "online", None
                with self._aviso_lock:
                    if not self._avisou_pronta and self.iniciada_em:
                        self._avisou_pronta = True
                        self.pronta_em = time.time()
                        _notificar("Calculadora RTC pronta",
                                   f"API Java no ar em {self.pronta_em - self.iniciada_em:.0f}s. "
                                   "O Claude já pode calcular tributos.")
                return True
            if self.proc is not None and self.proc.poll() is not None:
                return self._falhou(
                    f"A API Java encerrou na subida (código {self.proc.returncode}). Veja {API_LOG}.",
                    avisar=True)
            time.sleep(2)
        return self._falhou(f"A API não respondeu em {RTC_STARTUP_TIMEOUT:.0f}s. Veja {API_LOG}.",
                            avisar=True)

    def _falhou(self, motivo: str, avisar: bool = False) -> bool:
        self.estado, self.erro = "erro", motivo
        log.error(motivo)
        if avisar:
            _notificar("Calculadora RTC: falha na API", motivo)
        return False

    def parar(self) -> None:
        if not RTC_STOP_ON_EXIT or not self.iniciada_por_este_mcp():
            return
        log.info("Encerrando a API Java (PID %s).", self.proc.pid)
        try:
            self.proc.terminate()
            self.proc.wait(timeout=15)
        except Exception:  # noqa: BLE001
            try:
                self.proc.kill()
            except Exception:  # noqa: BLE001
                pass


api = GerenciadorApi()
atexit.register(api.parar)


# ------------------------------------------------------------------------ HTTP

def _hoje() -> str:
    return date.today().isoformat()


def _enviar(method: str, url: str, params: dict, json: Any) -> httpx.Response:
    with httpx.Client(timeout=RTC_HTTP_TIMEOUT) as client:
        return client.request(method, url, params=params, json=json)


def _request(method: str, url: str, *, params: dict | None = None, json: Any = None) -> Any:
    params = {k: v for k, v in (params or {}).items() if v is not None}
    try:
        try:
            resp = _enviar(method, url, params, json)
        except httpx.ConnectError:
            # API fora do ar: sobe (ou espera subir) e tenta de novo uma vez.
            if not api.garantir(esperar=True):
                raise ToolError(
                    f"A API da calculadora não está disponível em {RTC_BASE_URL}. {api.erro or ''} "
                    f"Log da API: {API_LOG}"
                ) from None
            resp = _enviar(method, url, params, json)
    except httpx.ConnectError as exc:
        raise ToolError(f"Não foi possível conectar à API da calculadora em {RTC_BASE_URL}.") from exc
    except httpx.TimeoutException as exc:
        raise ToolError(f"Tempo esgotado ao chamar {url}.") from exc

    if resp.status_code >= 400:
        detail: Any
        try:
            body = resp.json()
            detail = body.get("detail") or body.get("title") or body
            extra = body.get("errors") or body.get("erros")
            if extra:
                detail = f"{detail} | {extra}"
        except ValueError:
            detail = resp.text[:1000]
        raise ToolError(f"HTTP {resp.status_code}: {detail}")

    if not resp.content:
        return None
    try:
        return resp.json()
    except ValueError:
        return resp.text


def _get(url: str, **params: Any) -> Any:
    return _request("GET", url, params=params)


def _post(url: str, body: Any) -> Any:
    return _request("POST", url, json=body)


def _norm(texto: Any) -> str:
    s = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def _filtrar(itens: list[dict], busca: str | None, campos: list[str]) -> list[dict]:
    if not busca:
        return itens
    termos = _norm(busca).split()
    out = []
    for it in itens:
        alvo = " ".join(_norm(it.get(c)) for c in campos)
        if all(t in alvo for t in termos):
            out.append(it)
    return out


def _envelope(res: Any) -> Any:
    """Embrulha listas num objeto (o FastMCP divide listas cruas em vários blocos de texto)."""
    if isinstance(res, list):
        return {"total": len(res), "itens": res}
    return res


def _limitar(itens: list, limite: int | None) -> dict:
    limite = limite or RTC_MAX_RESULTS
    return {
        "total_encontrado": len(itens),
        "exibindo": min(len(itens), limite),
        "itens": itens[:limite],
    }


# ---------------------------------------------------------------- INPUT MODELS

class AliquotasImpostoSeletivo(BaseModel):
    adValorem: float | None = Field(None, description="Alíquota ad valorem do IS (%)")
    adRem: float | None = Field(None, description="Alíquota ad rem do IS (valor por unidade)")


class AliquotasNominais(BaseModel):
    cbs: float | None = Field(None, description="Alíquota nominal CBS (%), ex: 8.8")
    ibsEstadual: float | None = Field(None, description="Alíquota nominal IBS estadual (%)")
    ibsMunicipal: float | None = Field(None, description="Alíquota nominal IBS municipal (%)")
    impostoSeletivo: AliquotasImpostoSeletivo | None = None


class ComponentesBaseCalculo(BaseModel):
    """Componentes para a API calcular/validar a base de cálculo do item."""

    vProd: float | None = Field(None, description="Valor dos produtos/serviços")
    vFrete: float | None = None
    vSeg: float | None = None
    vOutro: float | None = Field(None, description="Outras despesas acessórias")
    vII: float | None = Field(None, description="Imposto de importação")
    vIS: float | None = Field(None, description="Imposto Seletivo")
    vDesc: float | None = Field(None, description="Desconto incondicional")
    vPIS: float | None = Field(None, description="PIS (vigente 2026)")
    vCOFINS: float | None = Field(None, description="COFINS (vigente 2026)")
    vICMS: float | None = Field(None, description="ICMS (2026-2032)")
    vICMSUFDest: float | None = None
    vFCP: float | None = None
    vFCPUFDest: float | None = None
    vICMSMono: float | None = None
    vISSQN: float | None = Field(None, description="ISSQN (2026-2032, só serviço)")


class ImpostoSeletivo(BaseModel):
    cst: str = Field(description="CST do Imposto Seletivo, ex: '000'")
    cClassTrib: str = Field(description="cClassTrib do Imposto Seletivo, ex: '000001'")
    baseCalculo: float = Field(description="Base de cálculo do IS")
    quantidade: float | None = None
    unidade: str | None = Field(None, description="Unidade de medida, ex: 'LT'")
    impostoInformado: float | None = Field(
        None, description="IS informado pelo contribuinte, para conferência (opcional)"
    )


class TributacaoRegular(BaseModel):
    cst: str
    cClassTrib: str


class CompraGovernamental(BaseModel):
    tpEnteGov: int = Field(
        description="1=União, 2=Estado, 3=Distrito Federal, 4=Município, "
        "5=Consórcio Público, 6=Comitê Gestor do IBS"
    )
    tpOperGov: int | None = Field(
        None,
        description="1=Fornecimento com pagamento posterior, 2=Recebimento do pagamento com "
        "fornecimento já realizado, 3=Fornecimento com pagamento já realizado, 4=Recebimento do "
        "pagamento com fornecimento posterior, 5=Fornecimento e pagamento concomitantes",
    )


class ItemOperacao(BaseModel):
    numero: int = Field(description="Número sequencial do item (1, 2, 3...)")
    cst: str = Field(description="Código de Situação Tributária CBS/IBS, ex: '000', '200'")
    cClassTrib: str = Field(description="Código de Classificação Tributária, 6 dígitos, ex: '000001'")
    ncm: str | None = Field(None, description="NCM sem pontos (mercadorias), ex: '10063021'")
    nbs: str | None = Field(None, description="NBS sem pontos (serviços), ex: '122011200'")
    baseCalculo: float | None = Field(
        None,
        description="Base de cálculo de CBS/IBS. Obrigatória, exceto quando há impostoSeletivo "
        "ou gComponentesBC (aí a API deriva a base).",
    )
    quantidade: float | None = None
    unidade: str | None = Field(None, description="Unidade de medida, ex: 'KG', 'UN', 'LT'")
    impostoSeletivo: ImpostoSeletivo | None = None
    tributacaoRegular: TributacaoRegular | None = None
    gComponentesBC: ComponentesBaseCalculo | None = None
    aliquotasNominais: AliquotasNominais | None = Field(
        None,
        description="Alíquotas nominais. Obrigatório para operações a partir de 2027 "
        "(ex: cbs 8.8, ibsEstadual 0.05, ibsMunicipal 0.05 no período de transição).",
    )


# ---------------------------------------------------------------------- CÁLCULO

@mcp.tool()
def calcular_tributos(
    municipio: int,
    itens: list[ItemOperacao],
    dh_fato_gerador: str | None = None,
    uf: str | None = None,
    tp_doc: int | None = None,
    compra_governamental: CompraGovernamental | None = None,
) -> Any:
    """Calcula CBS, IBS (estadual e municipal) e Imposto Seletivo de uma operação do regime geral.

    Usa o endpoint de observabilidade: cada item é calculado de forma independente e, se um item
    tiver erro de entrada, os demais ainda são calculados (o item com problema vem com
    estadoItem=INCONSISTENCIA_ENTRADA e a lista de erros). Use `explicar_erro` para detalhar um código.

    Dicas antes de calcular:
    - Descubra CST e cClassTrib com `buscar_classificacao_tributaria` / `listar_situacoes_tributarias`.
    - Confirme que a NCM/NBS é compatível com a cClassTrib via `validar_nomenclatura_aplicavel`.
    - O código do município (IBGE) sai de `listar_municipios`.

    Args:
        municipio: Código IBGE do município da operação (7 dígitos), ex: 4314902 (Porto Alegre).
        itens: Itens da operação.
        dh_fato_gerador: Data/hora do fato gerador ISO 8601 com fuso, ex: '2027-03-10T10:00:00-03:00'.
            Se omitido, usa agora.
        uf: Sigla da UF, ex: 'RS'.
        tp_doc: Modelo do DF-e de origem (55=NF-e, 65=NFC-e, ...).
        compra_governamental: Preencha apenas em compras governamentais.
    """
    from datetime import datetime

    body: dict[str, Any] = {
        "id": uuid.uuid4().hex,
        "versao": "1.0.0",
        "dhFatoGerador": dh_fato_gerador or datetime.now().astimezone().isoformat(timespec="seconds"),
        "municipio": municipio,
        "uf": uf,
        "tpDoc": tp_doc,
        "gCompraGov": compra_governamental.model_dump(exclude_none=True) if compra_governamental else None,
        "itens": [i.model_dump(exclude_none=True) for i in itens],
    }
    body = {k: v for k, v in body.items() if v is not None}
    return _post(f"{CALC}/observabilidade/regime-geral", body)


@mcp.tool()
def explicar_erro(codigo: str) -> Any:
    """Retorna a descrição de um código de erro devolvido pelo cálculo (ex: 'REG-011', 'CAL-001', 'VAL-001')."""
    return _get(f"{CALC}/observabilidade/erros", codigo=codigo)


@mcp.tool()
def calcular_base_calculo_unificada(
    ano_fato_gerador: int,
    natureza: Literal["bem", "servico"],
    tipo_documento: int = 55,
    vProd: float | None = None,
    vFrete: float | None = None,
    vSeg: float | None = None,
    vOutro: float | None = None,
    vII: float | None = None,
    vIS: float | None = None,
    vDesc: float | None = None,
    vPIS: float | None = None,
    vCOFINS: float | None = None,
    vICMS: float | None = None,
    vICMSUFDest: float | None = None,
    vFCP: float | None = None,
    vFCPUFDest: float | None = None,
    vICMSMono: float | None = None,
    vISSQN: float | None = None,
) -> Any:
    """Calcula a base de cálculo unificada de CBS/IBS da NF-e/NFC-e a partir dos componentes do item.

    Mostra o que soma e o que é deduzido (PIS/COFINS, ICMS, ISSQN etc. conforme o ano de transição).

    Args:
        ano_fato_gerador: Ano do fato gerador, ex: 2026.
        natureza: 'bem' ou 'servico'.
        tipo_documento: Modelo do documento (55=NF-e, 65=NFC-e).
        vProd..vISSQN: Valores dos componentes (informe só os que existirem).
    """
    componentes = {
        "vProd": vProd, "vFrete": vFrete, "vSeg": vSeg, "vOutro": vOutro, "vII": vII, "vIS": vIS,
        "vDesc": vDesc, "vPIS": vPIS, "vCOFINS": vCOFINS, "vICMS": vICMS,
        "vICMSUFDest": vICMSUFDest, "vFCP": vFCP, "vFCPUFDest": vFCPUFDest,
        "vICMSMono": vICMSMono, "vISSQN": vISSQN,
    }
    body = {
        "anoFatoGerador": ano_fato_gerador,
        "tipoDocumento": tipo_documento,
        "natureza": natureza.upper(),
        **{k: v for k, v in componentes.items() if v is not None},
    }
    return _post(f"{CALC}/base-calculo/base-calculo-unificada", body)


# -------------------------------------------------------- CST E CLASSIFICAÇÕES

@mcp.tool()
def listar_situacoes_tributarias(data: str | None = None, sigla_dfe: str | None = None) -> Any:
    """Lista os CSTs de CBS/IBS, cada um com as cClassTrib vinculadas (código e descrição).

    Bom ponto de partida para escolher CST + cClassTrib de uma operação.

    Args:
        data: Data do fato gerador (yyyy-MM-dd). Padrão: hoje.
        sigla_dfe: Filtra pelo DF-e (ex: 'NFE', 'NFCE', 'NFSE'). Veja `listar_tipos_dfe`.
    """
    return _envelope(
        _get(f"{DADOS}/situacoes-tributarias/cbs-ibs", data=data or _hoje(), siglaDfe=sigla_dfe)
    )


_CAMPOS_CLASSIF_RESUMO = [
    "codigo", "descricao", "tipoAliquota", "nomenclatura", "descricaoTratamentoTributario",
    "possuiPercentualReducao",
]


@mcp.tool()
def buscar_classificacao_tributaria(
    data: str | None = None,
    c_class_trib: str | None = None,
    cst: str | None = None,
    sigla_dfe: str | None = None,
    fornecedor: int | None = None,
    adquirente: int | None = None,
    busca: str | None = None,
    limite: int | None = None,
) -> Any:
    """Consulta classificações tributárias (cClassTrib) de CBS/IBS.

    Escolhe a consulta conforme os filtros informados:
    - c_class_trib (+ sigla_dfe opcional): detalhe completo de uma cClassTrib
      (tipo de alíquota, percentuais de redução, crédito, nomenclatura exigida etc.).
    - cst: todas as cClassTrib de um CST.
    - fornecedor/adquirente (ATOR_ID) e/ou sigla_dfe: cClassTrib aplicáveis aos atores/DF-e.
    - nenhum dos acima: lista geral; use `busca` para filtrar por texto
      (ex: 'medicamento', 'educação', 'alimentação humana').

    Args:
        data: Data do fato gerador (yyyy-MM-dd). Padrão: hoje.
        c_class_trib: Código da cClassTrib (6 dígitos).
        cst: Código do CST (3 dígitos).
        sigla_dfe: Sigla do DF-e (ex: 'NFE', 'NFCE', 'NFSE').
        fornecedor: ATOR_ID do fornecedor.
        adquirente: ATOR_ID do adquirente.
        busca: Texto para filtrar por código/descrição (listas).
        limite: Máximo de itens retornados em listas (padrão 50).
    """
    data = data or _hoje()
    base = f"{DADOS}/classificacoes-tributarias/cbs-ibs"

    if c_class_trib:
        if sigla_dfe:
            return _get(f"{base}/{sigla_dfe}/{c_class_trib}", data=data)
        return _get(f"{base}/class-trib/{c_class_trib}", data=data)

    if cst:
        res = _get(f"{base}/{cst}", data=data)
    elif fornecedor is not None or adquirente is not None or sigla_dfe:
        res = _get(f"{base}/por-atores", data=data, fornecedor=fornecedor,
                   adquirente=adquirente, siglaDfe=sigla_dfe)
    else:
        res = _get(base, data=data)

    if not isinstance(res, list):
        return res
    res = _filtrar(res, busca, ["codigo", "descricao", "descricaoTratamentoTributario"])
    resumo = [{k: it.get(k) for k in _CAMPOS_CLASSIF_RESUMO if k in it} for it in res]
    out = _limitar(resumo, limite)
    out["observacao"] = "Resumo. Para o detalhe de uma cClassTrib, chame novamente com c_class_trib."
    return out


@mcp.tool()
def validar_nomenclatura_aplicavel(
    c_class_trib: str,
    ncm: str | None = None,
    nbs: str | None = None,
    data: str | None = None,
) -> Any:
    """Valida se uma NCM (mercadoria) ou NBS (serviço) é compatível com a cClassTrib na data.

    Informe `ncm` OU `nbs`. Retorna `valido: true/false`. Evita o erro REG-011 no cálculo.
    """
    if bool(ncm) == bool(nbs):
        raise ToolError("Informe exatamente um entre `ncm` e `nbs`.")
    base = f"{DADOS}/classificacoes-tributarias"
    data = data or _hoje()
    if ncm:
        return _get(f"{base}/ncm-aplicavel", cClassTrib=c_class_trib, ncm=ncm,
                    dataOcorrenciaFatoGerador=data)
    return _get(f"{base}/nbs-aplicavel", cClassTrib=c_class_trib, nbs=nbs,
                dataOcorrenciaFatoGerador=data)


# ---------------------------------------------------------------- NCM / NBS

@mcp.tool()
def consultar_ncm(ncm: str, data: str | None = None) -> Any:
    """Consulta uma NCM (8 dígitos, sem pontos): descrição hierárquica e se é tributada pelo Imposto Seletivo."""
    return _get(f"{DADOS}/ncm", ncm=ncm, data=data or _hoje())


@mcp.tool()
def consultar_nbs(nbs: str, data: str | None = None) -> Any:
    """Consulta uma NBS (código de serviço, sem pontos): descrição e dados de tributação."""
    return _get(f"{DADOS}/nbs", nbs=nbs, data=data or _hoje())


# ---------------------------------------------------------------- ALÍQUOTAS

@mcp.tool()
def consultar_aliquotas_referencia(
    data: str | None = None,
    codigo_uf: int | None = None,
    codigo_municipio: int | None = None,
) -> Any:
    """Consulta as alíquotas padrão/de referência: CBS (União), IBS estadual (UF) e IBS municipal.

    Sempre consulta a da União; a da UF e a do município só se os códigos forem informados.
    Quando não houver alíquota cadastrada para a data, o item correspondente traz o erro.

    Args:
        data: Data (yyyy-MM-dd). Padrão: hoje.
        codigo_uf: Código IBGE da UF (2 dígitos), ex: 43 (RS). Veja `listar_ufs`.
        codigo_municipio: Código IBGE do município (7 dígitos). Veja `listar_municipios`.
    """
    data = data or _hoje()
    consultas: dict[str, tuple[str, dict]] = {
        "uniao_cbs": (f"{DADOS}/aliquota-uniao", {"data": data}),
    }
    if codigo_uf is not None:
        consultas["uf_ibs_estadual"] = (f"{DADOS}/aliquota-uf", {"codigoUf": codigo_uf, "data": data})
    if codigo_municipio is not None:
        consultas["municipio_ibs_municipal"] = (
            f"{DADOS}/aliquota-municipio", {"codigoMunicipio": codigo_municipio, "data": data}
        )
    out: dict[str, Any] = {}
    for nome, (url, params) in consultas.items():
        try:
            out[nome] = _get(url, **params)
        except ToolError as exc:
            out[nome] = {"erro": str(exc)}
    return out


# ------------------------------------------------------- UFs E MUNICÍPIOS

@mcp.tool()
def listar_ufs() -> Any:
    """Lista as UFs com sigla, nome e código IBGE."""
    return _envelope(_get(f"{DADOS}/ufs"))


@mcp.tool()
def listar_municipios(sigla_uf: str, busca: str | None = None, limite: int | None = None) -> Any:
    """Lista os municípios de uma UF com o código IBGE (usado no cálculo).

    Args:
        sigla_uf: Sigla da UF, ex: 'RS'.
        busca: Parte do nome para filtrar (ignora acentos), ex: 'porto alegre'.
        limite: Máximo de itens (padrão 50).
    """
    res = _get(f"{DADOS}/ufs/municipios", siglaUf=sigla_uf.upper())
    return _limitar(_filtrar(res, busca, ["nome", "codigo"]), limite)


# ------------------------------------------------------- FUNDAMENTAÇÃO LEGAL

@mcp.tool()
def consultar_fundamentacao_legal(
    data: str | None = None,
    c_class_trib: str | None = None,
    busca: str | None = None,
    limite: int | None = 10,
) -> Any:
    """Consulta a fundamentação legal (LC 214/2025) de cada cClassTrib.

    Informe `c_class_trib` para a base legal de uma classificação, ou `busca` para filtrar por texto.

    Args:
        data: Data (yyyy-MM-dd). Padrão: hoje.
        c_class_trib: Código da cClassTrib.
        busca: Texto livre (ex: 'medicamento', 'art. 138').
        limite: Máximo de itens (padrão 10; os textos legais são longos).
    """
    res = _get(f"{DADOS}/fundamentacoes-legais", data=data or _hoje())
    if c_class_trib:
        res = [r for r in res if r.get("codigoClassificacaoTributaria") == c_class_trib]
    res = _filtrar(res, busca, [
        "codigoClassificacaoTributaria", "descricaoClassificacaoTributaria",
        "texto", "textoCurto", "referenciaNormativa",
    ])
    return _limitar(res, limite)


# ---------------------------------------------------------------------- DF-e

@mcp.tool()
def listar_tipos_dfe(data: str | None = None) -> Any:
    """Lista os tipos de DF-e (NF-e, NFC-e, NFS-e...) com sigla e modelo, agrupados (mercadorias/serviços)."""
    return _envelope(_get(f"{DADOS}/dfe/grupos", data=data or _hoje()))


# ---------------------------------------------------------------------- NFS-e

@mcp.tool()
def nfse_classificacoes_por_nbs(nbs: str, data: str | None = None) -> Any:
    """NFS-e: lista os CSTs e cClassTrib aplicáveis a um serviço (código NBS, sem pontos)."""
    return _envelope(
        _get(f"{CALC}/nfse/situacoes-classificacoes-tributarias", nbs=nbs, data=data or _hoje())
    )


@mcp.tool()
def nfse_local_operacao(c_ind_op: str, data: str | None = None) -> Any:
    """NFS-e: indica o local da operação (onde o IBS é devido) a partir do Indicador de Operação.

    Args:
        c_ind_op: Código do Indicador de Operação (6 dígitos).
        data: Data do fato gerador (yyyy-MM-dd). Padrão: hoje.
    """
    return _envelope(_get(f"{CALC}/nfse/local-operacao", cIndOp=c_ind_op,
                          dataOcorrenciaFatoGerador=data or _hoje()))


# ---------------------------------------------------------------------- STATUS

@mcp.tool()
def status_conexao(iniciar_se_offline: bool = True) -> Any:
    """Mostra se está tudo conectado: o MCP ligado ao Claude, a API Java da calculadora
    (online, iniciando, offline ou erro), a versão do banco de dados e onde ver os logs.

    Use quando o usuário perguntar se a calculadora está funcionando, ou quando outra
    ferramenta falhar por conexão. Se a API estiver parada, ela é iniciada em segundo plano.

    Args:
        iniciar_se_offline: Se a API estiver parada, iniciar em segundo plano (padrão: sim).
    """
    online = api.online()
    if online:
        api.estado = "online"
    elif iniciar_se_offline and api.estado != "iniciando":
        threading.Thread(target=api.garantir, kwargs={"esperar": True}, daemon=True).start()
        time.sleep(0.5)

    if online:
        estado = "online"
    elif api.iniciada_por_este_mcp():
        estado = "iniciando"
    else:
        estado = api.estado
    out: dict[str, Any] = {
        "mcp": "conectado ao Claude",
        "api": estado,
        "api_url": RTC_BASE_URL,
        "inicio_automatico": RTC_AUTOSTART and _url_local(),
        "encerra_api_ao_sair": RTC_STOP_ON_EXIT,
        "api_iniciada_por_este_mcp": api.iniciada_por_este_mcp(),
    }
    if api.iniciada_por_este_mcp():
        out["api_pid"] = api.proc.pid
        if api.pronta_em and api.iniciada_em:
            out["api_subiu_em_segundos"] = round(api.pronta_em - api.iniciada_em, 1)
    if online:
        try:
            out["versao"] = _get(f"{DADOS}/versao")
        except ToolError as exc:
            out["versao"] = {"erro": str(exc)}
    elif estado == "iniciando" and api.iniciada_em:
        out["iniciando_ha_segundos"] = round(time.time() - api.iniciada_em)
        out["dica"] = "A API leva uns 15 a 40 segundos para subir. Consulte de novo em instantes."
    if api.erro:
        out["erro"] = api.erro
    out["log_api"] = str(API_LOG)
    return out


def _ao_conectar() -> None:
    if api.online():
        api.estado = "online"
        _notificar("Claude conectado à Calculadora RTC", "MCP ativo e API Java já está no ar.")
        return
    if RTC_AUTOSTART and _url_local():
        _notificar("Claude conectado à Calculadora RTC", "MCP ativo. Iniciando a API Java...")
    else:
        _notificar("Claude conectado à Calculadora RTC", "MCP ativo, mas a API está fora do ar.")
    api.garantir(esperar=True)


def main() -> None:
    if "--registrar" in sys.argv or "--remover-registro" in sys.argv:
        import registro
        sys.exit(registro.registrar() if "--registrar" in sys.argv else registro.remover_registro())

    log.info("MCP iniciado. API: %s | início automático: %s", RTC_BASE_URL, RTC_AUTOSTART)
    threading.Thread(target=_ao_conectar, daemon=True).start()
    try:
        mcp.run()
    finally:
        api.parar()


if __name__ == "__main__":
    main()
