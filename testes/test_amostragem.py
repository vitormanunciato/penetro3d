import numpy as np
import pytest
from shapely.geometry import Point

from penetro3d_amostragem import NIVEIS, densidade, espacamento, exportar, planejar
from penetro3d_core import MIN_PONTOS, carregar_talhoes


@pytest.fixture(scope='module')
def talhoes():
    import os
    from conftest import EXEMPLOS
    return carregar_talhoes([os.path.join(EXEMPLOS, 'talhoes_exemplo.kml')])


def test_espacamento_e_densidade_sao_inversos():
    for d in (1.0, 2.0, 3.5):
        assert densidade(espacamento(d)) == pytest.approx(d)
    assert espacamento(1.0) == pytest.approx(107.5, abs=0.5)


@pytest.mark.parametrize('nivel', list(NIVEIS))
def test_niveis_atingem_a_densidade(talhoes, nivel):
    p = planejar(talhoes[1], nivel)
    alvo = NIVEIS[nivel]['densidade']
    assert p['densidade_real'] >= alvo * 0.97
    assert p['densidade_real'] <= alvo * 1.35
    assert not p['piso_aplicado']


def test_pontos_dentro_do_talhao_e_fora_do_acude(talhoes):
    p = planejar(talhoes[1], 'alto')
    poli = p['poli']
    for x, y in zip(p['pontos'].x_m, p['pontos'].y_m):
        assert poli.contains(Point(x, y))
    assert p['recuo_m'] > 0


def test_niveis_crescem(talhoes):
    ns = [planejar(talhoes[0], n)['n'] for n in ('minimo', 'intermediario', 'alto')]
    assert ns[0] < ns[1] < ns[2]


def test_talhao_pequeno_aplica_o_piso():
    lon0, lat0, l = -51.40, -25.30, 0.0012          # ~1,5 ha
    anel = [(lon0, lat0), (lon0 + l, lat0), (lon0 + l, lat0 + l), (lon0, lat0 + l), (lon0, lat0)]
    p = planejar({'nome': 'mini', 'anel': anel, 'ilhas': []}, 'minimo')
    assert p['n'] >= MIN_PONTOS and p['piso_aplicado']


def test_exporta_arquivos_de_campo(talhoes, tmp_path):
    p = planejar(talhoes[0], 'intermediario')
    exportar(p, str(tmp_path))
    nomes = {f.suffix for f in tmp_path.rglob('*') if f.is_file()}
    assert {'.kml', '.gpx', '.geojson', '.csv'} <= nomes


def test_rota_sem_saltos_grandes(talhoes):
    p = planejar(talhoes[1], 'intermediario')
    x, y = p['pontos'].x_m.values, p['pontos'].y_m.values
    passos = np.hypot(np.diff(x), np.diff(y))
    assert np.median(passos) < p['espacamento_m'] * 1.3
