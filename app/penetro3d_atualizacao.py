#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
penetro3d_atualizacao.py — avisa quando há versão nova no GitHub e instala.

Como descobre a versão nova
---------------------------
Não usa a API do GitHub. A API limita 60 consultas por hora por IP, e numa rede
corporativa todos os computadores saem pelo mesmo IP — bastariam alguns colegas
abrindo o programa para esgotar a cota e o aviso parar de funcionar para todos.

Em vez disso, pede https://github.com/<repo>/releases/latest, que redireciona para
.../releases/tag/vX.Y.Z. A versão sai do endereço final. Essa página não tem o mesmo
limite. As notas da versão vêm da API só como enfeite: se falhar, o aviso segue sem
elas.

Quando consulta
---------------
No máximo uma vez a cada 20 horas, ao abrir o programa (e sempre que o usuário pedir
pelo botão). Qualquer falha — sem internet, proxy, GitHub fora — é silenciosa: o
programa nunca deixa de abrir por causa disso.

O que faz quando há versão nova
-------------------------------
Mostra um aviso na janela. Se o usuário aceitar, baixa o instalador para a pasta
temporária, confere o tamanho e o SHA-256 publicado junto com a versão
(Penetro3D-Setup.exe.sha256), abre o instalador e fecha o programa — o instalador
precisa do programa fechado para substituir os arquivos. Nada é instalado sem o
usuário pedir.

