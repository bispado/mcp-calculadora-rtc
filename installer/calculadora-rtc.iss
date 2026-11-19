; Instalador da Calculadora RTC para o Claude (MCP)
; Gerado por installer\build.ps1 — não compile direto sem rodar o build antes.

#define AppName "Calculadora RTC para o Claude"
#ifndef AppVersion
  #define AppVersion "0.2.0"
#endif
#define AppPublisher "Gustavo Bispo"
#define AppURL "https://github.com/bispado/mcp-calculadora-rtc"
#define ExeName "calculadora-rtc-mcp.exe"
#define Stage "build\stage"

[Setup]
AppId={{6F1E2B7C-3A9D-4C51-9E0B-7A2C4D8E1F30}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
DefaultDirName={localappdata}\Programs\Calculadora RTC
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir=output
OutputBaseFilename=CalculadoraRTC-Claude-Setup-{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\mcp\{#ExeName}
CloseApplications=yes
RestartApplications=no
LicenseFile=..\LICENSE
InfoAfterFile=LEIA-ME.txt

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Messages]
brazilianportuguese.WelcomeLabel2=Este assistente vai instalar a [name] no seu computador.%n%nEla permite que o Claude calcule CBS, IBS e Imposto Seletivo (Reforma Tributária — LC 214/2025) e consulte as tabelas oficiais (CST, cClassTrib, NCM, NBS, alíquotas).%n%nTudo o que é necessário já vem incluído: você não precisa instalar Java, Python nem nada mais.
brazilianportuguese.FinishedLabel=A instalação terminou.%n%nPróximo passo: feche o Claude Desktop por completo (clique com o botão direito no ícone do Claude perto do relógio e escolha "Sair") e abra de novo.%n%nDepois, no Claude, pergunte: "qual o status da calculadora?"

[Files]
Source: "{#Stage}\mcp\*"; DestDir: "{app}\mcp"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#Stage}\runtime\*"; DestDir: "{app}\runtime"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#Stage}\api\*"; DestDir: "{app}\api"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "LEIA-ME.txt"; DestDir: "{app}"; Flags: ignoreversion isreadme

[Run]
Filename: "{app}\mcp\{#ExeName}"; Parameters: "--registrar"; StatusMsg: "Conectando a calculadora ao Claude..."; Flags: runhidden waituntilterminated

[UninstallRun]
Filename: "{app}\mcp\{#ExeName}"; Parameters: "--remover-registro"; RunOnceId: "RemoverRegistro"; Flags: runhidden waituntilterminated

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
Type: filesandordirs; Name: "{%USERPROFILE}\.calculadora-rtc"

[Code]
function ClaudeAberto(): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec(ExpandConstant('{cmd}'), '/C tasklist /FI "IMAGENAME eq claude.exe" | find /I "claude.exe" >nul',
                 '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if WizardSilent() then
    Exit;
  while ClaudeAberto() do
  begin
    if MsgBox('O Claude está aberto.' + #13#10 + #13#10 +
              'Para conectar a calculadora, feche o Claude Desktop por completo: clique com o botão ' +
              'direito no ícone do Claude perto do relógio e escolha "Sair".' + #13#10 + #13#10 +
              'Clique em "Sim" depois de fechar, ou em "Não" para continuar assim mesmo.',
              mbConfirmation, MB_YESNO) = IDNO then
      Exit;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssDone) and ClaudeAberto() then
    MsgBox('O Claude Desktop está aberto.' + #13#10 + #13#10 +
           'Para a calculadora aparecer, feche o Claude por completo (botão direito no ícone ' +
           'perto do relógio > Sair) e abra de novo.', mbInformation, MB_OK);
end;
