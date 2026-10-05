#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
penetro3d_celular.py — ponte entre o computador e o celular, pela rede local.

O caminho antigo para levar um arquivo ao celular era WhatsApp, e-mail ou cabo.
Aqui o próprio programa serve a pasta por HTTP na rede local e mostra um QR code:
o celular aponta a câmera e abre. Serve tanto para o relatório 3D quanto para o
arquivo do plano de amostragem.

Duas coisas importantes:

  · O servidor só existe enquanto a janela estiver aberta. Ao fechar, ele para.
  · Fica acessível a quem estiver na mesma rede Wi-Fi. É a rede da fazenda ou do
    escritório, não a internet — mas vale saber.

Limite conhecido: o radar de campo NÃO funciona por aqui. A API de geolocalização
do navegador exige contexto seguro (https), e um endereço de rede local em http não
é considerado seguro. Por isso o radar precisa ser publicado em um endereço https
uma vez; o que passa por esta ponte é o relatório e o arquivo do plano.
"""

import html
import http.server
import os
import socket
import socketserver
import threading

from penetro3d_versao import AUTOR

def ip_local():
    """IP da máquina na rede local. Não envia pacote — só resolve a rota de saída."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        return s.getsockname()[0]
    except OSError:
        return '127.0.0.1'
    finally:
        s.close()


ORDEM = {'html': 0, 'pdf': 1, 'geojson': 2, 'kmz': 3, 'kml': 4, 'gpx': 5, 'csv': 6}

ROTULOS = {
    'html': 'Relatório 3D interativo',
    'pdf': 'Relatório em PDF',
    'geojson': 'Plano para o radar de campo',
    'kmz': 'Plano para o Google Earth',
    'kml': 'Plano para o Google Earth',
    'gpx': 'Plano para GPS de mão',
    'csv': 'Dados em planilha',
}


def _rotulo(nome, ext):
    """Nome amigável. Um arquivo chamado TALHAO_07._23_0ha_GLEBA_SUL.html
    não diz nada num celular; 'Relatório 3D interativo' diz."""
    base = ROTULOS.get(ext)
    if base is None:
        return nome
    talo = nome.rsplit('.', 1)[0].lower()
    if ext == 'csv':
        finos = {'perfis_brutos': 'Dados: leituras por perfil',
                 'grade_interpolada': 'Dados: grade interpolada',
                 'resumo_do_projeto': 'Resumo do projeto',
                 'pontos_nao_atribuidos': 'Pontos fora dos talhões'}
        return finos.get(talo, base)
    if ext in ('geojson', 'kmz', 'kml', 'gpx'):
        for nivel in ('minimo', 'intermediario', 'alto'):
            if talo.endswith('_' + nivel):
                bonito = {'minimo': 'mínimo', 'intermediario': 'intermediário',
                          'alto': 'alto detalhamento'}[nivel]
                return f'{base} · nível {bonito}'
    return base


