import urllib.request
from pathlib import Path

from penetro3d_celular import matriz_qr, servir


def test_servidor_entrega_indice_e_relatorio(tmp_path):
    (tmp_path / 'Talhao_A').mkdir()
    (tmp_path / 'Talhao_A' / 'Talhao_A.html').write_text('<h1>ok</h1>', encoding='utf-8')
    url, parar = servir(str(tmp_path), 'Teste')
    try:
        local = url.split('://', 1)[1].split('/', 1)[0].split(':')[1]
        base = f'http://127.0.0.1:{local}/'
        indice = urllib.request.urlopen(base, timeout=5).read().decode('utf-8')
        assert 'Talhao_A' in indice or 'Talhão A' in indice
        assert 'ANUNCIATO, V.M.' in indice
        rel = urllib.request.urlopen(base + 'Talhao_A/Talhao_A.html', timeout=5).read()
        assert b'ok' in rel
    finally:
        parar()


def test_qr_e_quadrado():
    m = matriz_qr('http://192.168.0.10:8000/')
    assert len(m) == len(m[0]) and len(m) >= 21


def test_radar_mostra_autoria():
    from conftest import RAIZ
    radar = Path(RAIZ, 'app', 'radar', 'radar_campo.html').read_text(encoding='utf-8')
    assert 'ANUNCIATO, V.M.' in radar
