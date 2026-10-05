#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
penetro3d_amostragem.py — planejamento da malha amostral, ANTES de ir a campo.

Recebe o KML do talhão e devolve uma malha hexagonal recortada pelo polígono, em
três níveis de densidade, com a rota de caminhamento já ordenada e exportação para
KML, GPX, CSV e GeoJSON (este último é o que o radar de campo consome).

Por que malha hexagonal
-----------------------
Para uma mesma quantidade de pontos, a rede triangular (cujas células de influência
são hexágonos) é o arranjo que minimiza a maior distância entre um lugar qualquer do
talhão e o ponto amostral mais próximo. Em uma malha quadrada de lado d, o pior caso
é d·√2/2 = 0,707·d; na hexagonal de espaçamento d, é d/√3 = 0,577·d. São ~18% menos
distância de pior caso pelo mesmo número de pontos — é isso que "cobertura sem
consumo de luxo" quer dizer na prática.

    área por ponto = (√3/2)·d²   →   d = √(11.547 / densidade em pt/ha)

De onde vêm as densidades
-------------------------
Não são números de catálogo: saem de duas contas feitas sobre dados reais de
penetrometria (talhão de 23 ha, 20 perfis, 0–60 cm).

1. Para ESTIMAR A MÉDIA de uma camada com erro de ±15% e 95% de confiança,
   n = (1,96·CV/0,15)². Com CV observado de 29–41% nas camadas de 10–60 cm,
   isso dá 0,6 a 1,2 ponto/ha. Daí o nível MÍNIMO de 1 pt/ha.

2. Para MAPEAR, o espaçamento precisa ser menor que o alcance da dependência
   espacial. No conjunto analisado, o semivariograma já estava no patamar no menor
   lag disponível (~70 m), ou seja: o alcance é igual ou menor que isso. Daí o nível
   ALTO com espaçamento de ~55 m, seguramente abaixo do alcance máximo plausível.

