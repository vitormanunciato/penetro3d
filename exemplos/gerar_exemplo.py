#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gera os dados de exemplo do Penetro3D: um KML com dois talhões e uma planilha no
layout do Falker PenetroLOG.

TUDO AQUI É FICTÍCIO. Os talhões não existem e as leituras são simuladas — o
repositório é público e não leva dado real de nenhuma propriedade.

A simulação foi desenhada para exercitar cada caminho do programa:

  · dois talhões no mesmo KML, com <Placemark id="..."> (como o Google Earth grava)
  · um açude dentro do Talhão Sul (<innerBoundaryIs>), que não pode receber pontos
  · um perfil na borda (fora do polígono, dentro da tolerância) e um fora de tudo
  · uma pedra a ~35 cm num perfil (resistência muito acima do conjunto)
  · um perfil interrompido aos 52,5 cm ("Medição completa: Não")
  · pé-de-grade entre 20 e 28 cm, com estrutura espacial SÓ nas camadas rasas —
    compactação de tráfego segue as linhas de passada; abaixo de 20 cm, a
    resistência varia sem padrão. Assim o selo de suporte espacial sai diferente
    entre as camadas, como no talhão real que motivou o programa.

    python gerar_exemplo.py        (grava os dois arquivos nesta pasta)
"""

import os

import numpy as np
from openpyxl import Workbook
from pyproj import Transformer

AQUI = os.path.dirname(os.path.abspath(__file__))
SEMENTE = 2026
EPSG = 31982
LAT0, LON0 = -25.3120, -51.4170          # região fictícia no Centro-Sul do Paraná

tr = Transformer.from_crs(f'EPSG:{EPSG}', 'EPSG:4326', always_xy=True)
tr_ida = Transformer.from_crs('EPSG:4326', f'EPSG:{EPSG}', always_xy=True)
X0, Y0 = tr_ida.transform(LON0, LAT0)


def para_ll(pts_m):
    """Coordenadas locais em metros → (lon, lat)."""
    xs, ys = tr.transform([X0 + x for x, _ in pts_m], [Y0 + y for _, y in pts_m])
    return list(zip(xs, ys))


# ─────────────────────────────────────────────────────────────── geometria ──
NORTE = [(0, 120), (310, 150), (520, 110), (560, 260), (430, 380), (150, 400),
         (-20, 330), (0, 120)]
SUL = [(-30, -360), (260, -400), (540, -330), (580, -40), (330, 40), (40, 20),
       (-50, -150), (-30, -360)]
ACUDE = [(250, -230), (330, -220), (350, -160), (290, -120), (230, -150), (250, -230)]


def kml():
    def anel(pts):
        return ' '.join(f'{lon:.7f},{lat:.7f},0' for lon, lat in para_ll(pts))
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2" xmlns:gx="http://www.google.com/kml/ext/2.2">
<Document>
  <name>Fazenda Exemplo (fictícia)</name>
  <Placemark id="ID_00001">
    <name>Talhão Norte</name>
    <Polygon><outerBoundaryIs><LinearRing><coordinates>
      {anel(NORTE)}
    </coordinates></LinearRing></outerBoundaryIs></Polygon>
  </Placemark>
  <Placemark id="ID_00002">
    <name>Talhão Sul</name>
    <Polygon>
      <outerBoundaryIs><LinearRing><coordinates>
        {anel(SUL)}
      </coordinates></LinearRing></outerBoundaryIs>
      <innerBoundaryIs><LinearRing><coordinates>
        {anel(ACUDE)}
      </coordinates></LinearRing></innerBoundaryIs>
    </Polygon>
  </Placemark>
</Document>
</kml>
'''


# ─────────────────────────────────────────────────────────────── leituras ──
PROF = np.arange(2.5, 60.01, 2.5)


def perfil(rng, x, y):
    """Resistência simulada (kPa) ao longo da profundidade, num ponto (x, y) em metros.

    Três componentes somados:
      · a subida natural da resistência nos primeiros ~15 cm;
      · o pé-de-grade, com pico entre 20 e 28 cm e intensidade ALEATÓRIA por perfil,
        e o subsolo abaixo dele, também aleatório — sem estrutura espacial;
      · o efeito de tráfego, concentrado entre 5 e 20 cm, que cresce perto das
        linhas de passada — a única estrutura espacial do modelo.
    """
    # duas linhas de passada (uma cruzando cada talhão); vale a mais próxima
    d1 = abs(0.55 * x - y + 60) / np.hypot(0.55, 1.0)
    d2 = abs(-0.30 * x - y - 180) / np.hypot(0.30, 1.0)
    trafego = np.exp(-min(d1, d2) / 110.0)                     # 1 na linha, ~0 longe
    pico_z = rng.uniform(20, 28)
    pico = rng.normal(2400, 330)
    fundo = rng.normal(1650, 230)

    z = PROF
    subida = 1 / (1 + np.exp(-(z - 11) / 2.8))                 # 0 na superfície → 1
    nivel = fundo + (pico - fundo) * np.exp(-((z - pico_z) / 8.0) ** 2)
    ci = 40 + subida * nivel + 1500 * trafego * np.exp(-((z - 12.5) / 6.0) ** 2)
    ci *= rng.lognormal(0, 0.11, len(z))                       # ruído de leitura
    return np.clip(ci, 0, None)


def pontos():
    """Malha irregular dentro dos talhões, mais os casos especiais."""
    rng = np.random.default_rng(SEMENTE)
    from shapely.geometry import Point, Polygon
    norte, sul = Polygon(NORTE), Polygon(SUL, [ACUDE])
    pts = []
    for poli, passo in ((norte, 95), (sul, 105)):
        minx, miny, maxx, maxy = poli.bounds
        for gy in np.arange(miny + 40, maxy, passo):
            for gx in np.arange(minx + 40, maxx, passo):
                x, y = gx + rng.uniform(-22, 22), gy + rng.uniform(-22, 22)
                if poli.buffer(-12).contains(Point(x, y)):
                    pts.append((x, y))
    pts.append((540, 125))       # borda: ~15 m fora do Talhão Norte
    pts.append((700, 0))         # fora de tudo
    return pts, rng


def planilha(caminho):
    pts, rng = pontos()
    n = len(pts)
    CI = np.array([perfil(rng, x, y) for x, y in pts]).T      # (prof, ponto)

    pedra = 7                                                  # pedra a ~35 cm
    CI[(PROF >= 32.5) & (PROF <= 40), pedra] = [6900, 7420, 7180, 6750]
    interrompido = 15                                          # parou aos 52,5 cm
    completo = np.ones(n, bool)
    CI[PROF > 52.5, interrompido] = np.nan
    completo[interrompido] = False

    ll = para_ll(pts)
    wb = Workbook()
    ws = wb.active
    ws.title = 'Worksheet'

    def linha(r, *vals):
        for c, v in enumerate(vals, start=1):
            if v is not None:
                ws.cell(row=r, column=c, value=v)

    # cabeçalho no layout do export do Falker Compact
    linha(1, 'Falker Automação Agrícola Ltda.')
    linha(2, 'Arquivo .CSV gerado com')
    linha(3, 'Programa:', 'Falker Compact')
    linha(4, 'Este arquivo foi gerado em', '05/10/2026 10:12:44 am')
    linha(6, 'Configurações de Médias')
    linha(7, 'Intervalo de profundidade:', '2.5 cm')
    linha(8, 'Mostrar média total:', 'Sim')
    linha(10, 'Pasta:', 'EXEMPLO')
    linha(11, 'Medição de Referência:', 0)
    linha(13, 'Medição', '', *range(1, n + 1))
    linha(14, 'Hora', '', *[f'{8 + i // 9:02d}:{(i * 6) % 60:02d}:{(i * 17) % 60:02d}'
                            for i in range(n)])
    linha(15, 'Data', '', *['14/09/2026'] * n)
    linha(16, 'Profundidade Máxima (cm)', '', *[60] * n)
    linha(17, 'Excesso de velocidade', '', *['Não'] * n)
    linha(18, 'Medição completa', '', *['Sim' if c else 'Não' for c in completo])
    linha(19, 'Tipo de Cone', '', *[2] * n)
    linha(20, 'Resolução (cm)', '', *[2.5] * n)
    linha(21, 'Latitude', '', *[round(lat, 6) for _, lat in ll])
    linha(22, 'Longitude', '', *[round(lon, 6) for lon, _ in ll])
    rpmax = np.nanmax(CI, axis=0)
    linha(23, 'RP Máxima (kPa)', '', *[int(v) for v in rpmax])
    linha(24, 'Prof. da RP Máxima (cm)', '',
          *[float(PROF[int(np.nanargmax(CI[:, i]))]) for i in range(n)])
    linha(26, 'Dados da Medição:')
    linha(27, None, 'Profundidade (cm)', *['CI (kPa)'] * n)
    for k, z in enumerate(PROF):
        linha(28 + k, None, float(z),
              *[None if not np.isfinite(v) else int(round(v)) for v in CI[k]])
    r = 28 + len(PROF)
    linha(r, 'Médias (kPa)')
    for j, (a, b) in enumerate(((1, 10), (11, 20), (21, 30), (31, 40), (41, 50),
                                (51, 60), (1, 60))):
        sel = (PROF >= a) & (PROF <= b + 0.1)
        linha(r + 1 + j, f'De {a} a {b}', None,
              *[None if np.isnan(CI[sel, i]).all() else int(np.nanmean(CI[sel, i]))
                for i in range(n)])
    wb.save(caminho)
    return n


if __name__ == '__main__':
    with open(os.path.join(AQUI, 'talhoes_exemplo.kml'), 'w', encoding='utf-8') as f:
        f.write(kml())
    n = planilha(os.path.join(AQUI, 'penetrometria_exemplo.xlsx'))
    print(f'talhoes_exemplo.kml e penetrometria_exemplo.xlsx gravados ({n} perfis)')
