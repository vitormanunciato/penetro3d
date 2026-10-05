#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
penetro3d_core.py — leitura, interpolação, conferência e relatório HTML.

Núcleo do Penetro3D. Não depende de interface gráfica: é usado pelo app
(penetro3d_app.py), pela linha de comando e pelos testes.

Fluxo de um projeto
-------------------
  1. carregar_talhoes()   lê um ou mais KML → polígonos (com buracos)
  2. ler_falker()         lê a planilha do PenetroLOG → pontos + leituras
  3. atribuir_pontos()    descobre em qual talhão cai cada ponto
  4. interpolar()         IDW camada a camada dentro de cada polígono
  5. resumo()             estatísticas agronômicas
  6. validar_camadas()    em quais camadas o mapa tem suporte espacial
  7. render_html()        relatório interativo com o bloco 3D
  (o PDF é gerado por penetro3d_pdf.py)

Método
------
  · Interpolação IDW (p=2) aplicada CAMADA A CAMADA: cada profundidade lida é
    interpolada no plano de forma independente, sem mistura vertical. A amostragem
    vertical (2,5 cm) é ordens de grandeza mais densa que a horizontal (dezenas de
    metros) — interpolar em 3D contínuo criaria estrutura que o dado não sustenta.
  · IDW, e não krigagem: com poucas dezenas de pontos por talhão não há suporte
    amostral para um variograma confiável.
  · A validação leave-one-out diz quanto o mapa pode ser lido como valor pontual.
    r baixo = leia zonas, não pixels. E o r precisa ser medido por profundidade:
    agrupando todas, o gradiente vertical (comum a todos os perfis) infla o número.
  · Limiares padrão: 1500 kPa (restrição incipiente) e 2500 kPa (francamente
    restritivo), para solo com umidade próxima à capacidade de campo.