O nível INTERMEDIÁRIO fica no meio (~76 m) e serve para zoneamento amplo — bom para
decidir "esta metade do talhão precisa de escarificação", não "escarifique este
ponto".
"""

import json
import os

import numpy as np
import pandas as pd
import shapely
from pyproj import Transformer
from shapely.affinity import rotate, translate

from penetro3d_core import UTM_EPSG, ErroDeDados, _projetar, aneis, slug

# ─────────────────────────────────────────────────────────────── configuração ──
RECUO_BORDA = 15.0     # m — não amostrar na bordadura/carreador, que é sempre mais duro
MIN_PONTOS = 6         # piso absoluto: abaixo disso não há o que interpretar

NIVEIS = {
    'minimo': {
        'rotulo': 'Mínimo',
        'densidade': 1.0,
        'para_que': 'caracterizar o talhão',
        'entrega': 'perfil médio, profundidade da camada compactada e ordem de grandeza da '
                   'resistência, com erro de ±15% na média de cada camada',
        'nao_entrega': 'mapa de manchas confiável — não use para escarificação localizada',
    },
    'intermediario': {
        'rotulo': 'Intermediário',
        'densidade': 2.0,
        'para_que': 'zonear o talhão em áreas amplas',
        'entrega': 'as duas ou três zonas de manejo mais evidentes, além de tudo do nível '
                   'mínimo',
        'nao_entrega': 'contorno fino das manchas nem mapa de aplicação a taxa variável',
    },
    'alto': {
        'rotulo': 'Alto detalhamento',
        'densidade': 3.5,
        'para_que': 'agricultura de precisão',
        'entrega': 'suporte amostral para variograma e krigagem, e mapa de prescrição para '
                   'escarificação a taxa variável',
        'nao_entrega': 'nada disso dispensa registrar a umidade do solo na coleta',
    },
}


def espacamento(densidade_ha):
    """Espaçamento da malha hexagonal, em metros, para uma densidade em pontos/ha."""
    return float(np.sqrt(10000.0 / (densidade_ha * np.sqrt(3) / 2)))


def densidade(espacamento_m):
    """Caminho inverso: densidade em pontos/ha para um espaçamento dado."""
    return float(10000.0 / (espacamento_m ** 2 * np.sqrt(3) / 2))


# ────────────────────────────────────────────────────────────── malha hexagonal ──
def _malha_hex(poli, d, passos=5, angulos=(0, 15, 30, 45)):
    """Rede triangular de espaçamento d, encaixada no polígono na melhor posição.

    Para um mesmo d, deslocar e girar a malha muda quantos pontos caem dentro. Testa
    várias combinações e fica com a que aproveita melhor o talhão.

    Devolve (x, y) no referencial do talhão e (xr, yr) no referencial girado da
    malha, onde as faixas são horizontais e a serpentina faz sentido.
    """
    vazio = np.array([])
    dy = d * np.sqrt(3) / 2
    melhor = (None, -1)
    for ang in angulos:
        g = rotate(poli, -ang, origin='centroid')          # gira o talhão, não a malha
        minx, miny, maxx, maxy = g.bounds
        for ox in np.linspace(0, d, passos, endpoint=False):
            for oy in np.linspace(0, dy, passos, endpoint=False):
                xs, ys = [], []
                j = 0
                y = miny + oy
                while y <= maxy:
                    x = minx + ox + ((d / 2) if (j % 2) else 0.0)
                    while x <= maxx:
                        xs.append(x); ys.append(y)
                        x += d
                    y += dy; j += 1
                if not xs:
                    continue
                xs = np.asarray(xs); ys = np.asarray(ys)
                dentro = shapely.contains_xy(g, xs, ys)
                if dentro.sum() > melhor[1]:
                    melhor = ((xs[dentro], ys[dentro], ang), int(dentro.sum()))
    if melhor[0] is None or melhor[1] == 0:
        return vazio, vazio, vazio, vazio

    xs, ys, ang = melhor[0]
    cx, cy = poli.centroid.x, poli.centroid.y
    a = np.radians(ang)
    dx, dy_ = xs - cx, ys - cy
    return (cx + dx * np.cos(a) - dy_ * np.sin(a),
            cy + dx * np.sin(a) + dy_ * np.cos(a), xs, ys)


def _ordenar_rota(xr, yr, d):
    """Serpentina por faixas da malha, para encurtar a caminhada.

    Recebe as coordenadas NO REFERENCIAL DA MALHA (já girado): é lá que as faixas são
    horizontais. Ordenar no referencial do talhão faria a rota ziguezaguear à toa.
    """
    if len(xr) == 0:
        return np.array([], int)
    faixa = np.round((yr - yr.min()) / (d * np.sqrt(3) / 2)).astype(int)
    ordem = []
    for k, f in enumerate(sorted(set(faixa))):
        idx = np.where(faixa == f)[0]
        idx = idx[np.argsort(xr[idx])]
        if k % 2:
            idx = idx[::-1]                                 # faixa alternada: volta ao contrário
        ordem.extend(idx.tolist())
    return np.array(ordem, int)


def _caminhada(x, y):
    """Distância total percorrida seguindo a ordem dada, em metros."""
    if len(x) < 2:
        return 0.0
    return float(np.sum(np.hypot(np.diff(x), np.diff(y))))


# ───────────────────────────────────────────────────────────────── planejamento ──
def planejar(talhao, nivel='intermediario', epsg=UTM_EPSG, recuo=RECUO_BORDA,
             densidade_ha=None):
    """Gera a malha amostral de um talhão.

    `talhao` é um item de penetro3d_core.carregar_talhoes(). `nivel` é uma das chaves
    de NIVEIS, ou passe `densidade_ha` para um valor livre. Devolve um dicionário com
    o DataFrame dos pontos (lat/lon prontos para o GPS) e as métricas do plano.
    """
    if densidade_ha is None:
        if nivel not in NIVEIS:
            raise ErroDeDados(f'Nível "{nivel}" desconhecido. Use: {", ".join(NIVEIS)}.')
        densidade_ha = NIVEIS[nivel]['densidade']

    tr = Transformer.from_crs('EPSG:4326', f'EPSG:{epsg}', always_xy=True)
    poli = _projetar(talhao['anel'], talhao.get('ilhas'), tr)
    x0, y0 = poli.centroid.x, poli.centroid.y
    poli = translate(poli, -x0, -y0)
    area_ha = poli.area / 1e4

    # a bordadura é sempre mais compactada (manobra, tráfego): amostrar ali enviesa
    # o talhão inteiro. Se o recuo engolir o talhão, ele cede antes de o plano falhar.
    util, recuo_usado = poli, 0.0
    for tentativa in (recuo, recuo / 2, 0.0):
        g = poli.buffer(-tentativa) if tentativa > 0 else poli
        if not g.is_empty and g.area > 0.35 * poli.area:
            util, recuo_usado = g, tentativa
            break

    def tentar(dd):
        x, y, xr, yr = _malha_hex(util, dd)
        return x, y, xr, yr, (len(x) / area_ha if area_ha else 0.0)

    def bissectar(d_alto, d_baixo, r_baixo, passos=7):
        """Maior espaçamento que ainda atinge o alvo, entre um ralo e um denso."""
        r = r_baixo
        for _ in range(passos):
            meio = (d_alto + d_baixo) / 2
            rm = tentar(meio)
            if rm[4] >= alvo * 0.97:
                d_baixo, r = meio, rm
            else:
                d_alto = meio
        return d_baixo, r

    # O alvo é densidade sobre a área TOTAL, mas os pontos só entram na área útil.
    # Compensar por passos fixos erra para o outro lado em talhão estreito, onde um
    # passo a menos acrescenta uma faixa inteira. Então: acha o intervalo e bissecta,
    # ficando com o MAIOR espaçamento que ainda atinge o alvo — menos pontos para a
    # mesma promessa.
    alvo = densidade_ha
    d = espacamento(alvo)
    r = tentar(d)
    if r[4] < alvo * 0.97:
        d_alto, d_baixo = d, d
        for _ in range(10):
            d_baixo *= 0.90
            if d_baixo < 8:
                break
            r2 = tentar(d_baixo)
            if r2[4] >= alvo * 0.97:
                d, r = bissectar(d_alto, d_baixo, r2)
                break
        else:
            d = d_baixo
    elif r[4] > alvo * 1.15:
        d_baixo, d_alto, r_baixo = d, d, r
        for _ in range(8):
            d_alto *= 1.12
            if tentar(d_alto)[4] < alvo * 0.97:
                d, r = bissectar(d_alto, d_baixo, r_baixo)
                break
        else:
            d, r = d_baixo, r_baixo

    # piso absoluto: um talhão pequeno ainda precisa de perfis suficientes
    piso = False
    while len(r[0]) < MIN_PONTOS and d > 8:
        d *= 0.85
        r = tentar(d)
        piso = True

    x, y, xr, yr = r[0], r[1], r[2], r[3]
    if len(x) == 0:
        raise ErroDeDados(f'Não consegui posicionar pontos em "{talhao["nome"]}" — '
                          f'talhão pequeno ou geometria inválida.')

    ordem = _ordenar_rota(xr, yr, d)
    x, y = x[ordem], y[ordem]
    lon, lat = tr.transform(x + x0, y + y0, direction='INVERSE')

    pontos = pd.DataFrame({
        'ordem': np.arange(1, len(x) + 1),
        'id': [f'P{i:03d}' for i in range(1, len(x) + 1)],
        'lat': np.round(lat, 7), 'lon': np.round(lon, 7),
        'x_m': np.round(x, 1), 'y_m': np.round(y, 1),
    })

    return {
        'talhao': talhao['nome'], 'nivel': nivel, 'pontos': pontos, 'poli': poli,
        'origem': (x0, y0), 'epsg': epsg, 'area_ha': round(area_ha, 2),
        'n': len(pontos), 'densidade_real': round(len(pontos) / area_ha, 2),
        'espacamento_m': round(d, 1),
        'cobertura_m': round(d / np.sqrt(3), 1),      # pior distância até o ponto mais próximo
        'recuo_m': round(recuo_usado, 1),
        'caminhada_km': round(_caminhada(x, y) / 1000, 2),
        # o piso mandou no resultado: a densidade saiu do alvo por ser um talhão
        # pequeno demais, não por escolha do nível
        'piso_aplicado': piso,
    }


def comparar(talhao, epsg=UTM_EPSG, recuo=RECUO_BORDA):
    """Roda os três níveis e devolve (tabela comparativa, {nível: plano})."""
    planos, linhas = {}, []
    for chave, cfg in NIVEIS.items():
        p = planejar(talhao, chave, epsg, recuo)
        planos[chave] = p
        linhas.append({
            'nivel': cfg['rotulo'] + (' (piso)' if p['piso_aplicado'] else ''),
            'alvo_pt_ha': cfg['densidade'],
            'pontos': p['n'], 'densidade_real_pt_ha': p['densidade_real'],
            'espacamento_m': p['espacamento_m'], 'cobertura_max_m': p['cobertura_m'],
            'caminhada_km': p['caminhada_km'],
            'tempo_estimado_h': round(p['n'] * 4.5 / 60 + p['caminhada_km'] / 4.0, 1),
            'para_que': cfg['para_que'],
        })
    return pd.DataFrame(linhas), planos


# ──────────────────────────────────────────────────────────────────── exportação ──
def _kml(plano):
    p = plano['pontos']
    marcas = '\n'.join(
        f'  <Placemark><name>{r.id}</name>'
        f'<description>ordem {r.ordem} de {len(p)} · {plano["talhao"]}</description>'
        f'<Point><coordinates>{r.lon:.7f},{r.lat:.7f},0</coordinates></Point></Placemark>'
        for r in p.itertuples())
    rota = ' '.join(f'{r.lon:.7f},{r.lat:.7f},0' for r in p.itertuples())
    rotulo = NIVEIS.get(plano['nivel'], {}).get('rotulo', plano['nivel'])
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
  <name>{plano['talhao']} — amostragem {rotulo}</name>
{marcas}
  <Placemark><name>Rota sugerida</name><LineString><tessellate>1</tessellate>
    <coordinates>{rota}</coordinates></LineString></Placemark>
</Document></kml>'''


def _gpx(plano):
    pts = '\n'.join(f'  <wpt lat="{r.lat:.7f}" lon="{r.lon:.7f}"><name>{r.id}</name>'
                    f'<desc>{plano["talhao"]}</desc></wpt>'
                    for r in plano['pontos'].itertuples())
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<gpx version="1.1" creator="Penetro3D" '
            f'xmlns="http://www.topografix.com/GPX/1/1">\n{pts}\n</gpx>')


def _geojson(plano):
    """Formato que o radar de campo consome: pontos + contorno + metadados do plano."""
    tr = Transformer.from_crs(f'EPSG:{plano["epsg"]}', 'EPSG:4326', always_xy=True)
    x0, y0 = plano['origem']
    feats = [{
        'type': 'Feature',
        'geometry': {'type': 'Point', 'coordinates': [float(r.lon), float(r.lat)]},
        'properties': {'id': r.id, 'ordem': int(r.ordem), 'coletado': False},
    } for r in plano['pontos'].itertuples()]
    for anel in aneis(plano['poli']):
        lons, lats = tr.transform([a + x0 for a, _ in anel], [b + y0 for _, b in anel])
        feats.append({'type': 'Feature',
                      'geometry': {'type': 'LineString',
                                   'coordinates': [[a, b] for a, b in zip(lons, lats)]},
                      'properties': {'tipo': 'contorno'}})
    return {'type': 'FeatureCollection',
            'properties': {k: plano[k] for k in
                           ('talhao', 'nivel', 'n', 'area_ha', 'densidade_real',
                            'espacamento_m', 'cobertura_m', 'caminhada_km')},
            'features': feats}


def exportar(plano, pasta):
    """Grava KML, GPX, CSV e GeoJSON. Devolve os caminhos criados."""
    os.makedirs(pasta, exist_ok=True)
    base = os.path.join(pasta, f'{slug(plano["talhao"])}_{plano["nivel"]}')
    saidas = {}
    for ext, conteudo in (('kml', _kml(plano)), ('gpx', _gpx(plano))):
        with open(f'{base}.{ext}', 'w', encoding='utf-8') as f:
            f.write(conteudo)
        saidas[ext] = f'{base}.{ext}'
    plano['pontos'].to_csv(f'{base}.csv', index=False)
    saidas['csv'] = f'{base}.csv'
    with open(f'{base}.geojson', 'w', encoding='utf-8') as f:
        json.dump(_geojson(plano), f, ensure_ascii=False, separators=(',', ':'))
    saidas['geojson'] = f'{base}.geojson'
    return saidas
