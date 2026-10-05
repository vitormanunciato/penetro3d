"""Configuração comum dos testes: põe app/ no caminho e oferece os dados de exemplo."""
import os
import sys

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, 'app'))
os.environ['PENETRO3D_SEM_ATUALIZACAO'] = '1'
os.environ.setdefault('MPLBACKEND', 'Agg')

EXEMPLOS = os.path.join(RAIZ, 'exemplos')


@pytest.fixture
def kml_exemplo():
    return os.path.join(EXEMPLOS, 'talhoes_exemplo.kml')


@pytest.fixture
def xlsx_exemplo():
    return os.path.join(EXEMPLOS, 'penetrometria_exemplo.xlsx')


def escrever_kml(caminho, corpo):
    with open(caminho, 'w', encoding='utf-8') as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
                f'{corpo}</Document></kml>')
    return caminho


def anel_txt(lon0, lat0, lado=0.004):
    """Quadrado em graus como texto de <coordinates>."""
    pts = [(lon0, lat0), (lon0 + lado, lat0), (lon0 + lado, lat0 + lado),
           (lon0, lat0 + lado), (lon0, lat0)]
    return ' '.join(f'{a},{b},0' for a, b in pts)