def _pagina_indice(pasta, titulo):
    """Índice enxuto, legível no celular, agrupado por talhão."""
    grupos = {}
    for raiz, _, arqs in os.walk(pasta):
        for a in sorted(arqs):
            if a.startswith('.'):
                continue
            caminho = os.path.join(raiz, a)
            rel = os.path.relpath(caminho, pasta).replace(os.sep, '/')
            grupo = os.path.dirname(rel).split('/')[0] or ''
            ext = a.rsplit('.', 1)[-1].lower() if '.' in a else ''
            tam = os.path.getsize(caminho)
            peso = f'{tam/1e6:.1f} MB' if tam > 1e6 else f'{max(1, tam//1024)} KB'
            grupos.setdefault(grupo, []).append(
                (ORDEM.get(ext, 9), _rotulo(a, ext), rel, ext, peso))

    blocos = []
    for grupo in sorted(grupos, key=lambda g: (g == '', g)):
        itens = sorted(grupos[grupo])
        cab = (f'<h2>{html.escape(grupo.replace("_", " "))}</h2>' if grupo else
               ('<h2>Do projeto</h2>' if len(grupos) > 1 else ''))
        linhas = '\n'.join(
            f'<li class="{"principal" if pri == 0 else ""}">'
            f'<a href="{html.escape(rel)}">'
            f'<span class="nome">{html.escape(rot)}</span>'
            f'<span class="meta">{ext.upper()} · {peso}</span></a></li>'
            for pri, rot, rel, ext, peso in itens)
        blocos.append(cab + f'<ul>{linhas}</ul>')
    corpo = '\n'.join(blocos) or '<p class="vazio">Pasta vazia.</p>'

    return f'''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(titulo)}</title><style>
:root{{color-scheme:light}}
*{{box-sizing:border-box}}
body{{margin:0;background:#F4F6F2;color:#12211D;
 font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;font-size:17px}}
.wrap{{max-width:560px;margin:0 auto;padding:22px 16px 40px}}
h1{{font-size:21px;margin:0 0 4px;letter-spacing:-.01em}}
h2{{font-size:13px;text-transform:uppercase;letter-spacing:.08em;color:#6C7B75;
 margin:22px 0 8px;font-weight:700}}
p.sub{{color:#3E4F49;font-size:14px;margin:0 0 6px}}
ul{{list-style:none;padding:0;margin:0;display:grid;gap:9px}}
a{{display:flex;justify-content:space-between;align-items:center;gap:12px;
 background:#fff;border:1px solid #DCE3D9;border-radius:12px;padding:15px 16px;
 text-decoration:none;color:inherit;min-height:58px}}
.principal a{{border-color:#155A54;border-width:2px;background:#F7FBF6}}
.nome{{font-weight:600}}
.meta{{color:#6C7B75;font-size:12px;white-space:nowrap;font-variant-numeric:tabular-nums}}
.vazio{{color:#6C7B75}}
footer{{margin-top:26px;color:#6C7B75;font-size:12.5px;line-height:1.5}}
</style></head><body><div class="wrap">
<h1>{html.escape(titulo)}</h1>
<p class="sub">Toque para abrir.</p>
{corpo}
<footer>Servido pelo Penetro3D no computador, pela rede local.
Ao fechar a janela no computador, este endereço para de funcionar.<br>
Autoria: {html.escape(AUTOR)}</footer>
</div></body></html>'''


class _Servidor(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def servir(pasta, titulo='Penetro3D', porta=0):
    """Sobe um servidor para `pasta` e devolve (url, parar).

    `parar()` derruba o servidor. A porta 0 deixa o sistema escolher uma livre,
    evitando conflito com qualquer coisa que já esteja rodando na máquina.
    """
    pasta = os.path.abspath(pasta)

    class Manipulador(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=pasta, **k)

        def do_GET(self):                                    # noqa: N802
            if self.path in ('/', '/index.html'):
                corpo = _pagina_indice(pasta, titulo).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(corpo)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(corpo)
                return
            super().do_GET()

        def log_message(self, *a):                           # silencia o console
            pass

    srv = _Servidor(('0.0.0.0', porta), Manipulador)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f'http://{ip_local()}:{srv.server_address[1]}/'
    return url, lambda: (srv.shutdown(), srv.server_close())


def matriz_qr(texto):
    """Matriz booleana do QR code, para desenhar em qualquer tela.

    Devolve a matriz em vez de uma imagem de propósito: assim o desenho pode ser
    feito com retângulos num canvas do Tk, sem depender de ImageTk — que é a peça
    da Pillow que costuma faltar em instalação enxuta.
    """
    try:
        import qrcode
    except ImportError:
        return None
    q = qrcode.QRCode(box_size=1, border=2,
                      error_correction=qrcode.constants.ERROR_CORRECT_M)
    q.add_data(texto)
    q.make(fit=True)
    return q.get_matrix()
