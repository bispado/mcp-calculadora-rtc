"""Registra ou remove o MCP calculadora-rtc nas configurações do Claude.

- Claude Desktop: edita o claude_desktop_config.json, mantendo o resto do arquivo.
  Procura nas pastas de instalação conhecidas (instalador comum, Microsoft Store e
  a pasta Claude-Data das versões novas).
- Claude Code: usa `claude mcp add/remove`, se o comando existir.

Uso:  calculadora-rtc-mcp.exe --registrar | --remover-registro
      python server.py --registrar | --remover-registro   (modo desenvolvimento)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

NOME = "calculadora-rtc"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _comando_do_servidor() -> tuple[str, list[str]]:
    if getattr(sys, "frozen", False):
        return sys.executable, []
    return sys.executable, [str(Path(__file__).with_name("server.py"))]


def _abandonada(pasta: Path) -> bool:
    """O Claude deixa um marcador `.user-data-left.*` na pasta antiga quando muda os dados de lugar."""
    return any(pasta.glob(".user-data-left.*"))


def _configs_desktop() -> list[Path]:
    """Arquivos de configuração do Claude Desktop a atualizar (sem repetir e sem pastas abandonadas)."""
    candidatas: list[Path] = []
    appdata = os.getenv("APPDATA")
    local = os.getenv("LOCALAPPDATA")

    if local:
        candidatas += [p for p in sorted(Path(local).glob("Claude-Data/*")) if p.is_dir()]
        candidatas += [p for p in sorted(Path(local).glob("Packages/Claude_*/LocalCache/Roaming/Claude"))
                       if (p / "claude_desktop_config.json").exists()]
    if appdata and (Path(appdata) / "Claude").exists():
        candidatas.append(Path(appdata) / "Claude")

    achados: list[Path] = []
    vistos: set[str] = set()
    for pasta in candidatas:
        try:
            chave = str(pasta.resolve()).lower()
        except OSError:
            chave = str(pasta).lower()
        if chave in vistos or _abandonada(pasta):
            continue
        vistos.add(chave)
        achados.append(pasta / "claude_desktop_config.json")

    if not achados and appdata:
        # Nenhum Claude Desktop encontrado ainda: deixa registrado no local padrão,
        # para quando ele for instalado.
        achados.append(Path(appdata) / "Claude" / "claude_desktop_config.json")
    return achados


def _ler(caminho: Path) -> dict | None:
    if not caminho.exists() or not caminho.read_text(encoding="utf-8-sig").strip():
        return {}
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return None
    return dados if isinstance(dados, dict) else None


def _gravar(caminho: Path, dados: dict) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    backup = caminho.with_name(caminho.name + ".bak-calculadora-rtc")
    if caminho.exists() and not backup.exists():
        shutil.copy2(caminho, backup)
    temporario = caminho.with_name(caminho.name + ".tmp")
    temporario.write_text(json.dumps(dados, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporario, caminho)


def _claude_code(*args: str) -> str | None:
    claude = shutil.which("claude")
    if not claude:
        return None
    try:
        res = subprocess.run([claude, "mcp", *args], capture_output=True, text=True,
                             timeout=60, creationflags=_NO_WINDOW)
        return (res.stdout or res.stderr).strip().splitlines()[0] if (res.stdout or res.stderr) else "ok"
    except (OSError, subprocess.SubprocessError) as exc:
        return f"falhou: {exc}"


def registrar() -> int:
    comando, args = _comando_do_servidor()
    entrada = {"command": comando, "args": args, "env": {"PYTHONIOENCODING": "utf-8"}}
    print(f"Registrando o MCP '{NOME}': {comando} {' '.join(args)}".rstrip())
    for cfg in _configs_desktop():
        dados = _ler(cfg)
        if dados is None:
            print(f"  [ignorado] {cfg} não é um JSON válido; não foi alterado.")
            continue
        servidores = dados.setdefault("mcpServers", {})
        if not isinstance(servidores, dict):
            print(f"  [ignorado] {cfg}: 'mcpServers' inesperado; não foi alterado.")
            continue
        servidores[NOME] = entrada
        _gravar(cfg, dados)
        print(f"  [Claude Desktop] {cfg}")
    _claude_code("remove", NOME, "-s", "user")
    res = _claude_code("add", "--scope", "user", NOME, "--", comando, *args)
    print(f"  [Claude Code] {res or 'não encontrado (ignorado)'}")
    return 0


def remover_registro() -> int:
    print(f"Removendo o registro do MCP '{NOME}'")
    for cfg in _configs_desktop():
        dados = _ler(cfg)
        if not dados or not isinstance(dados.get("mcpServers"), dict) or NOME not in dados["mcpServers"]:
            continue
        del dados["mcpServers"][NOME]
        _gravar(cfg, dados)
        print(f"  [Claude Desktop] removido de {cfg}")
    res = _claude_code("remove", NOME, "-s", "user")
    print(f"  [Claude Code] {res or 'não encontrado (ignorado)'}")
    return 0
