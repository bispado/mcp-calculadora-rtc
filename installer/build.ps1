<#
.SYNOPSIS
  Gera o instalador da Calculadora RTC para o Claude (installer\output\*.exe).

.DESCRIPTION
  1. Gera o JAR da API (se não existir) e confere o banco gerado pelo Flyway.
  2. Cria um Java enxuto (jlink) só com os módulos que a API usa.
  3. Compila o MCP em executável (PyInstaller), sem precisar de Python na máquina do usuário.
  4. Monta a pasta de instalação e compila o instalador com o Inno Setup.

  Requisitos para gerar: JDK 21, Python com o .venv do projeto e Inno Setup 6.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File installer\build.ps1
  powershell -ExecutionPolicy Bypass -File installer\build.ps1 -ApiDir C:\src\calculadora-rtc-regime-regular -Version 0.3.0
#>
param(
  [string]$ApiDir = (Join-Path $PSScriptRoot "..\..\calculadora-rtc-regime-regular"),
  [string]$Version = "0.2.0",
  [string]$JdkHome = $env:JAVA_HOME
)
$ErrorActionPreference = "Stop"
$Root  = Resolve-Path (Join-Path $PSScriptRoot "..")
$Build = Join-Path $PSScriptRoot "build"
$Stage = Join-Path $Build "stage"
$ApiDir = Resolve-Path $ApiDir

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

# --- JDK
if (-not $JdkHome -or -not (Test-Path "$JdkHome\bin\jlink.exe")) {
  $JdkHome = Get-ChildItem "C:\Program Files\Eclipse Adoptium", "C:\Program Files\Microsoft", "C:\Program Files\Java" `
    -Directory -Filter "jdk-2*" -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1 -ExpandProperty FullName
}
if (-not $JdkHome) { throw "JDK 21 não encontrado. Instale (winget install EclipseAdoptium.Temurin.21.JDK) ou passe -JdkHome." }
$env:JAVA_HOME = $JdkHome
Write-Host "JDK: $JdkHome"

# --- Inno Setup
$Iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) { throw "Inno Setup 6 não encontrado. Instale: winget install JRSoftware.InnoSetup --scope user" }

# --- 1. API
Step "API Java"
$Jar = Join-Path $ApiDir "target\api-regime-geral.jar"
$Db  = Join-Path $ApiDir "calculadora\db\calculadora-pro.db"
if (-not (Test-Path $Db)) {
  New-Item -ItemType Directory -Force (Split-Path $Db) | Out-Null
  Push-Location $ApiDir
  & .\mvnw.cmd flyway:migrate "-Dflyway.configFiles=flyway\flyway-pro.conf" --batch-mode -q
  Pop-Location
}
if (-not (Test-Path $Jar)) {
  Push-Location $ApiDir
  & .\mvnw.cmd -DskipTests package --batch-mode -q
  Pop-Location
}
if (-not (Test-Path $Jar) -or -not (Test-Path $Db)) { throw "Falha ao gerar o JAR ou o banco da API." }

if (Test-Path $Stage) { Remove-Item $Stage -Recurse -Force }
New-Item -ItemType Directory -Force "$Stage\api\calculadora\db" | Out-Null
Copy-Item $Jar "$Stage\api\"
Copy-Item $Db  "$Stage\api\calculadora\db\"

# --- 2. Java enxuto
Step "Java enxuto (jlink)"
$Modules = "java.base,java.compiler,java.desktop,java.instrument,java.logging,java.management,java.naming," +
           "java.net.http,java.prefs,java.rmi,java.scripting,java.security.jgss,java.security.sasl,java.sql," +
           "java.transaction.xa,java.xml,jdk.crypto.ec,jdk.unsupported,jdk.zipfs,jdk.management," +
           "jdk.naming.dns,jdk.localedata,jdk.charsets"
& "$JdkHome\bin\jlink.exe" --add-modules $Modules --strip-debug --no-man-pages --no-header-files `
  --compress=zip-6 --output "$Stage\runtime"
if ($LASTEXITCODE -ne 0) { throw "jlink falhou." }

# --- 3. MCP em executável
Step "MCP em executável (PyInstaller)"
$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { throw "Crie o .venv do projeto: python -m venv .venv; .venv\Scripts\pip install -r requirements.txt" }
& $Py -m pip install -q -r (Join-Path $Root "requirements.txt") pyinstaller
Push-Location $Root
& $Py -m PyInstaller --noconfirm --clean --log-level ERROR --name calculadora-rtc-mcp --console --onedir `
  --collect-submodules mcp.server --collect-submodules mcp.shared --hidden-import registro `
  --distpath "$Build\dist" --workpath "$Build\work" --specpath "$Build\work" server.py
Pop-Location
if ($LASTEXITCODE -ne 0) { throw "PyInstaller falhou." }
Move-Item "$Build\dist\calculadora-rtc-mcp" "$Stage\mcp"

# --- 4. Instalador
Step "Instalador (Inno Setup)"
& $Iscc /Q "/DAppVersion=$Version" (Join-Path $PSScriptRoot "calculadora-rtc.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup falhou." }

$Out = Get-ChildItem (Join-Path $PSScriptRoot "output") -Filter "*$Version.exe" | Select-Object -First 1
Write-Host ("`nPronto: {0} ({1:N0} MB)" -f $Out.FullName, ($Out.Length / 1MB)) -ForegroundColor Green
