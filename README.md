# mcp-calculadora-rtc

Servidor [MCP](https://modelcontextprotocol.io) para a **Calculadora de Tributos da Reforma Tributária do Consumo** (CBS, IBS e Imposto Seletivo — LC 214/2025).

Ele envolve a API REST do projeto [calculadora-rtc-regime-regular](https://github.com/bispado/calculadora-rtc-regime-regular) e permite que um assistente (Claude, por exemplo) calcule tributos e consulte as tabelas oficiais em vez de responder de memória:

> "Qual cClassTrib uso para venda de arroz? A NCM 10063021 é compatível? Calcule CBS e IBS de R$ 100 em Porto Alegre em março de 2027."

## Ferramentas

| Ferramenta | O que faz | Endpoint da API |
|---|---|---|
| `calcular_tributos` | Calcula CBS, IBS e IS de uma operação; erros por item sem interromper os demais | `POST /observabilidade/regime-geral` |
| `explicar_erro` | Descreve um código de erro do cálculo (ex: `REG-011`) | `GET /observabilidade/erros` |
| `calcular_base_calculo_unificada` | Base de cálculo unificada da NF-e/NFC-e a partir dos componentes | `POST /base-calculo/base-calculo-unificada` |
| `listar_situacoes_tributarias` | CSTs de CBS/IBS com as cClassTrib vinculadas | `GET /dados-abertos/situacoes-tributarias/cbs-ibs` |
| `buscar_classificacao_tributaria` | cClassTrib por código, CST, atores, DF-e ou busca textual | `GET /dados-abertos/classificacoes-tributarias/cbs-ibs/...` |
| `validar_nomenclatura_aplicavel` | Verifica se uma NCM/NBS é compatível com a cClassTrib | `.../ncm-aplicavel`, `.../nbs-aplicavel` |
| `consultar_ncm` | Descrição da NCM e se é tributada pelo IS | `GET /dados-abertos/ncm` |
| `consultar_nbs` | Descrição da NBS | `GET /dados-abertos/nbs` |
| `consultar_aliquotas_referencia` | Alíquotas de referência da União, UF e município | `GET /dados-abertos/aliquota-*` |
| `listar_ufs` | UFs com código IBGE | `GET /dados-abertos/ufs` |
| `listar_municipios` | Municípios de uma UF com código IBGE (com busca por nome) | `GET /dados-abertos/ufs/municipios` |
| `consultar_fundamentacao_legal` | Base legal de cada cClassTrib (com busca) | `GET /dados-abertos/fundamentacoes-legais` |
| `listar_tipos_dfe` | Tipos de DF-e (NF-e, NFC-e, NFS-e...) com sigla e modelo | `GET /dados-abertos/dfe/grupos` |
| `nfse_classificacoes_por_nbs` | CST e cClassTrib aplicáveis a um serviço (NFS-e) | `GET /nfse/situacoes-classificacoes-tributarias` |
| `nfse_local_operacao` | Local da operação da NFS-e pelo indicador de operação | `GET /nfse/local-operacao` |

Nas ferramentas com data, a data padrão é hoje. As listagens grandes (classificações e fundamentação legal) têm filtro `busca`, que ignora acentos, e limite de itens, para não estourar o contexto do modelo.

### O que ficou de fora (de propósito)

- Geração e validação de XML (`/xml/*`): payloads grandes e uso de sistema para sistema.
- `POST /regime-geral`: coberto pela versão com observabilidade.
- Endpoints `DEPRECATED` e `EXPERIMENTAL`, como a base unificada da NFS-e.
- Endpoints de nicho: pedágio, transferências a entes governamentais, redutores de compra governamental e a família do Imposto Seletivo (`/is`, `/imposto-seletivo`).
- `/versao/status` e `/dados-abertos/versao`, que são de monitoramento.

## Requisitos

- Python 3.10 ou superior.
- A API da calculadora rodando. Siga o README do [projeto original](https://github.com/bispado/calculadora-rtc-regime-regular): Java 21, geração do banco com Flyway e `spring-boot:run` com o perfil `offline`. Por padrão ela fica em `http://localhost:8080/api`.

> **Windows:** se a API cair na subida com `Unable to establish loopback connection`, aponte o diretório temporário do Java para um caminho curto antes de rodar:
> `$env:JAVA_TOOL_OPTIONS='-Djava.io.tmpdir=C:\jtmp -Djava.net.preferIPv4Stack=true'` (crie `C:\jtmp` antes).

## Instalação

```bash
git clone https://github.com/bispado/mcp-calculadora-rtc.git
cd mcp-calculadora-rtc
python -m venv .venv
# Windows
.venv\Scripts\pip install -r requirements.txt
# Linux/macOS
.venv/bin/pip install -r requirements.txt
```

Opcional: copie `.env.example` para `.env` e ajuste a URL da API.

| Variável | Padrão | Descrição |
|---|---|---|
| `RTC_BASE_URL` | `http://localhost:8080/api` | URL base da API |
| `RTC_HTTP_TIMEOUT` | `60` | Timeout em segundos |
| `RTC_MAX_RESULTS` | `50` | Máximo de itens nas listagens |

## Uso no Claude Code

```bash
claude mcp add calculadora-rtc -- <caminho>/.venv/Scripts/python.exe <caminho>/server.py
```

No Linux/macOS, use `.venv/bin/python`.

## Uso no Claude Desktop

Em `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "calculadora-rtc": {
      "command": "C:\\caminho\\mcp-calculadora-rtc\\.venv\\Scripts\\python.exe",
      "args": ["C:\\caminho\\mcp-calculadora-rtc\\server.py"],
      "env": { "RTC_BASE_URL": "http://localhost:8080/api" }
    }
  }
}
```

## Teste

Com a API no ar:

```bash
python smoke_test.py
```

O teste sobe o servidor via stdio, como um cliente MCP faria, e chama cada ferramenta.

## Aviso

Este é um projeto independente e não é oficial. Os resultados vêm da API da calculadora e servem para simulação e apoio. Confira sempre a legislação e as orientações oficiais.
