"""Olheiro: mantém o acervo federal em dia sozinho (roda todo dia no GitHub Actions).

1. Constituição: compara o SHA-256 do compilado do Planalto com `fonte/constituicao-compilado.json`;
   se mudou, grava o snapshot novo e regenera `constituicao.md` com `converter_constituicao.py`.
2. Normas novas: o índice do Senado dos dois últimos anos é refeito e o que falta é baixado.
3. Alterações: rechecagem rotativa dos metadados no normas.leg.br. Quando o SHA-256 muda, o .md é
   regenerado e só fica gravado se o texto ou os campos que importam mudaram — sem commit de ruído.
   Normas citadas na ementa das novas ("Altera a Lei nº ...") passam na frente da fila por 30 dias,
   porque o texto compilado costuma demorar alguns dias para sair.

Cada mudança vira um commit próprio. O estado (SHA e data da última checagem) fica em
`federal/_indice/olheiro.json`, fora do git, guardado pelo cache do Actions; se sumir, é refeito.

    python3 -I scripts/olheiro.py [--checar 6000] [--minutos 300] [--rps 3] [--commit]
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import baixar_federal as bf  # noqa: E402

RAIZ_REPO = os.path.dirname(bf.RAIZ)
SCRIPTS = os.path.dirname(os.path.abspath(__file__))
ESTADO = os.path.join(bf.RAIZ, "_indice", "olheiro.json")
CONSTITUICAO_META = os.path.join(RAIZ_REPO, "fonte", "constituicao-compilado.json")
CONSTITUICAO_HTM = os.path.join(RAIZ_REPO, "fonte", "constituicao-compilado.htm")
CAMPOS = ("titulo", "tipo", "numero", "data", "ementa", "revogada", "versao_texto", "urn")
DIAS_PRIORIDADE = 30
# "Lei nº 8.078, de 11 de setembro de 1990", "Lei Complementar nº 101, de 2000", "Decreto-Lei nº 2.848"
CITACAO = re.compile(r"(Lei Complementar|Decreto-Lei|Lei)\s+n[ºo°.]*\s*([\d.]+)(?:,?\s+de\s+[^,;]*?(\d{4}))?", re.I)
PREFIXO_CITACAO = {"lei": "lei", "lei complementar": "lcp", "decreto-lei": "del"}
HOJE = dt.date.today().isoformat()
TRAVA = threading.Lock()
PARAR = threading.Event()


def git(*args, verificar=True):
    return subprocess.run(["git", "-C", RAIZ_REPO, *args], check=verificar, capture_output=True, text=True)


def commit(caminhos, mensagem, ativo):
    if not ativo:
        print("[simulação] commit:", mensagem)
        return
    git("add", "--sparse", "--", *caminhos)
    if git("diff", "--cached", "--quiet", verificar=False).returncode:
        git("commit", "-q", "-m", mensagem)
        print("commit:", mensagem, flush=True)


def relevante(caminho):
    """O que importa comparar: campos estáveis do cabeçalho + corpo. Ignora baixado_em e hashes."""
    texto = open(caminho, encoding="utf-8").read()
    partes = texto.split("---", 2)
    if len(partes) != 3:
        return texto
    campos = [l for l in partes[1].splitlines() if l.split(":", 1)[0] in CAMPOS]
    corpo = "\n".join(l.rstrip() for l in partes[2].strip().splitlines())
    return "\n".join(campos) + "\n" + corpo


def sha_do_cabecalho(caminho):
    with open(caminho, encoding="utf-8") as f:
        cab = f.read(4000)
    m = re.search(r'^sha256_metadados_fonte:\s*"?([0-9a-f]{64})', cab, re.M)
    return m[1] if m else None


# --- 1. Constituição ------------------------------------------------------------------------------

def constituicao(ativo):
    meta = json.load(open(CONSTITUICAO_META, encoding="utf-8"))
    req = urllib.request.Request(meta["url"], headers={"User-Agent": bf.UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        bruto = r.read()
    sha = hashlib.sha256(bruto).hexdigest()
    if sha == meta["sha256"]:
        print("Constituição sem mudança")
        return True
    backup = (open(CONSTITUICAO_HTM, "rb").read(), open(CONSTITUICAO_META, "rb").read())
    open(CONSTITUICAO_HTM, "wb").write(bruto)
    meta.update(sha256=sha, obtido_em=HOJE)
    with open(CONSTITUICAO_META, "w", encoding="utf-8") as f:
        f.write(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
    r = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "converter_constituicao.py")],
                       capture_output=True, text=True)
    if r.returncode:
        # o conversor rejeitou o snapshot novo: volta ao anterior e avisa, sem publicar texto quebrado
        open(CONSTITUICAO_HTM, "wb").write(backup[0])
        open(CONSTITUICAO_META, "wb").write(backup[1])
        print("::warning::Constituição mudou no Planalto, mas o conversor falhou:", r.stderr[-500:])
        return False
    commit(["constituicao.md", "fonte"], "Atualiza a Constituição Federal (texto compilado do Planalto)", ativo)
    return True


# --- 2. Normas novas ------------------------------------------------------------------------------

def atualizar_indice():
    script = os.path.join(SCRIPTS, "indice_federal.py")
    # primeiro completa os anos que faltam no cache; depois refaz os dois últimos, que ainda mudam
    subprocess.run([sys.executable, "-I", script], check=True)
    subprocess.run([sys.executable, "-I", script, "--de", str(dt.date.today().year - 1), "--refazer"], check=True)


def novas(itens, ativo):
    ano_min = str(dt.date.today().year - 1)
    alvo = [d for d in itens if d["dataassinatura"][6:] >= ano_min and not os.path.exists(bf.montar(d)["md"])]
    print(f"Normas recentes sem .md: {len(alvo)}", flush=True)
    criadas = []
    for d in alvo:
        try:
            status, _, extra = bf.processar(d)
        except Exception as e:
            status, extra = "erro", str(e)[:200]
        if status == "ok":
            md = bf.montar(d)["md"]
            commit([md], f"Acrescenta {d['normaNome'].strip()}", ativo)
            criadas.append(d)
        else:
            print("sem texto ainda:", d["norma"], status, extra if isinstance(extra, str) else (extra or {}).get("motivo"))
    return criadas


def citadas(d, por_numero):
    """Arquivos das normas que a ementa diz alterar ou revogar."""
    achados = []
    for tipo, numero, ano in CITACAO.findall(d.get("ementa") or ""):
        chave = (PREFIXO_CITACAO[tipo.lower()], numero.replace(".", ""))
        for ano_md, md in por_numero.get(chave, []):
            if not ano or ano == ano_md:
                achados.append(md)
    return achados


# --- 3. Alterações --------------------------------------------------------------------------------

def checar(d, estado, ativo):
    info = bf.montar(d)
    md, rel = info["md"], os.path.relpath(info["md"], RAIZ_REPO).replace(os.sep, "/")
    if PARAR.is_set():
        return None
    with TRAVA:
        reg = estado["normas"].setdefault(rel, {})
    reg.setdefault("sha", sha_do_cabecalho(md))
    reg["visto"] = HOJE
    urn, meta = bf.obter_metadados(info["urn"], d["id"])
    captura = getattr(meta, "captura", None)
    if urn != info["urn"] or not captura or captura["sha256"] == reg["sha"]:
        return None
    antigo = md + ".olheiro"
    os.replace(md, antigo)
    try:
        status, _, _ = bf.processar(d)
    except Exception as e:
        status = "erro: " + str(e)[:200]
    if status != "ok" or relevante(md) == relevante(antigo):
        os.replace(antigo, md)
        if status == "ok":
            reg["sha"] = captura["sha256"]  # metadados mudaram, texto não: só memoriza
        return None
    os.remove(antigo)
    reg["sha"] = captura["sha256"]
    with TRAVA:
        estado["prioridade"].pop(rel, None)
    return md, f"Atualiza {d['normaNome'].strip()} (texto compilado)"


def alteracoes(itens, criadas, estado, n, prazo, workers, ativo):
    existentes = {}
    por_numero = {}
    for d in itens:
        info = bf.montar(d)
        if os.path.exists(info["md"]):
            rel = os.path.relpath(info["md"], RAIZ_REPO).replace(os.sep, "/")
            existentes[rel] = d
            prefixo = bf.TIPOS[d["tipo"]][1]
            por_numero.setdefault((prefixo, str(d.get("numero") or "").replace(".", "")), []).append((info["data"][:4], rel))
    limite = (dt.date.today() + dt.timedelta(days=DIAS_PRIORIDADE)).isoformat()
    for d in criadas:
        for rel in citadas(d, por_numero):
            estado["prioridade"][rel] = limite
    estado["prioridade"] = {k: v for k, v in estado["prioridade"].items() if v >= HOJE and k in existentes}
    fila = list(estado["prioridade"])
    resto = sorted((k for k in existentes if k not in estado["prioridade"]),
                   key=lambda k: estado["normas"].get(k, {}).get("visto", ""))
    fila += resto[: max(0, n - len(fila))]
    print(f"Rechecando {len(fila)} de {len(existentes)} normas ({len(estado['prioridade'])} prioritárias)", flush=True)
    mudou = 0
    with ThreadPoolExecutor(workers) as ex:
        futs = []
        for rel in fila:
            futs.append(ex.submit(checar, existentes[rel], estado, ativo))
        for i, fut in enumerate(futs, 1):
            if time.monotonic() > prazo and not PARAR.is_set():
                PARAR.set()  # as que já começaram terminam e são gravadas; as outras voltam sem marcar
                print("Tempo esgotado; o resto fica para a próxima rodada", flush=True)
            try:
                r = fut.result()
            except Exception as e:
                print("erro na checagem:", str(e)[:200])
                continue
            if r:
                commit([r[0]], r[1], ativo)
                mudou += 1
            if i % 500 == 0:
                print(f"{i}/{len(fila)} checadas, {mudou} atualizadas", flush=True)
                salvar(estado)
    print(f"Alterações gravadas: {mudou}", flush=True)


def salvar(estado):
    tmp = ESTADO + ".tmp"
    with TRAVA:
        texto = json.dumps(estado, ensure_ascii=False)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(texto)
    os.replace(tmp, ESTADO)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--checar", type=int, default=6000, help="normas existentes rechecadas por rodada")
    ap.add_argument("--minutos", type=float, default=300, help="orçamento de tempo da rodada")
    ap.add_argument("--rps", type=float, default=3)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--commit", action="store_true", help="faz um commit por mudança (sem isto, só simula os commits)")
    a = ap.parse_args()
    prazo = time.monotonic() + a.minutos * 60
    bf.LIMITE = bf.Limitador(min(a.rps, 4))
    ok = True
    try:
        ok = constituicao(a.commit)
    except Exception as e:
        print("::warning::Constituição não verificada:", e)
    atualizar_indice()
    itens = bf.carregar_indice(set())
    estado = json.load(open(ESTADO, encoding="utf-8")) if os.path.exists(ESTADO) else {}
    estado.setdefault("normas", {})
    estado.setdefault("prioridade", {})
    try:
        criadas = novas(itens, a.commit)
        alteracoes(itens, criadas, estado, a.checar, prazo, a.workers, a.commit)
    finally:
        salvar(estado)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