O hash pega download corrompido ou adulterado no caminho (proxy, rede). Ele vem do
mesmo lugar que o instalador, então não substitui uma assinatura digital contra
quem controlasse a conta do GitHub.
"""

import hashlib

import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request

from penetro3d_versao import REPO_GITHUB, VERSAO

NOME_INSTALADOR = 'Penetro3D-Setup.exe'
NOME_HASH = NOME_INSTALADOR + '.sha256'


class SemResposta(Exception):
    """A consulta não chegou ao GitHub (sem internet, proxy, firewall)."""
INTERVALO_S = 20 * 3600


def pasta_usuario():
    """Pasta gravável do usuário para estado e registro de erros."""
    if sys.platform.startswith('win'):
        base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
        p = os.path.join(base, 'Penetro3D')
    else:
        p = os.path.join(os.path.expanduser('~'), '.local', 'share', 'penetro3d')
    os.makedirs(p, exist_ok=True)
    return p


def _estado_ler():
    """Estado salvo; um arquivo corrompido vale como vazio, nunca trava a consulta."""
    try:
        with open(os.path.join(pasta_usuario(), 'estado.json'), encoding='utf-8') as f:
            e = json.load(f)
        return e if isinstance(e, dict) else {}
    except (OSError, ValueError):
        return {}


def _ultima_consulta():
    try:
        return float(_estado_ler().get('ultima_consulta', 0))
    except (TypeError, ValueError):
        return 0.0


def _estado_gravar(**kw):
    e = _estado_ler()
    e.update(kw)
    try:
        with open(os.path.join(pasta_usuario(), 'estado.json'), 'w', encoding='utf-8') as f:
            json.dump(e, f)
    except OSError:
        pass


def versao_tupla(txt):
    """'v1.10.2' → (1, 10, 2). Compara números, não texto: 1.10 é maior que 1.9."""
    nums = re.findall(r'\d+', str(txt))
    return tuple(int(n) for n in nums[:3]) + (0,) * (3 - min(3, len(nums)))


def _abrir(url, timeout):
    req = urllib.request.Request(url, headers={
        'User-Agent': f'Penetro3D/{VERSAO}', 'Accept': 'text/html,application/json'})
    return urllib.request.urlopen(req, timeout=timeout)


def ultima_versao(repo=REPO_GITHUB, timeout=6):
    """Versão da última release publicada, ou None se não der para saber agora."""
    try:
        with _abrir(f'https://github.com/{repo}/releases/latest', timeout) as r:
            final = r.geturl()
    except (urllib.error.URLError, OSError, ValueError):
        return None
    # a tag inteira (v1.5.0, v1.5.0-rc1…): cortar no primeiro caractere fora de [\d.]
    # gerava um endereço de download inexistente
    m = re.search(r'/releases/tag/([^/?#]+)/?$', final)
    return urllib.request.unquote(m.group(1)) if m else None


def _notas(repo, tag, timeout=6):
    """Notas da versão. Enfeite: qualquer falha devolve texto vazio."""
    try:
        with _abrir(f'https://api.github.com/repos/{repo}/releases/tags/{tag}', timeout) as r:
            corpo = json.loads(r.read().decode('utf-8'))
        # o rodapé "Instalar: …" da página da versão não interessa a quem já tem o programa
        return (corpo.get('body') or '').split('\n---\n')[0].strip()
    except (urllib.error.URLError, OSError, ValueError):
        return ''


def verificar(manual=False, repo=REPO_GITHUB, atual=VERSAO):
    """Há versão nova? Devolve um dicionário com os dados dela, ou None.

    Com manual=False respeita o intervalo mínimo entre consultas. A variável de
    ambiente PENETRO3D_SEM_ATUALIZACAO=1 desliga a consulta automática — para
    computadores sem acesso à internet ou onde a TI preferir controlar versões.
    """
    if not manual:
        if os.environ.get('PENETRO3D_SEM_ATUALIZACAO') == '1':
            return None
        if time.time() - _ultima_consulta() < INTERVALO_S:
            return None
    tag = ultima_versao(repo)
    if not tag:
        # falhou: não grava o horário, para tentar de novo na próxima abertura
        if manual:
            raise SemResposta('Não consegui consultar o GitHub — sem internet, ou a rede '
                              'bloqueia o acesso.')
        return None
    _estado_gravar(ultima_consulta=time.time())
    if versao_tupla(tag) <= versao_tupla(atual):
        return None
    return {'versao': tag.lstrip('v'), 'tag': tag,
            'notas': _notas(repo, tag),
            'pagina': f'https://github.com/{repo}/releases/tag/{tag}',
            'instalador': f'https://github.com/{repo}/releases/download/{tag}/{NOME_INSTALADOR}',
            'hash': f'https://github.com/{repo}/releases/download/{tag}/{NOME_HASH}'}


def baixar(info, progresso=None, timeout=30):
    """Baixa o instalador para a pasta temporária. Devolve o caminho do arquivo.

    `progresso(baixados, total)` é chamado a cada bloco, para a barra da janela.
    Confere o tamanho no fim: um download cortado pela rede não deve ser executado.
    """
    esperado = _hash_publicado(info, timeout)
    versao = re.sub(r'[^\w.-]', '_', str(info['versao']))
    destino = os.path.join(tempfile.gettempdir(), f'Penetro3D-Setup-{versao}.exe')
    parcial = destino + '.parcial'
    h = hashlib.sha256()
    with _abrir(info['instalador'], timeout) as r, open(parcial, 'wb') as f:
        total = int(r.headers.get('Content-Length') or 0)
        feito = 0
        while True:
            bloco = r.read(256 * 1024)
            if not bloco:
                break
            f.write(bloco)
            h.update(bloco)
            feito += len(bloco)
            if progresso:
                progresso(feito, total)
    if total and os.path.getsize(parcial) != total:
        os.remove(parcial)
        raise IOError('O download do instalador veio incompleto. Tente de novo.')
    if h.hexdigest().lower() != esperado:
        os.remove(parcial)
        raise IOError('O instalador baixado não confere com o SHA-256 publicado na versão '
                      '(arquivo corrompido ou alterado no caminho). Nada foi instalado.')
    if os.path.exists(destino):
        os.remove(destino)
    os.replace(parcial, destino)
    return destino


def _hash_publicado(info, timeout):
    """SHA-256 do arquivo .sha256 publicado junto com o instalador."""
    try:
        with _abrir(info['hash'], timeout) as r:
            txt = r.read(4096).decode('ascii', 'replace')
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
        raise IOError('Não encontrei o SHA-256 desta versão no GitHub, então não dá para '
                      'conferir o instalador. Baixe pela página da versão.') from e
    m = re.search(r'\b([0-9a-fA-F]{64})\b', txt)
    if not m:
        raise IOError('O arquivo de SHA-256 da versão está em formato inesperado.')
    return m.group(1).lower()


def executar_instalador(caminho):
    """Abre o instalador. Quem chama deve fechar o programa logo em seguida."""
    if sys.platform.startswith('win'):
        os.startfile(caminho)                                      # noqa: S606
    else:
        raise OSError('O instalador automático só existe para Windows.')
