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
import zipfile
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd
import shapely
from pyproj import Transformer
from shapely.affinity import rotate, translate

from penetro3d_core import UTM_EPSG, ErroDeDados, _projetar, aneis, slug
from penetro3d_versao import AUTOR

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
KML_NS = 'http://www.opengis.net/kml/2.2'


def _aneis_lonlat(plano):
    """Devolve o contorno métrico do plano em longitude/latitude."""
    tr = Transformer.from_crs(f'EPSG:{plano["epsg"]}', 'EPSG:4326', always_xy=True)
    x0, y0 = plano['origem']
    resultado = []
    for anel in aneis(plano['poli']):
        lons, lats = tr.transform([x + x0 for x, _ in anel],
                                  [y + y0 for _, y in anel])
        resultado.append(list(zip(lons, lats)))
    return resultado


def _elemento(pai, nome, texto=None, **atributos):
    e = ET.SubElement(pai, f'{{{KML_NS}}}{nome}', atributos)
    if texto is not None:
        e.text = str(texto)
    return e


def _estilos_kml(documento):
    """Estilos legíveis no campo, inclusive sobre imagem de satélite."""
    estilo = _elemento(documento, 'Style', id='ponto')
    icone = _elemento(estilo, 'IconStyle')
    _elemento(icone, 'color', 'ff2f9e44')
    _elemento(icone, 'scale', '0.9')
    etiqueta = _elemento(estilo, 'LabelStyle')
    _elemento(etiqueta, 'color', 'ffffffff')
    _elemento(etiqueta, 'scale', '0.75')

    estilo = _elemento(documento, 'Style', id='rota')
    linha = _elemento(estilo, 'LineStyle')
    _elemento(linha, 'color', 'ff00a5ff')
    _elemento(linha, 'width', '4')

    estilo = _elemento(documento, 'Style', id='talhao')
    linha = _elemento(estilo, 'LineStyle')
    _elemento(linha, 'color', 'ff00ffff')
    _elemento(linha, 'width', '3')
    area = _elemento(estilo, 'PolyStyle')
    _elemento(area, 'color', '2600ffff')


def _kml(plano):
    """KML de campo para Google Earth: limite, pontos numerados e rota."""
    ET.register_namespace('', KML_NS)
    raiz = ET.Element(f'{{{KML_NS}}}kml')
    documento = _elemento(raiz, 'Document')
    rotulo = NIVEIS.get(plano['nivel'], {}).get('rotulo', plano['nivel'])
    _elemento(documento, 'name', f'{plano["talhao"]} — amostragem {rotulo}')
    _elemento(documento, 'description',
              f'{plano["n"]} pontos · malha {plano["espacamento_m"]} m · '
              f'caminhada estimada {plano["caminhada_km"]} km · Autoria: {AUTOR}')
    _estilos_kml(documento)

    limite = _elemento(documento, 'Placemark')
    _elemento(limite, 'name', 'Limite do talhão')
    _elemento(limite, 'styleUrl', '#talhao')
    poligono = _elemento(limite, 'Polygon')
    _elemento(poligono, 'tessellate', '1')
    aneis_ll = _aneis_lonlat(plano)
    for i, anel in enumerate(aneis_ll):
        borda = _elemento(poligono, 'outerBoundaryIs' if i == 0 else 'innerBoundaryIs')
        linear = _elemento(borda, 'LinearRing')
        _elemento(linear, 'coordinates',
                  ' '.join(f'{lon:.7f},{lat:.7f},0' for lon, lat in anel))

    pasta = _elemento(documento, 'Folder')
    _elemento(pasta, 'name', 'Pontos de amostragem')
    for r in plano['pontos'].itertuples():
        marca = _elemento(pasta, 'Placemark')
        _elemento(marca, 'name', r.id)
        _elemento(marca, 'description',
                  f'Ordem {r.ordem} de {plano["n"]} · {plano["talhao"]}')
        _elemento(marca, 'styleUrl', '#ponto')
        dados = _elemento(marca, 'ExtendedData')
        for nome, valor in (('ordem', r.ordem), ('latitude', f'{r.lat:.7f}'),
                            ('longitude', f'{r.lon:.7f}')):
            dado = _elemento(dados, 'Data', name=nome)
            _elemento(dado, 'value', valor)
        ponto = _elemento(marca, 'Point')
        _elemento(ponto, 'coordinates', f'{r.lon:.7f},{r.lat:.7f},0')

    rota = _elemento(documento, 'Placemark')
    _elemento(rota, 'name', 'Rota sugerida')
    _elemento(rota, 'description',
              'Siga a numeração dos pontos. A linha é uma ordem de caminhamento, '
              'não navegação por estradas.')
    _elemento(rota, 'styleUrl', '#rota')
    linha = _elemento(rota, 'LineString')
    _elemento(linha, 'tessellate', '1')
    _elemento(linha, 'coordinates', ' '.join(
        f'{r.lon:.7f},{r.lat:.7f},0' for r in plano['pontos'].itertuples()))

    return ET.tostring(raiz, encoding='utf-8', xml_declaration=True).decode('utf-8')


