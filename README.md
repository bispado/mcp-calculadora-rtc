# mcp-calculadora-rtc

Servidor [MCP](https://modelcontextprotocol.io) para a **Calculadora de Tributos da Reforma Tributária do Consumo** (CBS, IBS e Imposto Seletivo — LC 214/2025).

Ele envolve a API REST do projeto [calculadora-rtc-regime-regular](https://github.com/bispado/calculadora-rtc-regime-regular) e permite que um assistente (Claude, por exemplo) calcule tributos e consulte as tabelas oficiais em vez de responder de memória:

> "Qual cClassTrib uso para venda de arroz? A NCM 10063021 é compatível? Calcule CBS e IBS de R$ 100 em Porto Alegre em março de 2027."

## Instalação fácil (Windows)

Para quem só quer usar, sem programar:

1. Baixe o **`CalculadoraRTC-Claude-Setup-<versão>.exe`** na página de [Releases](https://github.com/bispado/mcp-calculadora-rtc/releases).
2. Execute e clique em **Avançar** até concluir. Não precisa de administrador.
   - Se o Windows mostrar *"O Windows protegeu o computador"*, clique em **Mais informações** e depois em **Executar assim mesmo**. O instalador não tem assinatura digital paga.
3. Feche o Claude Desktop por completo (ícone perto do relógio → **Sair**) e abra de novo.
4. Pergunte ao Claude: *"qual o status da calculadora?"*

O instalador já traz **tudo**: o MCP compilado (sem Python), um Java próprio enxuto (sem instalar Java), a API e o banco de dados já gerado. Ele registra a calculadora no app do Claude e, se existir, no Claude Code. Para desinstalar, vá em **Configurações do Windows → Aplicativos**; a desinstalação remove também o registro no Claude.

> A calculadora não apareceu em **+ → Conectores**? Veja [Não aparece em Conectores?](#não-aparece-em-conectores).

### Gerar o instalador

Na máquina de desenvolvimento, com JDK 21, o `.venv` do projeto e o [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`winget install JRSoftware.InnoSetup --scope user`) instalados:

```powershell
powershell -ExecutionPolicy Bypass -File installer\build.ps1 -Version 0.2.0
```

O script gera o JAR e o banco da API, se faltarem, cria o Java enxuto com `jlink`, compila o MCP com PyInstaller e monta o instalador em `installer\output\`.

Para registrar ou remover manualmente:

```powershell
calculadora-rtc-mcp.exe --registrar
calculadora-rtc-mcp.exe --remover-registro
```

Em desenvolvimento, use `python server.py --registrar`.

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

## Requisitos (instalação manual, para desenvolvimento)

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

## Instalação manual (desenvolvimento)

```bash
git clone https://github.com/bispado/mcp-calculadora-rtc.git
cd mcp-calculadora-rtc
python -m venv .venv
# Windows
.venv\Scripts\pip install -r requirements.txt
# Linux/macOS
.venv/bin/pip install -r requirements.txt
```

### Registrar no Claude

O Claude guarda a lista de MCPs em **dois lugares diferentes**, e cada parte do Claude lê um deles:

| Onde | Quem lê | Como um MCP entra lá |
|---|---|---|
| `claude_desktop_config.json` | App do Claude: chat, menu **+ → Conectores** e aba Code | Pelo app (**Configurações → Desenvolvedor → Editar configuração**) ou editando o arquivo |
| `~/.claude.json` | Claude Code (terminal e aba Code do app) | `claude mcp add` |

Um MCP registrado só com `claude mcp add` funciona nas sessões do Claude Code, mas **não aparece em Conectores nem no chat comum do app**.

Por isso, o jeito recomendado é este comando, que registra nos dois lugares de uma vez:

```powershell
.venv\Scripts\python.exe server.py --registrar
```

Ele acha sozinho o arquivo certo do app. Esse arquivo muda de lugar conforme a instalação: `%APPDATA%\Claude\` no instalador comum, `%LOCALAPPDATA%\Claude-Data\...` nas versões novas ou a pasta da Microsoft Store. O comando também ignora pastas antigas que o Claude abandonou e mantém o resto do arquivo como está. Na primeira alteração, ele guarda um backup do arquivo original em `claude_desktop_config.json.bak-calculadora-rtc`.

Depois, **feche o Claude por completo** (ícone perto do relógio → **Sair**) e abra de novo. Para desfazer:

```powershell
.venv\Scripts\python.exe server.py --remover-registro
```

#### Alternativa: editar o arquivo do app à mão

Abra o arquivo pelo próprio app, em **Configurações → Desenvolvedor → Editar configuração**. Assim você abre o arquivo certo em qualquer tipo de instalação. Dentro de `mcpServers`, acrescente:

```json
"calculadora-rtc": {
  "command": "C:\\caminho\\mcp-calculadora-rtc\\.venv\\Scripts\\python.exe",
  "args": ["C:\\caminho\\mcp-calculadora-rtc\\server.py"],
  "env": { "PYTHONIOENCODING": "utf-8" }
}
```

Os caminhos são os da **sua** máquina, onde você criou o `.venv`. Não copie os caminhos de outra pessoa. Salve e reinicie o app.

#### Alternativa: só o Claude Code no terminal

Se você usa apenas o Claude Code pelo terminal:

```bash
claude mcp add --scope user calculadora-rtc -- <caminho>/.venv/Scripts/python.exe <caminho>/server.py
```

No Linux e no macOS, use `.venv/bin/python`. Lembre que, desse jeito, a calculadora **não** aparece no app do Claude.

### Configuração

Opcional: copie `.env.example` para `.env` e ajuste os valores.

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

## Não aparece em Conectores?

Se a calculadora funciona no Claude Code mas não aparece em **+ → Conectores** no app, ela está registrada só no cadastro do Claude Code, e não no do app (veja [Registrar no Claude](#registrar-no-claude)). As causas mais comuns:

| Causa | Como resolver |
|---|---|
| Foi registrada só com `claude mcp add` | Rode `server.py --registrar` (instalação manual) ou o instalador de novo |
| O Claude estava aberto durante a instalação e regravou o arquivo, apagando o registro | Feche o Claude (**Sair**) e rode o instalador de novo |
| O app do Claude foi instalado **depois** da calculadora | Rode o instalador de novo, com o Claude fechado |
| O app não foi reiniciado depois do registro | Feche por completo (**Sair**, e não só fechar a janela) e abra de novo |
| O arquivo do app está num local que o registro não conhece | Abra **Configurações → Desenvolvedor → Editar configuração** e acrescente a entrada à mão (veja [acima](#alternativa-editar-o-arquivo-do-app-à-mão)). No instalador, o executável fica em `%LOCALAPPDATA%\Programs\Calculadora RTC\mcp\calculadora-rtc-mcp.exe`, sem `args` |
| A empresa bloqueia MCPs locais por política | Fale com o administrador do Claude da sua organização |

Para conferir o que está registrado: no app, **Configurações → Desenvolvedor** lista os servidores locais e o estado de cada um; no terminal, use `claude mcp list`.

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