"""

import json
import os
import re
import unicodedata
import warnings
import xml.etree.ElementTree as ET
from datetime import date

import numpy as np
import pandas as pd
from pyproj import Transformer
from shapely.affinity import translate
from shapely.geometry import Point, Polygon
from shapely.prepared import prep

# ─────────────────────────────────────────────────────────────── configuração ──
UTM_EPSG   = 31982    # SIRGAS 2000 / UTM 22S (Guarapuava-PR). 21S=31981, 23S=31983
RES_M      = 12.0     # resolução horizontal da grade, em metros
IDW_POWER  = 2.0      # potência do inverso da distância
TOL_BORDA  = 30.0     # m — ponto fora do polígono, mas a até esta distância, é "borda"
MIN_PONTOS = 3        # mínimo de perfis para interpolar um talhão
LIM_MOD    = 1500     # kPa — restrição incipiente
LIM_CRIT   = 2500     # kPa — francamente restritivo
CMAX_KPA   = 3500     # kPa — saturação da escala de cor
CAMADAS    = [('0-10', 0, 10), ('10-20', 10, 20), ('20-40', 20, 40), ('40-60', 40, 60)]
FATIAS_CM  = [10, 20, 30, 45]

# densidade (pontos/ha) a partir da qual cada uso se sustenta — ver penetro3d_amostragem
DENS_CARACTERIZAR = 1.0
DENS_ZONEAR = 2.0
DENS_PRECISAO = 3.5

# rampa de cor: verde (baixo) → âmbar (moderado) → vermelho (restritivo). O piso
# não é quase-branco de propósito: a 19% de opacidade no volume 3D, um piso claro
# demais some e parece que a camada superficial não foi desenhada.
RAMPA = [[0, '#C7E4AC'], [0.20, '#93CB63'], [0.42, '#5FB63C'], [0.52, '#E8C33A'],
         [0.66, '#F7A823'], [0.714, '#EE3124'], [0.85, '#B5201A'], [1, '#6E120E']]

AQUI = os.path.dirname(os.path.abspath(__file__))
# ícone do programa embutido no relatório (aba do navegador); gerado de app/icone.svg
FAVICON = ('data:image/svg+xml;base64,'
           'PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA2NCA2NCI+CiAgPGRlZnM+PGNsaXBQYXRoIGlkPSJoeCI+PHBvbHlnb24gcG9pbnRzPSIzMiwzIDU3LjEsMTcuNSA1Ny4xLDQ2LjUgMzIsNjEgNi45LDQ2LjUgNi45LDE3LjUiLz48L2NsaXBQYXRoPjwvZGVmcz4KICA8ZyBjbGlwLXBhdGg9InVybCgjaHgpIj4KICAgIDxyZWN0IHdpZHRoPSI2NCIgaGVpZ2h0PSIyNSIgZmlsbD0iIzcyQkY0NCIvPgogICAgPHJlY3QgeT0iMjUiIHdpZHRoPSI2NCIgaGVpZ2h0PSIxOCIgZmlsbD0iI0Y3QTgyMyIvPgogICAgPHJlY3QgeT0iNDMiIHdpZHRoPSI2NCIgaGVpZ2h0PSIyMSIgZmlsbD0iI0VFMzEyNCIvPgogIDwvZz4KICA8cGF0aCBkPSJNMjUgMTAgQyAyNiAyMiwgNDYgMjEsIDQ1LjUgMzIgQyA0NSA0MiwgMzIgNDUsIDMxIDU0IiBmaWxsPSJub25lIiBzdHJva2U9IiNGRkZGRkYiIHN0cm9rZS13aWR0aD0iNSIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIi8+Cjwvc3ZnPg==')
PLOTLY_CDN = ('<script src="https://cdnjs.cloudflare.com/ajax/libs/'
              'plotly.js/2.35.2/plotly.min.js"></script>')


class ErroDeDados(Exception):
    """Problema nos arquivos de entrada — mensagem destinada ao usuário final."""


# ─────────────────────────────────────────────────────────────────── utilidades ──
def num_br(v, casas=0):
    """Formata número no padrão pt-BR: 1.234,5"""
    return f'{v:,.{casas}f}'.replace(',', '\x00').replace('.', ',').replace('\x00', '.')


def num_cm(v):
    """Profundidade em cm: casa decimal só quando existe (52,5 cm; 60 cm)."""
    v = float(v)
    return num_br(v, 0 if v.is_integer() else 1)


def slug(txt, maxlen=60):
    """Nome de arquivo seguro a partir de um texto qualquer."""
    txt = unicodedata.normalize('NFKD', str(txt))
    txt = ''.join(c for c in txt if not unicodedata.combining(c))
    txt = re.sub(r'[^A-Za-z0-9._-]+', '_', txt).strip('_')
    return txt[:maxlen] or 'talhao'


def _norm(s):
    """Remove acentos e caixa, para casar rótulos do Falker com/sem acentuação."""
    s = unicodedata.normalize('NFKD', str(s))
    return ''.join(c for c in s if not unicodedata.combining(c)).strip().lower()


# ──────────────────────────────────────────────────────────────────── leitura KML ──
def _anel(txt):
    """Texto de <coordinates> → [(lon, lat), ...]."""
    pares = []
    for c in txt.split():
        p = c.split(',')
        if len(p) >= 2:
            try:
                pares.append((float(p[0]), float(p[1])))
            except ValueError:
                return []
    return pares


def _tag(el):
    """Nome da tag sem o namespace (KML usa xmlns, e nem sempre o mesmo)."""
    return el.tag.rsplit('}', 1)[-1]


def carregar_talhoes(caminhos_kml):
    """Lê os KML e devolve [{'nome', 'arquivo', 'anel', 'ilhas'}] — um item por polígono.

    Percorre o XML de verdade (e não por expressão regular), porque o Google Earth
    escreve <Placemark id="..."> e agrupa geometrias em <MultiGeometry> e <Folder>.
    Ler isso com regex faz um KML de vários talhões virar um só, silenciosamente.
    Buracos (<innerBoundaryIs>) são preservados e recortados da área.
    """
    talhoes = []
    for caminho in caminhos_kml:
        base = os.path.splitext(os.path.basename(caminho))[0]
        try:
            raiz = ET.parse(caminho).getroot()
        except (ET.ParseError, OSError) as e:
            raise ErroDeDados(f'Não consegui interpretar {os.path.basename(caminho)} '
                              f'como KML: {e}')

        marcas = [el for el in raiz.iter() if _tag(el) == 'Placemark'] or [raiz]
        achou = 0
        for i, marca in enumerate(marcas):
            nome_el = next((f for f in marca if _tag(f) == 'name'), None)
            nome = (nome_el.text or '').strip() if nome_el is not None else ''

            poligonos = [el for el in marca.iter() if _tag(el) == 'Polygon'] or \
                        [el for el in marca.iter() if _tag(el) == 'LinearRing']
            for j, pol in enumerate(poligonos):
                fora, dentro = None, []
                for cont in pol.iter():
                    t = _tag(cont)
                    if t not in ('outerBoundaryIs', 'innerBoundaryIs'):
                        continue
                    coord = next((e for e in cont.iter() if _tag(e) == 'coordinates'), None)
                    if coord is None or not coord.text:
                        continue
                    anel = _anel(coord.text)
                    if len(anel) < 4:
                        continue
                    if t == 'outerBoundaryIs':
                        fora = anel
                    else:
                        dentro.append(anel)
                if fora is None:                      # LinearRing solto
                    coord = next((e for e in pol.iter() if _tag(e) == 'coordinates'), None)
                    fora = _anel(coord.text) if (coord is not None and coord.text) else []
                if len(fora) < 4:
                    continue

                rot = nome or base
                if len(poligonos) > 1:
                    rot = f'{rot} ({j + 1})'
                elif not nome and len(marcas) > 1:
                    rot = f'{base}_{i + 1}'
                talhoes.append({'nome': rot, 'arquivo': os.path.basename(caminho),
                                'anel': fora, 'ilhas': dentro})
                achou += 1
        if not achou:
            raise ErroDeDados(f'{os.path.basename(caminho)} não contém um polígono válido '
                              f'(nenhum anel com 4 ou mais vértices).')
    if not talhoes:
        raise ErroDeDados('Nenhum talhão foi lido dos arquivos KML selecionados.')

    # nomes repetidos gravariam na mesma pasta e um sobrescreveria o outro
    vistos = {}
    for t in talhoes:
        chave = slug(t['nome'])
        vistos[chave] = vistos.get(chave, 0) + 1
        if vistos[chave] > 1:
            t['nome'] = f"{t['nome']} #{vistos[chave]}"
    return talhoes


# ───────────────────────────────────────────────────────────── leitura do Falker ──
def ler_falker(caminho):
    """Lê o export do Falker PenetroLOG / Falker Compact.

    Layout: rótulos na coluna 0 ('Medição', 'Latitude', 'Longitude', 'Data'…), uma
    coluna por medição a partir da coluna 2; abaixo da célula 'Profundidade (cm)'
    (coluna 1) vem o bloco de leituras, uma linha por profundidade.

    Retorna (df_pontos, profundidades, CI[n_prof, n_pontos], data_coleta, avisos).
    """
    nome = os.path.basename(caminho)
    try:
        df = pd.read_excel(caminho, header=None)
    except Exception as e:                                         # noqa: BLE001
        raise ErroDeDados(f'Não consegui ler a planilha {nome}: {e}')

    rot = df[0].map(_norm)
    avisos = []

    def linha(rotulo, obrigatorio=True):
        alvo = rot[rot == _norm(rotulo)]
        if alvo.empty:
            if obrigatorio:
                raise ErroDeDados(f'A planilha {nome} não parece ser um export do Falker: '
                                  f'não encontrei a linha "{rotulo}".')
            return None
        return alvo.index[0]

    ids = df.iloc[linha('Medição'), 2:].tolist()
    lat = pd.to_numeric(df.iloc[linha('Latitude'), 2:], errors='coerce').to_numpy(float)
    lon = pd.to_numeric(df.iloc[linha('Longitude'), 2:], errors='coerce').to_numpy(float)

    l_data = linha('Data', obrigatorio=False)
    datas = (df.iloc[l_data, 2:].dropna().astype(str).tolist()
             if l_data is not None else [])

    marca = df[1].map(_norm).str.contains('profundidade', na=False)
    if not marca.any():
        raise ErroDeDados(f'Não encontrei o bloco "Profundidade (cm)" em {nome}.')
    i = int(np.argmax(marca.to_numpy())) + 1

    prof, leituras = [], []
    while i < len(df):
        try:
            p = float(df.iloc[i, 1])
        except (TypeError, ValueError):
            break
        if not np.isfinite(p):
            break
        prof.append(p)
        leituras.append(pd.to_numeric(df.iloc[i, 2:], errors='coerce').to_numpy(float))
        i += 1
    if len(prof) < 2:
        raise ErroDeDados(f'Nenhuma leitura de profundidade foi lida de {nome}.')

    CI = np.array(leituras, float)
    prof = np.array(prof, float)
    fin = np.isfinite(CI)

    ok = np.isfinite(lat) & np.isfinite(lon) & fin.any(axis=0)
    if not ok.any():
        raise ErroDeDados(f'Em {nome}, nenhum perfil tem coordenada e ao menos uma leitura.')
    if (~ok).any():
        avisos.append(f'{int((~ok).sum())} perfil(is) sem coordenada ou sem nenhuma '
                      f'leitura, descartado(s)')

    # Um perfil que parou antes (no Falker, "Medição completa: Não") não deve custar
    # suas leituras válidas. A profundidade da análise é cortada onde TODOS os perfis
    # mantidos ainda têm leitura; se esse corte for fundo demais, é mais barato
    # descartar os poucos perfis rasos do que encurtar o talhão inteiro.
    def _profundidade_comum(sel):
        val = fin[:, sel].all(axis=1)
        return int(np.argmin(val)) if not val.all() else len(val)

    k = _profundidade_comum(ok)
    if k < len(prof):
        minimo = int(np.ceil(0.75 * len(prof)))
        if k < minimo:
            rasos = ok & (fin.sum(axis=0) < minimo)
            if rasos.any() and (ok & ~rasos).sum() >= MIN_PONTOS:
                avisos.append(f'{int(rasos.sum())} perfil(is) interrompido(s) cedo demais, '
                              f'descartado(s): '
                              + ', '.join(str(ids[i]) for i in np.where(rasos)[0]))
                ok = ok & ~rasos
                k = _profundidade_comum(ok)
        if k < len(prof):
            avisos.append(f'análise limitada a {num_br(prof[k - 1], 1)} cm: nem todos os '
                          f'perfis chegaram a {num_br(prof[-1], 1)} cm')
    if k < 2:
        raise ErroDeDados(f'Em {nome}, os perfis não têm profundidades em comum suficientes.')

    pontos = pd.DataFrame({'id': [str(v) for v in np.array(ids, dtype=object)[ok]],
                           'lat': lat[ok], 'lon': lon[ok]}).reset_index(drop=True)
    data_coleta = max(set(datas), key=datas.count) if datas else ''
    return pontos, prof[:k], CI[:k][:, ok], data_coleta, avisos


# ─────────────────────────────────────────────────────── geometria e projeção ──
def _projetar(anel, ilhas, tr):
    """Anel externo + buracos em lon/lat → polígono métrico já com os vazios recortados."""
    fx, fy = tr.transform([c[0] for c in anel], [c[1] for c in anel])
    buracos = []
    for il in ilhas or []:
        ix, iy = tr.transform([c[0] for c in il], [c[1] for c in il])
        buracos.append(list(zip(ix, iy)))
    g = Polygon(list(zip(fx, fy)), buracos)
    return g if g.is_valid else g.buffer(0)


def aneis(poli):
    """Todos os anéis de um polígono (externo + buracos), para desenho."""
    if poli.geom_type == 'MultiPolygon':
        poli = max(poli.geoms, key=lambda g: g.area)
    return [list(zip(*poli.exterior.xy))] + [list(zip(*i.xy)) for i in poli.interiors]


def epsg_sugerido(talhoes):
    """EPSG métrico SIRGAS 2000 / UTM deduzido da longitude média dos talhões.

    Evita que o usuário tenha de saber o fuso: o KML já diz onde o talhão está.
    Zonas 18S–25S cobrem o Brasil (EPSG 31978–31985).
    """
    lons, lats = [], []
    for t in talhoes:
        for lon, lat in t['anel']:
            lons.append(lon); lats.append(lat)
    if not lons:
        return UTM_EPSG, 'não deduzido'
    lon_m, lat_m = float(np.mean(lons)), float(np.mean(lats))
    fuso = int((lon_m + 180) // 6) + 1
    if not (18 <= fuso <= 25):
        return UTM_EPSG, f'fuso {fuso} fora do Brasil — confira'
    if lat_m >= 0:
        return UTM_EPSG, 'talhão no hemisfério norte — confira'
    return 31960 + fuso, f'UTM {fuso}S (deduzido do KML)'


# ─────────────────────────────────────────────────────── atribuição aos talhões ──
def atribuir_pontos(pontos, talhoes, epsg, tol_m=TOL_BORDA):
    """Descobre em qual talhão cai cada ponto.

    Devolve um array de índices (−1 = nenhum talhão) e um array de situação
    ('interno', 'borda', 'fora'). Um ponto fora de todos os polígonos mas a até
    `tol_m` metros de um deles é atribuído a esse como 'borda' — GPS de campo erra
    alguns metros, e um perfil de borda ainda restringe a interpolação.
    """
    tr = Transformer.from_crs('EPSG:4326', f'EPSG:{epsg}', always_xy=True)
    px, py = tr.transform(pontos.lon.values, pontos.lat.values)
    geoms = [_projetar(t['anel'], t.get('ilhas'), tr) for t in talhoes]

    idx = np.full(len(pontos), -1, int)
    sit = np.array(['fora'] * len(pontos), dtype=object)
    for i, (a, b) in enumerate(zip(px, py)):
        p = Point(a, b)
        dentro = [j for j, g in enumerate(geoms) if g.contains(p)]
        if dentro:
            idx[i], sit[i] = dentro[0], 'interno'
        else:
            dists = [g.distance(p) for g in geoms]
            j = int(np.argmin(dists))
            if dists[j] <= tol_m:
                idx[i], sit[i] = j, 'borda'
    return idx, sit


# ──────────────────────────────────────────────────────────────  interpolação ──
def interpolar(pontos, CI, anel_ll, epsg=UTM_EPSG, res_m=RES_M, ilhas_ll=None):
    """IDW camada a camada dentro do polígono. Devolve grade, máscara e validação."""
    tr = Transformer.from_crs('EPSG:4326', f'EPSG:{epsg}', always_xy=True)
    poli = _projetar(anel_ll, ilhas_ll, tr)
    x0, y0 = poli.centroid.x, poli.centroid.y            # origem local, em metros
    poli = translate(poli, -x0, -y0)                     # translate preserva os buracos

    sx, sy = tr.transform(pontos.lon.values, pontos.lat.values)
    sx, sy = np.asarray(sx) - x0, np.asarray(sy) - y0
    dentro = np.array([poli.contains(Point(a, b)) for a, b in zip(sx, sy)])

    minx, miny, maxx, maxy = poli.bounds
    gx = np.arange(minx, maxx + res_m, res_m)
    gy = np.arange(miny, maxy + res_m, res_m)
    GX, GY = np.meshgrid(gx, gy)

    pr = prep(poli)
    mask = np.array([[pr.contains(Point(a, b)) for a, b in zip(rx, ry)]
                     for rx, ry in zip(GX, GY)])
    if not mask.any():
        raise ErroDeDados('Nenhuma célula da grade caiu dentro do polígono — confira o EPSG '
                          'e a resolução da grade.')

    # os pesos IDW só dependem da geometria: calcula uma vez, aplica a todas as camadas
    D = np.sqrt((GX[..., None] - sx) ** 2 + (GY[..., None] - sy) ** 2)
    W = 1.0 / np.maximum(D, 1.0) ** IDW_POWER
    W /= W.sum(axis=2, keepdims=True)
    VOL = np.einsum('yxp,dp->dyx', W, CI)                # (n_prof, ny, nx)
    VOL[:, ~mask] = np.nan

    # validação cruzada leave-one-out nos próprios pontos amostrados
    if len(sx) > 2:
        Dp = np.sqrt((sx[:, None] - sx) ** 2 + (sy[:, None] - sy) ** 2)
        Wp = 1.0 / np.maximum(Dp, 1.0) ** IDW_POWER
        np.fill_diagonal(Wp, 0.0)
        Wp /= Wp.sum(axis=1, keepdims=True)
        pred = CI @ Wp.T
        rmse = float(np.sqrt(np.nanmean((pred - CI) ** 2)))
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            r = float(np.corrcoef(pred.ravel(), CI.ravel())[0, 1])
            # r agrupado é otimista: parte da correlação vem só do gradiente
            # vertical, comum a todos os perfis. O r POR profundidade isola a
            # habilidade horizontal — que é a única coisa que o mapa acrescenta.
            rk = np.array([np.corrcoef(pred[k], CI[k])[0, 1]
                           for k in range(CI.shape[0])], float)
        r_horiz = float(np.nanmedian(rk)) if np.isfinite(rk).any() else float('nan')
        frac_neg = float(np.nanmean(rk < 0)) if np.isfinite(rk).any() else float('nan')
    else:
        rmse = r = r_horiz = frac_neg = float('nan')

    return dict(gx=gx, gy=gy, VOL=VOL, mask=mask, poli=poli, sx=sx, sy=sy, dentro=dentro,
                area_ha=poli.area / 1e4, rmse=rmse, r=r, r_horiz=r_horiz,
                frac_neg=frac_neg, epsg=epsg, res_m=res_m, origem=(x0, y0))


def resumo(prof, VOL, mask, camadas):
    """Estatísticas por camada + espessura e profundidade da restrição."""
    out, medias = {}, {}
    for chave, a, b in camadas:
        sel = (prof > a) & (prof <= b)
        if not sel.any():
            continue
        with warnings.catch_warnings():          # colunas fora do polígono são só NaN
            warnings.simplefilter('ignore', RuntimeWarning)
            m = np.nanmean(VOL[sel], axis=0)
        medias[chave] = m
        v = m[mask]
        out[chave] = dict(media=round(float(v.mean())),
                          baixo=round(float((v < LIM_MOD).mean() * 100)),
                          mod=round(float(((v >= LIM_MOD) & (v < LIM_CRIT)).mean() * 100)),
                          rest=round(float((v >= LIM_CRIT).mean() * 100)))
    passo = float(np.diff(prof)[0]) if len(prof) > 1 else 1.0
    acima = np.where(np.isnan(VOL), False, VOL > LIM_CRIT)
    esp = acima.sum(axis=0) * passo
    zmax = prof[np.argmax(np.where(np.isnan(VOL), -1, VOL), axis=0)].astype(float)
    esp = np.where(mask, esp, np.nan)          # fora do polígono não existe valor
    zmax = np.where(mask, zmax, np.nan)
    e = esp[mask]
    out['restritiva_area'] = round(float((e > 0).mean() * 100))
    out['restritiva_esp'] = round(float(e[e > 0].mean()), 1) if (e > 0).any() else 0.0
    out['zmax_mediana'] = float(np.median(zmax[mask]))
    # a espessura soma todas as leituras acima do limite, contíguas ou não: pode ser
    # uma camada só ou duas separadas, e isso muda a decisão de manejo
    x = np.concatenate([np.zeros((1,) + acima.shape[1:], bool), acima])
    blocos = ((~x[:-1]) & x[1:]).sum(axis=0)
    sel = mask & (np.nan_to_num(esp) > 0)
    out['restritiva_partida'] = (round(float((blocos[sel] > 1).mean() * 100))
                                 if sel.any() else 0)
    return out, medias, esp, zmax


def validar_camadas(prof, CI, sx, sy, camadas):
    """Leave-one-out POR CAMADA: o mapa interpolado ajuda ou atrapalha?

    Compara o IDW contra a alternativa mais simples possível — usar a média do talhão
    naquela camada. Se o RMSE do IDW não for menor, o desenho horizontal das manchas
    não tem suporte no dado e o mapa deve ser lido como "quanto", não como "onde".
    """
    n = len(sx)
    if n < 4:
        return {}
    D = np.sqrt((sx[:, None] - sx) ** 2 + (sy[:, None] - sy) ** 2)
    W = 1.0 / np.maximum(D, 1.0) ** IDW_POWER
    np.fill_diagonal(W, 0.0)
    W /= W.sum(axis=1, keepdims=True)

    out = {}
    for chave, a, b in camadas:
        sel = (prof > a) & (prof <= b)
        if not sel.any():
            continue
        v = CI[sel].mean(axis=0)
        pred = W @ v
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            r = float(np.corrcoef(pred, v)[0, 1])
        rmse_idw = float(np.sqrt(((pred - v) ** 2).mean()))
        rmse_media = float(np.sqrt(((v.mean() - v) ** 2).mean()))
        ganho = (rmse_media - rmse_idw) / rmse_media * 100 if rmse_media else 0.0
        out[chave] = {'r': round(r, 3) if np.isfinite(r) else None,
                      'rmse_idw': round(rmse_idw), 'rmse_media': round(rmse_media),
                      'ganho_pct': round(ganho, 1),
                      'suporte': bool(rmse_idw < rmse_media)}
    return out


def rotulo_suporte(v):
    """Texto curto para carimbar no mapa daquela camada."""
    if not v:
        return ('', '')
    r = num_br(v['r'], 2) if v.get('r') is not None else '—'
    if v['suporte']:
        return ('com suporte espacial',
                f"interpolar reduz o erro em {num_br(v['ganho_pct'], 0)}% "
                f"ante usar a média do talhão (r = {r})")
    return ('sem suporte espacial — leia a média, não as manchas',
            f"interpolar aumenta o erro em {num_br(abs(v['ganho_pct']), 0)}% "
            f"ante usar a média do talhão (r = {r})")


def medidas_por_ponto(pontos, prof, CI, camadas, situacao=None):
    """Tabela do dado MEDIDO (sem interpolação), uma linha por perfil."""
    linhas = []
    for i in range(len(pontos)):
        reg = {'ponto': str(pontos.id.iloc[i]),
               'lat': float(pontos.lat.iloc[i]), 'lon': float(pontos.lon.iloc[i]),
               'situacao': (situacao[i] if situacao is not None else '')}
        for chave, a, b in camadas:
            sel = (prof > a) & (prof <= b)
            reg[chave] = float(CI[sel, i].mean()) if sel.any() else float('nan')
        k = int(np.argmax(CI[:, i]))
        reg['rp_max'] = float(CI[k, i])
        reg['prof_rp_max'] = float(prof[k])
        reg['rp_media'] = float(CI[:, i].mean())
        linhas.append(reg)
    return pd.DataFrame(linhas)


def detectar_outliers(pontos, prof, CI, fator=1.8):
    """Perfis cuja RP máxima destoa do conjunto (possível pedra ou impedimento pontual)."""
    if len(pontos) < 4:
        return []
    pmax = CI.max(axis=0)
    ref = np.percentile(pmax, 75)
    return [(str(pontos.id.iloc[i]), float(pmax[i]), float(prof[int(np.argmax(CI[:, i]))]))
            for i in np.where(pmax > fator * ref)[0]]


# ────────────────────────────────────────────────────────────── relatório HTML ──
def _grade(a):
    """Matriz numpy → lista de listas com None no lugar de NaN (JSON-safe)."""
    return [[None if not np.isfinite(v) else int(round(v)) for v in linha] for linha in a]


def montar_payload(ctx, pontos, prof, CI, R, S, medias, camadas, fatias, V=None):
    """Empacota tudo o que a página HTML precisa, incluindo as notas de método."""
    fora = [str(pontos.id.iloc[i]) for i in range(len(pontos)) if not R['dentro'][i]]
    outl = detectar_outliers(pontos, prof, CI)
    n, npf = len(pontos), len(prof)
    area = num_br(R['area_ha'], 2)

    notas = [
        f"<b>Georreferenciamento.</b> Polígono do KML e coordenadas dos perfis projetados "
        f"para <code>EPSG:{R['epsg']}</code>; eixos em metros a partir do centroide do "
        f"talhão. Área calculada do polígono: <b>{area} ha</b>.",

        f"<b>Interpolação.</b> IDW (inverso da distância ao quadrado, "
        f"<code>p = {IDW_POWER:g}</code>) aplicado <b>camada a camada</b> — cada uma das "
        f"{npf} profundidades é interpolada no plano de forma independente, sem mistura "
        f"vertical. Grade de {num_br(R['res_m'])} m recortada pelo polígono "
        f"({int(R['mask'].sum())} células).",
    ]

    if np.isfinite(R['rmse']):
        rh, fn = R['r_horiz'], R['frac_neg']
        base = (f"<b>Validação cruzada leave-one-out.</b> RMSE = {num_br(R['rmse'])} kPa e "
                f"r = {num_br(R['r'], 3)} somando as {n * npf} leituras. Esse r agrupado é "
                f"otimista: boa parte dele vem do gradiente vertical, que é comum a todos "
                f"os perfis e que o mapa não precisa prever. Isolando cada profundidade — "
                f"que é onde a interpolação horizontal de fato trabalha — a mediana do r "
                f"cai para <span class='flag'>{num_br(rh, 3)}</span>, com "
                f"{num_br(fn * 100)}% das profundidades em correlação negativa.")
        if rh < 0.3:
            base += (" <span class='flag'>Na prática, com esta densidade de amostragem o "
                     "desenho horizontal das manchas não se sustenta: em boa parte das "
                     "profundidades, prever pelos vizinhos não é melhor do que usar a média "
                     "do talhão.</span> Leia deste relatório o que é robusto — o perfil "
                     "médio, a profundidade da restrição e a ordem de grandeza da "
                     "resistência — e trate a posição exata das manchas como hipótese a "
                     "verificar, não como mapa de aplicação. Para zoneamento de "
                     "intervenção, adensar a malha (uma referência usual é 1 ponto/ha ou "
                     "mais) antes de decidir onde escarificar.")
        else:
            base += (" O mapa descreve zonas amplas, não valores pontuais. Para intervenção "
                     "localizada, adensar a malha nas manchas destacadas.")
        notas.append(base)

    if outl:
        desc = '; '.join(f'perfil {i} com {num_br(v)} kPa a {num_br(d, 1)} cm'
                         for i, v, d in outl)
        notas.append(
            f"<b>Escala de cor saturada em {num_br(CMAX_KPA)} kPa.</b> Valores muito acima "
            f"do conjunto foram detectados ({desc}) — compatível com pedra, cascalho ou "
            f"impedimento pontual. O dado foi mantido na interpolação, mas a escala satura "
            f"para não achatar visualmente o restante do talhão. <span class='flag'>Vale "
            f"reamostrar esse(s) ponto(s) antes de qualquer conclusão.</span>")
    else:
        notas.append(f"<b>Escala de cor saturada em {num_br(CMAX_KPA)} kPa.</b> Nenhum "
                     f"perfil destoou do conjunto a ponto de sugerir impedimento pontual.")

    if fora:
        notas.append(
            f"<b>Perfil(is) na borda.</b> {', '.join(fora)} — as coordenadas caem fora do "
            f"contorno do KML, dentro da tolerância de "
            f"{num_br(ctx.get('tol_borda', TOL_BORDA))} m adotada. Foram mantidos porque "
            f"restringem a borda da interpolação, mas estão sinalizados em cinza nos mapas. "
            f"Vale conferir o GPS ou o desenho do talhão.")

    if S.get('restritiva_partida'):
        notas.append(
            f"<b>A espessura restritiva é somada, não necessariamente contígua.</b> Em "
            f"{S['restritiva_partida']}% da área com restrição, as leituras acima de "
            f"{num_br(LIM_CRIT)} kPa aparecem em <b>mais de um bloco separado</b> ao longo "
            f"do perfil — não é uma camada única a romper. Confira os perfis ponto a ponto "
            f"antes de definir a profundidade de trabalho do escarificador.")

    if V:
        com = [c for c, v in V.items() if v['suporte']]
        sem = [c for c, v in V.items() if not v['suporte']]
        det = '; '.join(
            f"{c} cm: r = {num_br(v['r'], 2) if v['r'] is not None else '—'}, "
            f"{'reduz' if v['suporte'] else 'aumenta'} o erro em "
            f"{num_br(abs(v['ganho_pct']), 0)}%" for c, v in V.items())
        txt = (f"<b>O mapa não vale igual em todas as profundidades.</b> Testando cada "
               f"camada contra a alternativa mais simples — usar a média do talhão — "
               f"{det}. ")
        if sem and com:
            txt += (f"<span class='flag'>Nas camadas de {', '.join(sem)} cm o desenho das "
                    f"manchas não tem suporte: interpolar piora a estimativa. Leia a média, "
                    f"não o mapa.</span> Em {', '.join(com)} cm o mapa acrescenta "
                    f"informação.")
        elif sem:
            txt += ("<span class='flag'>Em nenhuma camada a interpolação superou a média do "
                    "talhão. Este relatório descreve o perfil vertical; o desenho "
                    "horizontal é hipótese.</span>")
        else:
            txt += "Todas as camadas ganham com a interpolação."
        notas.append(txt)

    notas.append(
        "<b>Umidade não registrada.</b> A resistência à penetração depende fortemente do "
        "teor de água no momento da leitura. Sem a umidade gravimétrica das camadas, os "
        f"limiares de {num_br(LIM_MOD)} e {num_br(LIM_CRIT)} kPa são referências, não "
        "diagnóstico fechado.")

    meta = [('Área', f'{area} ha'), ('Perfis', str(n)),
            ('Profundidade', f'{num_cm(prof.min())}–{num_cm(prof.max())} cm '
                             f'({npf} leituras/perfil)'),
            ('Grade', f'{num_br(R["res_m"])} × {num_br(R["res_m"])} m')]
    if ctx.get('data_coleta'):
        meta.insert(2, ('Amostragem', ctx['data_coleta']))

    from penetro3d_versao import AUTOR, VERSAO
    return {
        'meta': {
            'eyebrow': f"{ctx['projeto']} · penetrometria",
            'titulo': f"Compactação do solo — {ctx['talhao']}",
            'lede': (f"Bloco tridimensional de resistência do solo à penetração interpolado "
                     f"a partir de {n} perfis verticais amostrados a cada "
                     f"{num_br(np.diff(prof)[0], 1)} cm até {num_cm(prof.max())} cm de "
                     f"profundidade, recortado pelo contorno do talhão."),
            'meta': meta,
            'nota_limiares': (f'Valores em kPa. Classes segundo os limiares agronômicos '
                              f'usuais: ~{LIM_MOD} kPa marca o início da restrição ao '
                              f'crescimento radicular e ~{LIM_CRIT} kPa a condição '
                              f'francamente restritiva, em solo com umidade próxima à '
                              f'capacidade de campo.'),
            'rodape': (f"Projeto {ctx['projeto']} · fonte: {ctx['arquivo_kml']} e "
                        f"{ctx['arquivo_xlsx']}. Gerado pelo Penetro3D {VERSAO} em "
                        f"{date.today().strftime('%d/%m/%Y')} · Autoria: {AUTOR}"),
        },
        'limiares': {'mod': LIM_MOD, 'crit': LIM_CRIT, 'cmax': CMAX_KPA},
        'rampa': RAMPA,
        'x': [round(float(v), 1) for v in R['gx']],
        'y': [round(float(v), 1) for v in R['gy']],
        'z': [float(v) for v in prof],
        'vol': [_grade(R['VOL'][k]) for k in range(len(prof))],
        'layers': {c: _grade(m) for c, m in medias.items()},
        'camadas': [{'chave': c, 'rotulo': f'{a} – {b} cm'}
                    for c, a, b in camadas if c in medias],
        'fatias': fatias,
        'maxvalor': float(np.nanmax(R['VOL'])),
        'poly': [[[round(a, 1), round(b, 1)] for a, b in anel] for anel in aneis(R['poli'])],
        'pontos': [{'id': str(pontos.id.iloc[i]), 'x': round(float(R['sx'][i]), 1),
                    'y': round(float(R['sy'][i]), 1), 'lat': float(pontos.lat.iloc[i]),
                    'lon': float(pontos.lon.iloc[i]), 'dentro': bool(R['dentro'][i]),
                    'ci': [int(round(v)) for v in CI[:, i]]} for i in range(len(pontos))],
        'stats': S,
        'validacao': {k: {**v, 'rotulo': rotulo_suporte(v)[0],
                          'detalhe': rotulo_suporte(v)[1]}
                      for k, v in (V or {}).items()},
        'notas': notas,
    }


def _plotly_js():
    """O plotly.js, na ordem: arquivo junto do programa → pacote plotly → None.

    O instalador traz só o plotly.min.js (3,5 MB) em vez do pacote plotly inteiro
    (~50 MB de validadores Python que o Penetro3D nunca usa).
    """
    for alvo in (os.path.join(AQUI, 'vendor', 'plotly.min.js'),):
        if os.path.isfile(alvo):
            with open(alvo, encoding='utf-8') as f:
                return f.read()
    try:
        from plotly.offline import get_plotlyjs
        return get_plotlyjs()
    except ImportError:
        return None


def render_html(payload, offline=True):
    """Injeta o payload no template e devolve o documento HTML completo."""
    with open(os.path.join(AQUI, 'relatorio_template.html'), encoding='utf-8') as f:
        template = f.read()
    js = _plotly_js() if offline else None
    plotly_tag = f'<script>{js}</script>' if js else PLOTLY_CDN
    dados = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
    dados = dados.replace('</', '<\\/')          # nunca fechar o <script> por acidente
    corpo = (template
             .replace('__PLOTLY__', plotly_tag)
             .replace('__TITULO_CURTO__', payload['meta']['titulo'])
             .replace('__DATA__', dados))
    return ('<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<link rel="icon" type="image/svg+xml" href="{FAVICON}">'
            '<style>body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style>'
            '</head><body>' + corpo + '</body></html>')


# ──────────────────────────────────────────────── conferência antes de processar ──
NIVEL_OK, NIVEL_ATENCAO, NIVEL_ERRO = 'ok', 'atencao', 'erro'


def confiabilidade(dens):
    """Traduz densidade amostral no que o resultado permite afirmar."""
    if dens >= DENS_PRECISAO:
        return ('alta', 'Suporta variograma, krigagem e mapa de prescrição.')
    if dens >= DENS_ZONEAR:
        return ('media', 'Suporta zoneamento em áreas amplas. Não suporta prescrição fina.')
    if dens >= DENS_CARACTERIZAR:
        return ('baixa', 'Suporta o diagnóstico do talhão (perfil médio, profundidade da '
                         'restrição). O desenho das manchas no mapa é hipótese.')
    return ('insuficiente', 'Abaixo de 1 ponto/ha: nem a média das camadas fica bem '
                            'estimada. Trate o resultado como sondagem exploratória.')


def conferencia(caminhos_kml, caminho_xlsx, epsg=UTM_EPSG, tol_borda=TOL_BORDA):
    """Diagnóstico dos arquivos antes de processar. Nada aqui escreve arquivo.

    Devolve {'achados': [...], 'talhoes': [...], 'pode_prosseguir': bool}. Cada achado
    tem nível, título, detalhe e — quando existe — uma ação sugerida ao usuário.
    """
    achados = []
    add = lambda n, t, d, a=None: achados.append(                      # noqa: E731
        {'nivel': n, 'titulo': t, 'detalhe': d, 'acao': a})

    talhoes = carregar_talhoes(caminhos_kml)
    pontos, prof, CI, data_coleta, avisos = ler_falker(caminho_xlsx)
    for a in avisos:
        add(NIVEL_ATENCAO, 'Leitura da planilha', a)

    idx, sit = atribuir_pontos(pontos, talhoes, epsg, tol_borda)

    orfaos = [str(pontos.id.iloc[i]) for i in np.where(idx < 0)[0]]
    if orfaos:
        add(NIVEL_ATENCAO, f'{len(orfaos)} ponto(s) fora de todos os talhões',
            f"Perfis {', '.join(orfaos)} não caem em nenhum polígono nem dentro da "
            f"tolerância de {num_br(tol_borda)} m.",
            'Aumente a tolerância de borda, revise o KML, ou siga sem eles — vão para '
            'pontos_nao_atribuidos.csv.')

    borda = [str(pontos.id.iloc[i]) for i in range(len(pontos)) if sit[i] == 'borda']
    if borda:
        add(NIVEL_ATENCAO, f'{len(borda)} ponto(s) na borda',
            f"Perfis {', '.join(borda)} caíram fora do polígono, dentro da tolerância. "
            f"Serão usados, marcados em cinza nos mapas.")

    for i, v, d in detectar_outliers(pontos, prof, CI):
        add(NIVEL_ATENCAO, f'Perfil {i}: resistência fora do padrão',
            f'{num_br(v)} kPa a {num_br(d, 1)} cm, muito acima do conjunto — compatível '
            f'com pedra, cascalho ou impedimento pontual.',
            'Reamostrar esse ponto é mais barato do que descobrir depois.')

    tr = Transformer.from_crs('EPSG:4326', f'EPSG:{epsg}', always_xy=True)
    resumo_talhoes = []
    for j, t in enumerate(talhoes):
        n = int((idx == j).sum())
        area = _projetar(t['anel'], t.get('ilhas'), tr).area / 1e4
        dens = n / area if area else 0.0
        grau, frase = confiabilidade(dens)
        resumo_talhoes.append({'nome': t['nome'], 'area_ha': round(area, 2), 'n': n,
                               'densidade': round(dens, 2), 'grau': grau, 'frase': frase})
        if n < MIN_PONTOS:
            add(NIVEL_ERRO, f'{t["nome"]}: {n} ponto(s)',
                f'Mínimo de {MIN_PONTOS} para interpolar. O talhão será pulado.',
                'Confira se o KML e a planilha são da mesma área.')
        elif grau in ('insuficiente', 'baixa'):
            add(NIVEL_ATENCAO, f'{t["nome"]}: {num_br(dens, 2)} ponto/ha',
                f'{n} perfis em {num_br(area, 1)} ha. {frase}',
                f'Para zonear, seriam {int(np.ceil(DENS_ZONEAR * area))} pontos; para '
                f'prescrição, {int(np.ceil(DENS_PRECISAO * area))}. A aba "Planejar '
                f'coleta" gera a malha.')

    if not achados:
        add(NIVEL_OK, 'Nenhuma anomalia encontrada',
            f'{len(pontos)} perfis, {len(talhoes)} talhão(ões), '
            f'{num_cm(prof.min())}–{num_cm(prof.max())} cm.')

    return {'achados': achados, 'talhoes': resumo_talhoes,
            'n_perfis': len(pontos), 'data_coleta': data_coleta,
            'profundidade': (float(prof.min()), float(prof.max())),
            'pode_prosseguir': any(t['n'] >= MIN_PONTOS for t in resumo_talhoes)}


# ──────────────────────────────────────────────────────────── projeto completo ──
def processar_projeto(projeto, caminhos_kml, caminho_xlsx, pasta_saida,
                      epsg=UTM_EPSG, res_m=RES_M, tol_borda=TOL_BORDA,
                      offline=True, log=print):
    """Roda o projeto inteiro e devolve o resumo. `log` recebe cada linha de progresso.

    Estrutura de saída:
        <pasta_saida>/<projeto>/
            <talhao>/<talhao>.html
            <talhao>/<talhao>.pdf
            <talhao>/perfis_brutos.csv
            <talhao>/grade_interpolada.csv
            resumo_do_projeto.csv
            pontos_nao_atribuidos.csv   (apenas se houver)
    """
    from penetro3d_pdf import gerar_pdf                     # import tardio: abre mais rápido

    destino = os.path.join(pasta_saida, slug(projeto))
    os.makedirs(destino, exist_ok=True)

    talhoes = carregar_talhoes(caminhos_kml)
    log(f'{len(talhoes)} talhão(ões) lido(s) de {len(caminhos_kml)} arquivo(s) KML')

    pontos, prof, CI, data_coleta, avisos = ler_falker(caminho_xlsx)
    for a in avisos:
        log(f'  aviso: {a}')
    log(f'{len(pontos)} perfis · {len(prof)} profundidades '
        f'({num_cm(prof.min())}–{num_cm(prof.max())} cm)'
        + (f' · coleta {data_coleta}' if data_coleta else ''))

    idx, sit = atribuir_pontos(pontos, talhoes, epsg, tol_borda)
    camadas = [(c, a, b) for c, a, b in CAMADAS if ((prof > a) & (prof <= b)).any()]
    fatias = [d for d in FATIAS_CM if float(d) in set(prof.tolist())] or \
             [float(prof[min(len(prof) - 1, int(len(prof) * f))])
              for f in (0.2, 0.4, 0.6, 0.8)]

    orfaos = np.where(idx < 0)[0]
    if len(orfaos):
        log(f'  ATENÇÃO: {len(orfaos)} ponto(s) não caíram em nenhum talhão nem dentro da '
            f'tolerância de {num_br(tol_borda)} m: '
            + ', '.join(str(pontos.id.iloc[i]) for i in orfaos)
            + ' — veja pontos_nao_atribuidos.csv')
        medidas_por_ponto(pontos.iloc[orfaos].reset_index(drop=True), prof,
                          CI[:, orfaos], camadas).to_csv(
            os.path.join(destino, 'pontos_nao_atribuidos.csv'), index=False)

    resumo_projeto, gerados, htmls = [], [], []
    for j, t in enumerate(talhoes):
        sel = np.where(idx == j)[0]
        nome = t['nome']
        if len(sel) < MIN_PONTOS:
            log(f'  [{nome}] ignorado: {len(sel)} ponto(s), mínimo de {MIN_PONTOS} '
                f'para interpolar')
            resumo_projeto.append({'talhao': nome, 'arquivo_kml': t['arquivo'],
                                   'n_pontos': len(sel), 'situacao': 'sem pontos suficientes'})
            continue

        log(f'  [{nome}] {len(sel)} perfis — interpolando…')
        sub_pontos = pontos.iloc[sel].reset_index(drop=True)
        sub_CI = CI[:, sel]
        sub_sit = sit[sel]

        R = interpolar(sub_pontos, sub_CI, t['anel'], epsg, res_m, t.get('ilhas'))
        S, medias, esp, zmax = resumo(prof, R['VOL'], R['mask'], camadas)
        V = validar_camadas(prof, sub_CI, R['sx'], R['sy'], camadas)
        tabela = medidas_por_ponto(sub_pontos, prof, sub_CI, camadas, sub_sit)

        pasta_t = os.path.join(destino, slug(nome))
        os.makedirs(pasta_t, exist_ok=True)
        base = os.path.join(pasta_t, slug(nome))

        ctx = {'projeto': projeto, 'talhao': nome, 'data_coleta': data_coleta,
               'arquivo_kml': t['arquivo'], 'arquivo_xlsx': os.path.basename(caminho_xlsx),
               'tol_borda': tol_borda}
        payload = montar_payload(ctx, sub_pontos, prof, sub_CI, R, S, medias,
                                 camadas, fatias, V)
        with open(base + '.html', 'w', encoding='utf-8') as f:
            f.write(render_html(payload, offline))
        htmls.append(base + '.html')
        log(f'  [{nome}] HTML gerado')

        gerar_pdf(base + '.pdf', ctx, sub_pontos, prof, sub_CI, R, S, medias,
                  esp, zmax, camadas, tabela, payload['notas'], V)
        log(f'  [{nome}] PDF gerado')

        _exportar_csv(pasta_t, sub_pontos, prof, sub_CI, R, medias, esp, zmax, sub_sit)

        resumo_projeto.append({
            'talhao': nome, 'arquivo_kml': t['arquivo'], 'n_pontos': len(sel),
            'situacao': 'ok', 'area_ha': round(R['area_ha'], 2),
            'rmse_loo_kpa': round(R['rmse']) if np.isfinite(R['rmse']) else '',
            'r_loo_agrupado': round(R['r'], 3) if np.isfinite(R['r']) else '',
            'r_loo_horizontal': round(R['r_horiz'], 3) if np.isfinite(R['r_horiz']) else '',
            'area_restritiva_pct': S['restritiva_area'],
            'espessura_restritiva_cm': S['restritiva_esp'],
            'prof_rp_max_mediana_cm': S['zmax_mediana'],
            'camadas_com_suporte_espacial': '; '.join(
                c for c, v in V.items() if v['suporte']) or 'nenhuma',
            **{f'ci_medio_{c}cm': S[c]['media'] for c, _, _ in camadas if c in S}})
        gerados.append(nome)

    pd.DataFrame(resumo_projeto).to_csv(
        os.path.join(destino, 'resumo_do_projeto.csv'), index=False)
    log(f'Concluído: {len(gerados)} talhão(ões) processado(s) em {destino}')
    return {'destino': destino, 'talhoes': gerados, 'resumo': resumo_projeto,
            'htmls': htmls, 'orfaos': [str(pontos.id.iloc[i]) for i in orfaos]}


def _exportar_csv(pasta, pontos, prof, CI, R, medias, esp, zmax, situacao):
    """Dados tidy: leituras brutas por perfil e a grade interpolada célula a célula."""
    brutos = pd.DataFrame([{'perfil': str(pontos.id.iloc[i]), 'situacao': situacao[i],
                            'lat': pontos.lat.iloc[i], 'lon': pontos.lon.iloc[i],
                            'x_m': R['sx'][i], 'y_m': R['sy'][i],
                            'profundidade_cm': prof[k], 'ci_kpa': CI[k, i]}
                           for i in range(len(pontos)) for k in range(len(prof))])
    brutos.to_csv(os.path.join(pasta, 'perfis_brutos.csv'), index=False)

    GX, GY = np.meshgrid(R['gx'], R['gy'])
    sel = R['mask']
    grade = pd.DataFrame({'x_m': GX[sel], 'y_m': GY[sel],
                          'espessura_restritiva_cm': esp[sel], 'prof_rp_max_cm': zmax[sel]})
    for c, m in medias.items():
        grade[f'ci_medio_{c}cm_kpa'] = m[sel]
    grade.to_csv(os.path.join(pasta, 'grade_interpolada.csv'), index=False)
