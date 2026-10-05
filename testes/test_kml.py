import pytest
from conftest import anel_txt, escrever_kml

from penetro3d_core import ErroDeDados, carregar_talhoes, epsg_sugerido


def _pm(nome, anel, id_=None, buraco=None):
    ida = f' id="{id_}"' if id_ else ''
    inner = (f'<innerBoundaryIs><LinearRing><coordinates>{buraco}</coordinates>'
             f'</LinearRing></innerBoundaryIs>') if buraco else ''
    return (f'<Placemark{ida}><name>{nome}</name><Polygon><outerBoundaryIs><LinearRing>'
            f'<coordinates>{anel}</coordinates></LinearRing></outerBoundaryIs>{inner}'
            f'</Polygon></Placemark>')


def test_exemplo_tem_dois_talhoes_e_o_acude(kml_exemplo):
    t = carregar_talhoes([kml_exemplo])
    assert [x['nome'] for x in t] == ['Talhão Norte', 'Talhão Sul']
    assert len(t[0]['ilhas']) == 0 and len(t[1]['ilhas']) == 1


def test_placemark_com_id_nao_funde_talhoes(tmp_path):
    corpo = (_pm('A', anel_txt(-51.40, -25.30), 'ID_1') +
             _pm('B', anel_txt(-51.39, -25.30), 'ID_2'))
    t = carregar_talhoes([escrever_kml(tmp_path / 'x.kml', corpo)])
    assert len(t) == 2


def test_multigeometry_vira_um_talhao_por_poligono(tmp_path):
    a, b = anel_txt(-51.40, -25.30), anel_txt(-51.39, -25.30)
    corpo = (f'<Placemark><name>Gleba</name><MultiGeometry>'
             f'<Polygon><outerBoundaryIs><LinearRing><coordinates>{a}</coordinates>'
             f'</LinearRing></outerBoundaryIs></Polygon>'
             f'<Polygon><outerBoundaryIs><LinearRing><coordinates>{b}</coordinates>'
             f'</LinearRing></outerBoundaryIs></Polygon></MultiGeometry></Placemark>')
    t = carregar_talhoes([escrever_kml(tmp_path / 'm.kml', corpo)])
    assert [x['nome'] for x in t] == ['Gleba (1)', 'Gleba (2)']


def test_nomes_repetidos_recebem_sufixo(tmp_path):
    corpo = _pm('Talhão 1', anel_txt(-51.40, -25.30)) + _pm('Talhão 1', anel_txt(-51.39, -25.30))
    t = carregar_talhoes([escrever_kml(tmp_path / 'd.kml', corpo)])
    assert t[0]['nome'] != t[1]['nome']


def test_kml_sem_poligono_da_erro_claro(tmp_path):
    corpo = '<Placemark><name>ponto</name><Point><coordinates>-51,-25,0</coordinates></Point></Placemark>'
    with pytest.raises(ErroDeDados, match='polígono'):
        carregar_talhoes([escrever_kml(tmp_path / 'p.kml', corpo)])


def test_arquivo_que_nao_e_kml(tmp_path):
    p = tmp_path / 'lixo.kml'
    p.write_text('isto não é xml', encoding='utf-8')
    with pytest.raises(ErroDeDados):
        carregar_talhoes([str(p)])


def test_epsg_deduzido_do_kml(kml_exemplo):
    epsg, _ = epsg_sugerido(carregar_talhoes([kml_exemplo]))
    assert epsg == 31982                      # Guarapuava: UTM 22S
