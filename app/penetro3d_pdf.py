#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
penetro3d_pdf.py — relatório PDF estático (sem o bloco 3D).

Conteúdo, nesta ordem:
  1. Cabeçalho, indicadores e mapas da resistência média por camada, cada um com o
     selo de suporte espacial
  2. Mapas de síntese (espessura somada acima do limite, profundidade da RP máxima)
     e os perfis sobrepostos com a média do talhão
  3. Um painel por ponto amostrado: resistência × profundidade, com a média do
     talhão ao fundo para comparação
  4. Tabela dos pontos com o dado MEDIDO (sem interpolação)
  5. Nota de método

Os mapas vêm da grade interpolada; a tabela e os perfis, das leituras originais.
"""

import os
import re
import tempfile

import matplotlib
matplotlib.use('Agg')                                   # sem janela: só arquivo
import matplotlib.pyplot as plt                         # noqa: E402
import numpy as np                                      # noqa: E402
from matplotlib.colors import LinearSegmentedColormap   # noqa: E402
from matplotlib.lines import Line2D                     # noqa: E402
from reportlab.lib import colors                        # noqa: E402
from reportlab.lib.enums import TA_JUSTIFY              # noqa: E402
from reportlab.lib.pagesizes import A4                  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import cm                      # noqa: E402
from reportlab.platypus import (BaseDocTemplate, Frame, Image, PageBreak,  # noqa: E402
                                PageTemplate, Paragraph, Spacer, Table, TableStyle)

from penetro3d_core import (CMAX_KPA, LIM_CRIT, LIM_MOD, RAMPA, aneis, esc, num_br,  # noqa: E402
                            num_cm, rotulo_camada)
from penetro3d_versao import AUTOR  # noqa: E402

VERDE1, CINZA, AMBAR, VERMELHO = '#155A54', '#727D84', '#F7A823', '#EE3124'
TINTA, TINTA2, TINTA3 = '#12211D', '#3E4F49', '#6C7B75'
CMAP = LinearSegmentedColormap.from_list('rp', [(p, c) for p, c in RAMPA])
DPI = 190

plt.rcParams.update({
    'font.family': 'DejaVu Sans', 'font.size': 8,
    'axes.edgecolor': '#C9D3C6', 'axes.labelcolor': TINTA2,
    'xtick.color': TINTA3, 'ytick.color': TINTA3,
    'axes.grid': True, 'grid.color': '#E6ECE3', 'grid.linewidth': .6,
    'figure.facecolor': 'white', 'savefig.facecolor': 'white',
})


# ────────────────────────────────────────────────────────────────────── figuras ──
def _estender(grade, mask, passos=3):
    """Copia o valor dos vizinhos para as células logo FORA do polígono (só elas):
    um NaN de dentro do polígono é intencional — "em branco" num mapa — e fica."""
    g = np.array(grade, float, copy=True)
    valido = mask & np.isfinite(g)
    ocupado = mask.copy()
    for _ in range(passos):
        p = np.pad(np.where(valido, g, 0.0), 1)
        q = np.pad(valido.astype(float), 1)
        soma = np.zeros_like(g)
        n = np.zeros_like(g)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy or dx:
                    sl = (slice(1 + dy, 1 + dy + g.shape[0]), slice(1 + dx, 1 + dx + g.shape[1]))
                    soma += p[sl]
                    n += q[sl]
        novo = (~ocupado) & (n > 0)
        if not novo.any():
            break
        g[novo] = soma[novo] / n[novo]
        valido = valido | novo
        ocupado = ocupado | novo
    return g


def _recorte(poli):
    """Contorno do talhão (com buracos) como PathPatch para recortar a imagem."""
    from matplotlib.patches import PathPatch
    from matplotlib.path import Path
    partes = list(poli.geoms) if poli.geom_type == 'MultiPolygon' else [poli]
    vert, cod = [], []
    aneis_ = [(np.asarray(p.exterior.coords, float), True) for p in partes] + \
             [(np.asarray(i.coords, float), False) for p in partes for i in p.interiors]
    for a, externo in aneis_:
        if len(a) < 3:
            continue
        area = 0.5 * np.sum(a[:-1, 0] * a[1:, 1] - a[1:, 0] * a[:-1, 1])
        if (area > 0) != externo:              # externo anti-horário, buracos horário
            a = a[::-1]
        vert.extend(a.tolist()); vert.append(a[0].tolist())
        cod.extend([Path.MOVETO] + [Path.LINETO] * (len(a) - 1) + [Path.CLOSEPOLY])
    if not vert:
        return None
    return PathPatch(Path(vert, cod), facecolor='none', edgecolor='none')


def _mpl(txt):
    """Texto do usuário no matplotlib: "$" abriria fórmula matemática e quebraria."""
    return str(txt).replace('$', r'\$')


def _mapa(ax, R, grade, vmin, vmax, cmap=CMAP, pontos_xy=None, dentro=None, rotulos=None):
    """Desenha uma grade interpolada com o contorno do talhão e os pontos."""
    gx, gy = R['gx'], R['gy']
    ext = [gx[0], gx[-1], gy[0], gy[-1]]
    # A suavização bilinear come uma célula inteira na borda de uma grade mascarada,
    # deixando uma faixa branca entre a cor e o contorno. Por isso a grade é estendida
    # algumas células para fora do polígono e a imagem é recortada pelo próprio contorno.
    mask = R.get('mask')
    g = _estender(grade, mask) if mask is not None else grade
    im = ax.imshow(np.ma.masked_invalid(g), extent=ext, origin='lower',
                   cmap=cmap, vmin=vmin, vmax=vmax, interpolation='bilinear', zorder=1)
    recorte = _recorte(R['poli'])
    if recorte is not None:
        recorte.set_transform(ax.transData)
        im.set_clip_path(recorte)
    for anel in aneis(R['poli']):                   # externo + buracos
        ax.plot([a for a, _ in anel], [b for _, b in anel], color=TINTA3, lw=1.0, zorder=3)
    if pontos_xy is not None:
        cor = ['white' if d else CINZA for d in dentro]
        ax.scatter(*pontos_xy, s=14, c=cor, edgecolors=TINTA, linewidths=.7, zorder=4)
        if rotulos is not None:
            for x, y, t in zip(pontos_xy[0], pontos_xy[1], rotulos):
                ax.annotate(_mpl(t), (x, y), fontsize=5, color=TINTA, zorder=5,
                            xytext=(0, 5), textcoords='offset points', ha='center')
    ax.set_aspect('equal')
    ax.set_xticks([]); ax.set_yticks([]); ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)
    return im


def _barra_escala(ax, gx, gy):
    """Barra de escala no canto inferior esquerdo."""
    larg = gx[-1] - gx[0]
    passo = 100 if larg > 400 else 50
    x0, y0 = gx[0] + larg * .04, gy[0] + (gy[-1] - gy[0]) * .05
    ax.plot([x0, x0 + passo], [y0, y0], color=TINTA, lw=2, solid_capstyle='butt', zorder=6)
    ax.annotate(f'{passo} m', (x0 + passo / 2, y0), fontsize=5.5, color=TINTA,
                ha='center', va='bottom', xytext=(0, 2), textcoords='offset points', zorder=6)


def fig_camadas(caminho, R, medias, camadas, S, pontos_xy, dentro, rotulos, V=None):
    """Grade 2×2 com a resistência média de cada camada de profundidade."""
    chaves = [(c, a, b) for c, a, b in camadas if c in medias]
    n = len(chaves)
    ncol = 2 if n > 1 else 1
    nlin = int(np.ceil(n / ncol))
    fig, axs = plt.subplots(nlin, ncol, figsize=(7.0, 3.4 * nlin))
    axs = np.atleast_1d(axs).ravel()
    im = None
    for ax, (c, a, b) in zip(axs, chaves):
        im = _mapa(ax, R, medias[c], 0, CMAX_KPA, pontos_xy=pontos_xy,
                   dentro=dentro, rotulos=rotulos)
        _barra_escala(ax, R['gx'], R['gy'])
        ax.set_title(rotulo_camada(a, b), fontsize=9.5, color=TINTA, pad=27, loc='left',
                     fontweight='bold')
        ax.text(0, 1.075, f"média {num_br(S[c]['media'])} kPa · {S[c]['rest']}% restritivo",
                transform=ax.transAxes, fontsize=6.5, color=TINTA3, va='bottom')
        v = (V or {}).get(c)
        if v:
            # o selo é o que impede alguém de ler manchas onde só há ruído
            ok = v['suporte']
            ax.text(0, 1.005,
                    ('✓ com suporte espacial' if ok else
                     '✕ sem suporte espacial — leia a média, não as manchas'),
                    transform=ax.transAxes, fontsize=6.5, va='bottom',
                    color=(VERDE1 if ok else VERMELHO),
                    fontweight='bold' if not ok else 'normal')
    for ax in axs[n:]:
        ax.axis('off')
    fig.subplots_adjust(left=.02, right=.88, top=.94, bottom=.03, hspace=.22, wspace=.02)
    cax = fig.add_axes([.90, .10, .018, .78])
    cb = fig.colorbar(im, cax=cax)
    cb.set_label('Resistência à penetração (kPa)', fontsize=7.5, color=TINTA2)
    cb.ax.tick_params(labelsize=6.5)
    for lim in (LIM_MOD, LIM_CRIT):
        cb.ax.axhline(lim, color='white', lw=1.1)
    fig.savefig(caminho, dpi=DPI, bbox_inches='tight')
    plt.close(fig)


def fig_sintese(caminho, R, esp, zmax, pontos_xy, dentro):
    """Espessura somada acima do limite e profundidade em que a RP é máxima."""
    fig, axs = plt.subplots(1, 2, figsize=(7.0, 3.5))

    esp_m = np.where(np.nan_to_num(esp) > 0, esp, np.nan)
    topo = float(np.nanmax(esp)) if np.isfinite(esp).any() else 0.0
    im0 = _mapa(axs[0], R, esp_m, 0, max(topo, 5), cmap='YlOrRd',
                pontos_xy=pontos_xy, dentro=dentro)
    _barra_escala(axs[0], R['gx'], R['gy'])
    axs[0].set_title(f'Espessura acima de {num_br(LIM_CRIT)} kPa', fontsize=9,
                     color=TINTA, pad=25, loc='left', fontweight='bold')
    axs[0].text(0, 1.005, 'soma no perfil, contígua ou não\nem branco: todo o perfil abaixo do limite',
                transform=axs[0].transAxes, fontsize=6.5, color=TINTA3, va='bottom')
    cb0 = fig.colorbar(im0, ax=axs[0], fraction=.045, pad=.02)
    cb0.set_label('cm', fontsize=7); cb0.ax.tick_params(labelsize=6.5)

    zlo, zhi = float(np.nanmin(zmax)), float(np.nanmax(zmax))
    im1 = _mapa(axs[1], R, zmax, zlo, zhi if zhi > zlo else zlo + 1, cmap='viridis_r',
                pontos_xy=pontos_xy, dentro=dentro)
    _barra_escala(axs[1], R['gx'], R['gy'])
    axs[1].set_title('Profundidade da resistência máxima', fontsize=9, color=TINTA,
                     pad=25, loc='left', fontweight='bold')
    axs[1].text(0, 1.005, 'onde está o ponto mais duro de cada perfil',
                transform=axs[1].transAxes, fontsize=6.5, color=TINTA3, va='bottom')
    cb1 = fig.colorbar(im1, ax=axs[1], fraction=.045, pad=.02)
    cb1.set_label('cm', fontsize=7); cb1.ax.tick_params(labelsize=6.5)

    fig.tight_layout()
    fig.savefig(caminho, dpi=DPI, bbox_inches='tight')
    plt.close(fig)


def _faixas(ax, xmax):
    ax.axvspan(LIM_MOD, min(LIM_CRIT, xmax), color=AMBAR, alpha=.10, lw=0, zorder=0)
    if xmax > LIM_CRIT:
        ax.axvspan(LIM_CRIT, xmax, color=VERMELHO, alpha=.10, lw=0, zorder=0)


def _xmax_perfil():
    """Limite do eixo x. Fixo na saturação da escala: um perfil com impedimento
    pontual de 6.000 kPa espremeria todos os demais contra a margem esquerda."""
    return CMAX_KPA * 1.09


def fig_perfis(caminho, prof, CI):
    """Todos os perfis sobrepostos, com a média do talhão em destaque."""
    xmax = _xmax_perfil()
    fig, ax = plt.subplots(figsize=(6.6, 4.0))
    _faixas(ax, xmax)
    for i in range(CI.shape[1]):
        ax.plot(CI[:, i], prof, color=CINZA, lw=.7, alpha=.55, zorder=2)
    ax.plot(CI.mean(axis=1), prof, color=VERDE1, lw=2.4, zorder=3)
    ax.set_xlim(0, xmax); ax.set_ylim(prof.max(), 0)
    ax.set_xlabel('Resistência à penetração (kPa)')
    ax.set_ylabel('Profundidade (cm)')
    ax.legend(handles=[Line2D([], [], color=VERDE1, lw=2.4,
                              label=f'Média dos {CI.shape[1]} perfis'),
                       Line2D([], [], color=CINZA, lw=.9, label='Perfis individuais')],
              loc='lower right', fontsize=7, framealpha=.9)
    if float(CI.max()) > xmax:
        ax.text(.012, .015, f'leituras acima de {num_br(CMAX_KPA)} kPa saem da escala',
                transform=ax.transAxes, ha='left', va='bottom', fontsize=6, color=TINTA3)
    fig.tight_layout()
    fig.savefig(caminho, dpi=DPI, bbox_inches='tight')
    plt.close(fig)


def figs_perfis_por_ponto(pasta, prof, CI, pontos, situacao, por_pagina=20, ncol=5):
    """Um painel por ponto. Devolve a lista de arquivos (uma imagem por página)."""
    media = CI.mean(axis=1)
    xmax = _xmax_perfil()
    arquivos = []
    n = CI.shape[1]
    for p0 in range(0, n, por_pagina):
        bloco = list(range(p0, min(p0 + por_pagina, n)))
        nlin = int(np.ceil(len(bloco) / ncol))
        fig, axs = plt.subplots(nlin, ncol, figsize=(7.0, 1.85 * nlin),
                                sharex=True, sharey=True)
        axs = np.atleast_1d(axs).ravel()
        for ax, i in zip(axs, bloco):
            _faixas(ax, xmax)
            ax.plot(media, prof, color=CINZA, lw=.9, alpha=.7, zorder=2)
            ax.plot(CI[:, i], prof, color=VERDE1, lw=1.6, zorder=3)
            k = int(np.argmax(CI[:, i]))
            # marcador preso à margem quando a leitura estoura a escala
            ax.plot(min(CI[k, i], xmax * .985), prof[k], 'o', ms=3.2, color=VERMELHO, zorder=4)
            marca = ' (borda)' if situacao is not None and situacao[i] == 'borda' else ''
            ax.set_title(f'Ponto {_mpl(pontos.id.iloc[i])}{marca}', fontsize=7.5,
                         color=TINTA, pad=3)
            ax.tick_params(labelsize=6)
        for ax in axs[len(bloco):]:
            ax.axis('off')
        axs[0].set_xlim(0, xmax); axs[0].set_ylim(prof.max(), 0)
        fig.supxlabel('Resistência à penetração (kPa)', fontsize=8, color=TINTA2)
        fig.supylabel('Profundidade (cm)', fontsize=8, color=TINTA2)
        fig.tight_layout(rect=[.02, .02, 1, 1])
        alvo = os.path.join(pasta, f'perfis_ponto_{p0}.png')
        fig.savefig(alvo, dpi=DPI, bbox_inches='tight')
        plt.close(fig)
        arquivos.append(alvo)
    return arquivos


# ─────────────────────────────────────────────────────────────────── documento ──
def _estilos():
    ss = getSampleStyleSheet()
    return {
        'titulo': ParagraphStyle('t', parent=ss['Title'], fontName='Helvetica-Bold',
                                 fontSize=17, leading=20, spaceAfter=2,
                                 alignment=0, textColor=colors.HexColor(TINTA)),
        'olho': ParagraphStyle('o', parent=ss['Normal'], fontName='Helvetica-Bold',
                               fontSize=7.5, leading=10, spaceAfter=3,
                               textColor=colors.HexColor(TINTA3)),
        'h2': ParagraphStyle('h', parent=ss['Normal'], fontName='Helvetica-Bold',
                             fontSize=11.5, leading=14, spaceBefore=6, spaceAfter=5,
                             textColor=colors.HexColor(TINTA)),
        'corpo': ParagraphStyle('c', parent=ss['Normal'], fontSize=8.6, leading=11.6,
                                alignment=TA_JUSTIFY, spaceAfter=5,
                                textColor=colors.HexColor(TINTA2)),
        'nota': ParagraphStyle('n', parent=ss['Normal'], fontSize=7.6, leading=10,
                               spaceAfter=3, textColor=colors.HexColor(TINTA3)),
    }


def _html_para_reportlab(txt):
    """Converte as tags do relatório HTML para as poucas que o reportlab entende."""
    txt = re.sub(r'<span class=.flag.>(.*?)</span>', r'<b>\1</b>', txt, flags=re.S)
    return txt.replace('<code>', '<font name="Courier">').replace('</code>', '</font>')


def _tabela_kpis(S, camadas):
    pares = [(c, a, b) for c, a, b in camadas[:2] if c in S]
    dados = [
        [f'Área com camada\n> {num_br(LIM_CRIT)} kPa', 'Espessura somada\nacima do limite',
         'Profundidade mediana\nda RP máxima']
        + [f'RP média\n{rotulo_camada(a, b)}' for c, a, b in pares],
        [f"{S['restritiva_area']}%", f"{num_br(S['restritiva_esp'], 1)} cm",
         f"{num_cm(S['zmax_mediana'])} cm"]
        + [f"{num_br(S[c]['media'])} kPa" for c, _, _ in pares],
    ]
    barras = [VERMELHO, AMBAR, AMBAR] + [
        VERMELHO if S[c]['media'] >= LIM_CRIT else (AMBAR if S[c]['media'] >= LIM_MOD
                                                    else '#72BF44')
        for c, _, _ in pares]
    larg = (17.4 / len(dados[0])) * cm
    t = Table(dados, colWidths=[larg] * len(dados[0]), rowHeights=[1.05 * cm, .78 * cm])
    estilo = [('FONT', (0, 0), (-1, 0), 'Helvetica', 6.8),
              ('FONT', (0, 1), (-1, 1), 'Helvetica-Bold', 14),
              ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor(TINTA3)),
              ('TEXTCOLOR', (0, 1), (-1, 1), colors.HexColor(TINTA)),
              ('VALIGN', (0, 0), (-1, -1), 'TOP'),
              ('LEFTPADDING', (0, 0), (-1, -1), 7), ('TOPPADDING', (0, 0), (-1, 0), 6),
              ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F4F6F2')),
              ('BOX', (0, 0), (-1, -1), .5, colors.HexColor('#DCE3D9')),
              ('INNERGRID', (0, 0), (-1, -1), .5, colors.white)]
    for i, cor in enumerate(barras):
        estilo.append(('LINEBEFORE', (i, 0), (i, -1), 2.4, colors.HexColor(cor)))
    t.setStyle(TableStyle(estilo))
    return t


def _tabela_pontos(tabela, camadas):
    cols_cam = [(c, a, b) for c, a, b in camadas if c in tabela.columns]
    cab = (['Ponto', 'Latitude', 'Longitude', 'Situação']
           + [f'{num_cm(a)}–{num_cm(b)}' for c, a, b in cols_cam] + ['RP máx.', 'Prof. máx.'])
    linhas = [cab]
    est_id = ParagraphStyle('id', fontName='Helvetica', fontSize=7, leading=8.2,
                            textColor=colors.HexColor(TINTA))
    for _, r in tabela.iterrows():
        linhas.append([Paragraph(esc(r['ponto']), est_id), f"{r['lat']:.6f}".replace('.', ','),
                       f"{r['lon']:.6f}".replace('.', ','), r['situacao']]
                      + [num_br(r[c]) for c, _, _ in cols_cam]
                      + [num_br(r['rp_max']), num_cm(r['prof_rp_max']) + ' cm'])
    larg = ([1.3 * cm, 2.1 * cm, 2.1 * cm, 1.5 * cm] + [1.55 * cm] * len(cols_cam)
            + [1.6 * cm, 1.7 * cm])
    t = Table(linhas, colWidths=larg, repeatRows=1)
    estilo = [('FONT', (0, 0), (-1, 0), 'Helvetica-Bold', 6.4),
              ('FONT', (0, 1), (-1, -1), 'Helvetica', 7),
              ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor(TINTA3)),
              ('TEXTCOLOR', (0, 1), (-1, -1), colors.HexColor(TINTA)),
              ('ALIGN', (1, 0), (-1, -1), 'RIGHT'), ('ALIGN', (3, 0), (3, -1), 'CENTER'),
              ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
              ('LINEBELOW', (0, 0), (-1, 0), .8, colors.HexColor('#B9C6B4')),
              ('LINEBELOW', (0, 1), (-1, -2), .3, colors.HexColor('#E6ECE3')),
              ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3)]
    for i, (_, r) in enumerate(tabela.iterrows(), start=1):
        if r['situacao'] == 'borda':
            estilo.append(('TEXTCOLOR', (3, i), (3, i), colors.HexColor(CINZA)))
        if r['rp_max'] >= LIM_CRIT:
            estilo.append(('TEXTCOLOR', (len(cab) - 2, i), (len(cab) - 2, i),
                           colors.HexColor(VERMELHO)))
    t.setStyle(TableStyle(estilo))
    return t


def _img(caminho, largura):
    """Imagem ajustada à largura, preservando a proporção original."""
    from PIL import Image as PILImage
    with PILImage.open(caminho) as im:
        w, h = im.size
    return Image(caminho, width=largura, height=largura * h / w)


def gerar_pdf(caminho, ctx, pontos, prof, CI, R, S, medias, esp, zmax,
              camadas, tabela, notas, V=None):
    """Monta o PDF completo do talhão."""
    est = _estilos()
    pontos_xy = (R['sx'], R['sy'])
    rotulos = [str(v) for v in pontos.id] if len(pontos) <= 40 else None
    situacao = tabela['situacao'].to_numpy() if 'situacao' in tabela else None

    with tempfile.TemporaryDirectory() as tmp:
        f_camadas = os.path.join(tmp, 'camadas.png')
        f_sintese = os.path.join(tmp, 'sintese.png')
        f_perfis = os.path.join(tmp, 'perfis.png')
        fig_camadas(f_camadas, R, medias, camadas, S, pontos_xy, R['dentro'], rotulos, V)
        fig_sintese(f_sintese, R, esp, zmax, pontos_xy, R['dentro'])
        fig_perfis(f_perfis, prof, CI)
        f_pontos = figs_perfis_por_ponto(tmp, prof, CI, pontos, situacao)

        def moldura(canv, doc):
            canv.saveState()
            canv.setStrokeColor(colors.HexColor(VERDE1)); canv.setLineWidth(1.6)
            canv.line(2 * cm, A4[1] - 1.45 * cm, A4[0] - 2 * cm, A4[1] - 1.45 * cm)
            canv.setFont('Helvetica', 6.6); canv.setFillColor(colors.HexColor(TINTA3))
            cab = f"{ctx['projeto']} · {ctx['talhao']}"
            canv.drawString(2 * cm, A4[1] - 1.15 * cm,
                            cab if len(cab) <= 110 else cab[:107] + '…')
            canv.drawRightString(A4[0] - 2 * cm, 1.15 * cm, f'{doc.page}')
            canv.drawString(2 * cm, 1.15 * cm,
                            f'Penetro3D · relatório de penetrometria · {AUTOR}')
            canv.restoreState()

        doc = BaseDocTemplate(caminho, pagesize=A4,
                              title=f"Compactação do solo — {ctx['talhao']}",
                              author=AUTOR, subject=ctx['projeto'])
        quadro = Frame(2 * cm, 1.6 * cm, A4[0] - 4 * cm, A4[1] - 3.6 * cm, id='q',
                       leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        doc.addPageTemplates([PageTemplate(id='p', frames=[quadro], onPage=moldura)])

        L = 17.4 * cm
        el = []
        el.append(Paragraph(esc(ctx['projeto'].upper()) + ' · PENETROMETRIA', est['olho']))
        el.append(Paragraph(f"Compactação do solo — {esc(ctx['talhao'])}", est['titulo']))
        meta = [f"Área {num_br(R['area_ha'], 2)} ha", f'{len(pontos)} perfis',
                f"{num_cm(prof.min())}–{num_cm(prof.max())} cm "
                f"({len(prof)} leituras/perfil)", f"grade {num_br(R['res_m'])} m"]
        if ctx.get('data_coleta'):
            meta.insert(2, f"coleta {esc(ctx['data_coleta'])}")
        el.append(Paragraph(' · '.join(meta), est['nota']))
        el.append(Spacer(1, 7))
        el.append(_tabela_kpis(S, camadas))
        el.append(Spacer(1, 12))
        el.append(Paragraph('Resistência média por camada de profundidade', est['h2']))
        el.append(Paragraph(
            'Grade interpolada por IDW e recortada pelo contorno do talhão. Os pontos claros '
            'marcam os perfis amostrados; os cinza, perfis cuja coordenada caiu na borda do '
            'polígono. As linhas brancas na barra de cor marcam '
            f'{num_br(LIM_MOD)} e {num_br(LIM_CRIT)} kPa.', est['corpo']))
        if V:
            el.append(Paragraph(
                'O selo acima de cada mapa vem de uma validação cruzada feita camada a '
                'camada: compara a interpolação contra a alternativa mais simples, que é '
                'usar a média do talhão. Onde a interpolação não reduz o erro em pelo menos 10%, o desenho '
                'das manchas não tem suporte no dado — nesses mapas, leia o valor médio '
                'e ignore a posição das cores.', est['corpo']))
        el.append(_img(f_camadas, L))

        el.append(PageBreak())
        el.append(Paragraph('Onde está a restrição', est['h2']))
        el.append(Paragraph(
            'À esquerda, quanto do perfil está acima do limite crítico em cada posição. É a '
            'soma das leituras acima do limite, que podem estar em um bloco só ou em blocos '
            'separados — confira os perfis ponto a ponto antes de fixar a profundidade de '
            'trabalho. À direita, em que profundidade cada perfil atinge sua resistência '
            'máxima, que é onde a haste de um escarificador precisaria chegar.', est['corpo']))
        el.append(_img(f_sintese, L))
        el.append(Spacer(1, 10))
        el.append(Paragraph('Perfis verticais sobrepostos', est['h2']))
        el.append(Paragraph(
            'Cada linha cinza é um perfil medido; a linha verde é a média do talhão. As '
            'faixas de fundo marcam as classes moderada e restritiva.', est['corpo']))
        el.append(_img(f_perfis, 15.2 * cm))

        el.append(PageBreak())
        el.append(Paragraph('Resistência × profundidade, ponto a ponto', est['h2']))
        el.append(Paragraph(
            'Dado medido, sem interpolação. A linha verde é o perfil do ponto; a cinza, a '
            'média do talhão, repetida em todos os painéis para comparação. O círculo '
            'vermelho marca a profundidade da resistência máxima daquele perfil.',
            est['corpo']))
        for i, f in enumerate(f_pontos):
            if i:
                el.append(PageBreak())
            el.append(_img(f, L))

        el.append(PageBreak())
        el.append(Paragraph('Pontos amostrados', est['h2']))
        el.append(Paragraph(
            'Valores medidos em kPa, média das leituras dentro de cada faixa de profundidade '
            '— não são valores interpolados. "Borda" indica perfil cuja coordenada caiu fora '
            'do polígono do KML, dentro da tolerância aceita.', est['corpo']))
        el.append(_tabela_pontos(tabela, camadas))
        el.append(Spacer(1, 14))

        el.append(Paragraph('Método, incertezas e o que verificar no campo', est['h2']))
        for nota in notas:
            el.append(Paragraph('• ' + _html_para_reportlab(nota), est['corpo']))

        doc.build(el)