def _gpx(plano):
    from xml.sax.saxutils import escape     # nome de talhão com "&" quebrava o GPX
    pts = '\n'.join(f'  <wpt lat="{r.lat:.7f}" lon="{r.lon:.7f}"><name>{escape(str(r.id))}'
                    f'</name><desc>{escape(str(plano["talhao"]))}</desc></wpt>'
                    for r in plano['pontos'].itertuples())
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<gpx version="1.1" creator="Penetro3D" '
            f'xmlns="http://www.topografix.com/GPX/1/1">\n'
            f'  <metadata><author><name>{escape(AUTOR)}</name></author></metadata>\n'
            f'{pts}\n</gpx>')


def _geojson(plano):
    """Formato que o radar de campo consome: pontos + contorno + metadados do plano."""
    feats = [{
        'type': 'Feature',
        'geometry': {'type': 'Point', 'coordinates': [float(r.lon), float(r.lat)]},
        'properties': {'id': r.id, 'ordem': int(r.ordem), 'coletado': False},
    } for r in plano['pontos'].itertuples()]
    for anel in _aneis_lonlat(plano):
        feats.append({'type': 'Feature',
                      'geometry': {'type': 'LineString',
                                   'coordinates': [[a, b] for a, b in anel]},
                      'properties': {'tipo': 'contorno'}})
    propriedades = {k: plano[k] for k in
                    ('talhao', 'nivel', 'n', 'area_ha', 'densidade_real',
                     'espacamento_m', 'cobertura_m', 'caminhada_km')}
    propriedades['autor'] = AUTOR
    return {'type': 'FeatureCollection',
            'properties': propriedades,
            'features': feats}


def _base_saida(plano, pasta):
    os.makedirs(pasta, exist_ok=True)
    return os.path.join(pasta, f'{slug(plano["talhao"])}_{plano["nivel"]}')


def _gravar_kmz(base, kml):
    caminho = f'{base}.kmz'
    with zipfile.ZipFile(caminho, 'w', compression=zipfile.ZIP_DEFLATED) as pacote:
        pacote.writestr('doc.kml', kml.encode('utf-8'))
    return caminho


def exportar_formato(plano, pasta, formato='kmz'):
    """Grava apenas o formato escolhido e devolve o caminho criado."""
    formatos = {'kmz', 'kml', 'gpx', 'geojson', 'csv'}
    if formato not in formatos:
        raise ValueError(f'Formato de exportação desconhecido: {formato}')

    base = _base_saida(plano, pasta)
    caminho = f'{base}.{formato}'
    if formato == 'kmz':
        return _gravar_kmz(base, _kml(plano))
    if formato == 'csv':
        plano['pontos'].to_csv(caminho, index=False, sep=';', decimal=',',
                               encoding='utf-8-sig')
        return caminho
    if formato == 'geojson':
        with open(caminho, 'w', encoding='utf-8') as f:
            json.dump(_geojson(plano), f, ensure_ascii=False, separators=(',', ':'))
        return caminho

    conteudo = _kml(plano) if formato == 'kml' else _gpx(plano)
    with open(caminho, 'w', encoding='utf-8') as f:
        f.write(conteudo)
    return caminho


def exportar_google_earth(plano, pasta):
    """Grava somente o KMZ de campo e devolve seu caminho."""
    return exportar_formato(plano, pasta, 'kmz')


def exportar(plano, pasta):
    """Grava KML/KMZ, GPX, CSV e GeoJSON. Devolve os caminhos criados."""
    return {formato: exportar_formato(plano, pasta, formato)
            for formato in ('kml', 'kmz', 'gpx', 'csv', 'geojson')}
