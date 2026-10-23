"""Olheiro estadual: coleta as normas novas de uma UF com o coletor dela e faz um commit por norma.

Cada coletor de `scripts/estados/` é retomável (pula o .md que já existe). Aqui ele roda com o índice
refeito e, quando o coletor permite, limitado às normas mais recentes. Os coletores que varrem IDs
ou números até um teto fixo (CE, SC, MA) recebem uma janela logo acima do maior já publicado, tirado
dos nomes dos arquivos no git — sem isso nunca veriam norma nova.

Só os .md entram nos commits; o resto que o coletor mexe (_falhas.jsonl, índices) é descartado.

    python3 -I scripts/olheiro_estados.py SP [--minutos 45] [--commit]
"""
import argparse
import datetime as dt
import glob
import os
import re
import subprocess
import sys

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(SCRIPTS)
ESTADOS = os.path.join(SCRIPTS, "estados")
RECENTES = "500"
JANELA = 300  # IDs ou números sondados acima do maior conhecido
SAPL = ("AC", "AL", "AM", "PB", "PI", "RO", "RR", "TO")
# UF -> argumentos do coletor. None = calculado na hora (janela de IDs).
COLETORES = {
    **{uf: ["sapl.py", "baixar", uf, RECENTES, "--refazer"] for uf in SAPL},
    "AP": ["ap.py", "--refazer"],  # índice sem ordem por data: roda inteiro (o que existe é pulado sem rede)
    "BA": ["ba.py", "--refazer"],
    "MS": ["ms.py", "--refazer"],
    "MT": ["mt.py", "--refazer"],
    "PA": ["pa.py", "--refazer"],
    "RN": ["rn.py", "--refazer"],
    "DF": ["df.py", "--refazer", RECENTES],
    "GO": ["go.py", "--refazer", RECENTES],
    "PR": ["pr.py", "--refazer", RECENTES],
    "RS": ["rs.py", "--refazer", RECENTES],
    "SP": ["sp.py", "--refazer", RECENTES],
    "PE": ["pe.py", "--refazer", "200"],  # baixa antes de pular, e com 1 worker: janela menor
    "MG": ["mg.py", RECENTES],
    "RJ": ["rj.py", "200"],
    "ES": ["spl_agape.py", "ES", RECENTES],
    "SE": ["spl_agape.py", "SE", RECENTES],
    "CE": None,
    "SC": None,
    "MA": None,
}


def git(*args, verificar=True):
    return subprocess.run(["git", "-C", RAIZ, *args], check=verificar, capture_output=True, text=True)


def publicados(uf):
    return git("ls-files", "--", f"estaduais/{uf}").stdout.splitlines()


def janela(inicio):
    return ",".join(str(n) for n in range(inicio + 1, inicio + JANELA + 1))


def argumentos(uf, arquivos):
    if COLETORES[uf] is not None:
        return COLETORES[uf]
    if uf in ("CE", "SC"):
        ids = [int(m[1]) for a in arquivos if (m := re.search(r"-id(\d+)\.md$", a))]
        return [uf.lower() + ".py", janela(max(ids, default=0))]
    # MA: um teto por tipo (EC, LC, LEI); o arquivo começa por "<tipo>-<número>-"
    itens = []
    for prefixo in ("EC", "LC", "LEI"):
        nums = [int(m[1]) for a in arquivos if (m := re.search(rf"/{prefixo.lower()}-(\d+)-[^/]*\.md$", a))]
        topo = max(nums, default=0)
        itens += [f"{prefixo}_{n}" for n in range(topo + 1, topo + JANELA + 1)]
    return ["ma.py", ",".join(itens)]


def titulo(caminho):
    with open(os.path.join(RAIZ, caminho), encoding="utf-8") as f:
        m = re.search(r'^titulo:\s*"?(.*?)"?\s*$', f.read(4000), re.M)
    return m[1] if m else os.path.basename(caminho)


def commitar(uf, ativo):
    # -z: caminhos com acento saem crus, sem aspas nem escapes octais
    st = git("status", "--porcelain", "-z", "--untracked-files=all", "--", f"estaduais/{uf}").stdout.split("\0")
    feitos = 0
    for linha in filter(None, st):
        codigo, caminho = linha[:2], linha[3:]
        if not caminho.endswith(".md"):
            continue
        acao = "Acrescenta" if codigo == "??" else "Atualiza"
        msg = f"{acao} {titulo(caminho)} ({uf})"
        if ativo:
            git("add", "--sparse", "--", caminho)
            git("commit", "-q", "-m", msg)
        print("commit:" if ativo else "[simulação] commit:", msg, flush=True)
        feitos += 1
    # o que não é .md (falhas, índices regravados) não vai para o git
    git("checkout", "--", f"estaduais/{uf}", verificar=False)
    return feitos


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("uf", choices=sorted(COLETORES))
    ap.add_argument("--minutos", type=float, default=45)
    ap.add_argument("--commit", action="store_true")
    a = ap.parse_args()
    if a.uf in ("ES", "SE"):
        # o índice de ES/SE fica em cache por (tipo, ano) e não tem --refazer: os anos que ainda mudam saem do cache
        ano = dt.date.today().year
        for f in glob.glob(os.path.join(RAIZ, "estaduais", a.uf, "_indice", "anos", f"*-{ano}.json")) + \
                glob.glob(os.path.join(RAIZ, "estaduais", a.uf, "_indice", "anos", f"*-{ano - 1}.json")):
            os.remove(f)
    args = argumentos(a.uf, publicados(a.uf))
    print(f"[{a.uf}] coletor:", " ".join(args)[:200], flush=True)
    try:
        # sem -I: os coletores importam módulos vizinhos de scripts/estados/
        r = subprocess.run([sys.executable, os.path.join(ESTADOS, args[0]), *args[1:]], timeout=a.minutos * 60)
        codigo = r.returncode
    except subprocess.TimeoutExpired:
        print(f"[{a.uf}] tempo esgotado; grava o que já foi coletado", flush=True)
        codigo = 0
    feitos = commitar(a.uf, a.commit)
    print(f"[{a.uf}] normas gravadas: {feitos}; coletor terminou com código {codigo}", flush=True)
    return 1 if codigo and not feitos else 0


if __name__ == "__main__":
    sys.exit(main())
