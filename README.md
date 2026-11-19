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
| `status_conexao` | Mostra se o MCP está conectado, o estado da API Java, a versão do banco e o log; sobe a API se estiver parada | `GET /dados-abertos/versao` |

Nas ferramentas com data, a data padrão é hoje. As listagens grandes (classificações e fundamentação legal) têm filtro `busca`, que ignora acentos, e limite de itens, para não estourar o contexto do modelo.

### O que ficou de fora (de propósito)

- Geração e validação de XML (`/xml/*`): payloads grandes e uso de sistema para sistema.
- `POST /regime-geral`: coberto pela versão com observabilidade.
- Endpoints `DEPRECATED` e `EXPERIMENTAL`, como a base unificada da NFS-e.
- Endpoints de nicho: pedágio, transferências a entes governamentais, redutores de compra governamental e a família do Imposto Seletivo (`/is`, `/imposto-seletivo`).
- `/versao/status` e `/dados-abertos/versao`, que são de monitoramento.

## Requisitos

- Python 3.10 ou superior.
- Java 21 ou superior.
- O projeto [calculadora-rtc-regime-regular](https://github.com/bispado/calculadora-rtc-regime-regular) clonado **ao lado** desta pasta (ou aponte `RTC_API_DIR` para ele), com o banco gerado pelo Flyway, conforme o README de lá.
- Recomendado: gerar o JAR da API uma vez, para ela subir mais rápido (cerca de 11 s, em vez de uns 40 s com `mvnw`):

  ```bash
  cd calculadora-rtc-regime-regular
  mvnw.cmd -DskipTests package
  ```

## Início automático da API

Você não precisa subir a API Java na mão. O ciclo é este:

1. **O Claude conecta no MCP.** Aparece um aviso no Windows: *"Claude conectado à Calculadora RTC"*.
2. **Se a API estiver parada, o MCP sobe a API em segundo plano.** Ele usa o JAR se existir, senão o `mvnw spring-boot:run` com o perfil `offline`. Quando a API fica pronta, aparece o aviso *"Calculadora RTC pronta"*. Se uma ferramenta for chamada antes disso, ela espera a API subir.
3. **O Claude fecha ou desconecta.** A API que o MCP iniciou é encerrada junto. No Windows, um Job Object garante isso até se o processo do MCP for morto à força, então a API nunca fica órfã ocupando a porta 8080.

Se a API já estiver no ar, iniciada por você ou por outra instância do MCP, ela é reaproveitada e não é encerrada.

Para ver o estado a qualquer momento, peça ao Claude *"qual o status da calculadora?"*. Ele chama `status_conexao`, que mostra a conexão, o estado da API (`online`, `iniciando`, `offline` ou `erro`), o PID, o tempo de subida, a versão do banco e o caminho do log.

A saída da API vai para `~/.calculadora-rtc/api.log`.

> O MCP já aplica a correção do erro `Unable to establish loopback connection` do Java no Windows: ele usa um diretório temporário curto, `~/.calculadora-rtc/tmp`.

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
| `RTC_AUTOSTART` | `1` | Sobe a API Java sozinho quando ela está parada (só para URL local) |
| `RTC_STOP_ON_EXIT` | `1` | Encerra a API iniciada pelo MCP quando o Claude desconecta |
| `RTC_NOTIFY` | `1` | Mostra avisos do Windows ao conectar, quando a API fica pronta e em caso de falha |
| `RTC_API_DIR` | `../calculadora-rtc-regime-regular` | Pasta do projeto da API |
| `RTC_JAVA_HOME` | detecção automática | JDK a usar (senão `JAVA_HOME`, as instalações em `Program Files` e o `PATH`) |
| `RTC_STARTUP_TIMEOUT` | `180` | Segundos de espera pela API subir |
| `RTC_HOME` | `~/.calculadora-rtc` | Pasta do log e do diretório temporário do Java |

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

```bash
python smoke_test.py
```

O teste sobe o servidor via stdio, como um cliente MCP faria, e chama cada ferramenta. Se a API estiver parada, o MCP a inicia e a encerra no final.

No Claude Desktop, o estado do servidor aparece em **Configurações → Desenvolvedor**, e o log do MCP fica em `mcp-server-calculadora-rtc.log`, na pasta de logs do Claude.

## Aviso

Este é um projeto independente e não é oficial. Os resultados vêm da API da calculadora e servem para simulação e apoio. Confira sempre a legislação e as orientações oficiais.

## Licença

Distribuído sob a licença MIT. Veja o arquivo [LICENSE](LICENSE).
