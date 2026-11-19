"""Smoke test: sobe o servidor via stdio (como o Claude faz) e chama cada ferramenta.

Requer a API da calculadora rodando. Uso:  python smoke_test.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = Path(__file__).parent
DATA = "2027-03-10"

CASOS: list[tuple[str, dict]] = [
    ("listar_ufs", {}),
    ("listar_municipios", {"sigla_uf": "RS", "busca": "porto alegre"}),
    ("listar_tipos_dfe", {"data": DATA}),
    ("listar_situacoes_tributarias", {"data": DATA, "sigla_dfe": "NFE"}),
    ("buscar_classificacao_tributaria", {"data": DATA, "busca": "alimentacao humana", "limite": 5}),
    ("buscar_classificacao_tributaria", {"data": DATA, "c_class_trib": "200003"}),
    ("buscar_classificacao_tributaria", {"data": DATA, "cst": "200", "limite": 3}),
    ("validar_nomenclatura_aplicavel", {"c_class_trib": "200003", "ncm": "10063021", "data": DATA}),
    ("consultar_ncm", {"ncm": "22030000", "data": DATA}),
    ("consultar_nbs", {"nbs": "122011200", "data": DATA}),
    ("consultar_aliquotas_referencia", {"data": "2026-06-01", "codigo_uf": 43, "codigo_municipio": 4314902}),
    ("consultar_fundamentacao_legal", {"data": DATA, "c_class_trib": "200003"}),
    ("explicar_erro", {"codigo": "REG-011"}),
    ("nfse_classificacoes_por_nbs", {"nbs": "122011200", "data": DATA}),
    ("calcular_base_calculo_unificada", {
        "ano_fato_gerador": 2026, "natureza": "bem", "vProd": 1000, "vFrete": 50,
        "vDesc": 50, "vPIS": 9.25, "vCOFINS": 46.25, "vICMS": 180,
    }),
    ("calcular_tributos", {
        "municipio": 4314902, "uf": "RS", "dh_fato_gerador": "2027-03-10T10:00:00-03:00",
        "itens": [
            {"numero": 1, "ncm": "10063021", "cst": "200", "cClassTrib": "200003",
             "baseCalculo": 100.0, "quantidade": 20, "unidade": "KG",
             "aliquotasNominais": {"cbs": 8.8, "ibsEstadual": 0.05, "ibsMunicipal": 0.05}},
            {"numero": 2, "ncm": "02013000", "cst": "200", "cClassTrib": "200035",
             "baseCalculo": 80.0,
             "aliquotasNominais": {"cbs": 8.8, "ibsEstadual": 0.05, "ibsMunicipal": 0.05}},
        ],
    }),
]


async def main() -> int:
    params = StdioServerParameters(command=sys.executable, args=[str(HERE / "server.py")])
    falhas = 0
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        tools = await s.list_tools()
        print(f"{len(tools.tools)} ferramentas: {', '.join(t.name for t in tools.tools)}\n")
        for nome, args in CASOS:
            res = await s.call_tool(nome, args)
            texto = "".join(getattr(c, "text", "") for c in res.content)
            status = "ERRO" if res.isError else "ok"
            falhas += res.isError
            print(f"[{status}] {nome} {json.dumps(args, ensure_ascii=False)[:70]}")
            print("      " + texto.replace("\n", " ")[:220] + "\n")
    print(f"Falhas: {falhas}")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
