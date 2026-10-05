import numpy as np
import pytest

from penetro3d_core import (CAMADAS, atribuir_pontos, carregar_talhoes, interpolar,
                            ler_falker, resumo, validar_camadas)


@pytest.fixture(scope='module')
def dados():
    import os
    from conftest import EXEMPLOS
    t = carregar_talhoes([os.path.join(EXEMPLOS, 'talhoes_exemplo.kml')])
    p, prof, CI, _, _ = ler_falker(os.path.join(EXEMPLOS, 'penetrometria_exemplo.xlsx'))
    return t, p, prof, CI


def test_atribuicao_interno_borda_fora(dados):
    t, p, _, _ = dados
    idx, sit = atribuir_pontos(p, t, 31982, tol_m=30)
    assert (sit == 'borda').sum() == 1 and (sit == 'fora').sum() == 1
    assert (idx == -1).sum() == 1
    assert (idx == 0).sum() == 14 and (idx == 1).sum() == 18


def test_tolerancia_zero_manda_borda_para_fora(dados):
    t, p, _, _ = dados
    _, sit = atribuir_pontos(p, t, 31982, tol_m=0)
    assert (sit == 'borda').sum() == 0 and (sit == 'fora').sum() == 2


@pytest.fixture(scope='module')
def sul(dados):
    t, p, prof, CI = dados
    idx, _ = atribuir_pontos(p, t, 31982)
    sel = idx == 1
    R = interpolar(p[sel].reset_index(drop=True), CI[:, sel], t[1]['anel'], 31982, 12,
                   t[1]['ilhas'])
    return R, prof, CI[:, sel]


def test_grade_respeita_o_acude(sul):
    from shapely.geometry import Point
    R, _, _ = sul
    buraco = R['poli'].interiors[0]
    from shapely.geometry import Polygon
    acude = Polygon(buraco)
    GX, GY = np.meshgrid(R['gx'], R['gy'])
    no_acude = np.array([[acude.contains(Point(a, b)) for a, b in zip(rx, ry)]
                         for rx, ry in zip(GX, GY)])
    assert no_acude.any()
    assert not R['mask'][no_acude].any()
    assert np.isnan(R['VOL'][:, no_acude]).all()


def test_area_e_valores_plausiveis(sul):
    R, prof, CI = sul
    assert 15 < R['area_ha'] < 30
    v = R['VOL'][:, R['mask']]
    assert np.isfinite(v).all()
    assert v.min() >= CI.min() - 1e-6 and v.max() <= CI.max() + 1e-6   # IDW não extrapola


def test_resumo_e_validacao_por_camada(sul):
    R, prof, CI = sul
    S, medias, esp, zmax = resumo(prof, R['VOL'], R['mask'], CAMADAS)
    assert 0 <= S['restritiva_area'] <= 100
    assert np.isnan(esp[~R['mask']]).all() and np.isfinite(esp[R['mask']]).all()
    V = validar_camadas(prof, CI, R['sx'], R['sy'], CAMADAS)
    # o modelo de exemplo só tem estrutura espacial nas camadas rasas
    assert [V[c]['suporte'] for c, _, _ in CAMADAS] == [True, True, False, False]
    assert np.isfinite(R['r_horiz'])
