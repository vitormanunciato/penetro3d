import io

import pytest

import penetro3d_atualizacao as atu


@pytest.fixture(autouse=True)
def pasta_isolada(tmp_path, monkeypatch):
    monkeypatch.setattr(atu, 'pasta_usuario', lambda: str(tmp_path))
    monkeypatch.delenv('PENETRO3D_SEM_ATUALIZACAO', raising=False)
    monkeypatch.setattr(atu, '_notas', lambda *a, **k: 'notas')


def test_versao_tupla_compara_numeros():
    assert atu.versao_tupla('v1.10.0') > atu.versao_tupla('1.9.9')
    assert atu.versao_tupla('v2') == (2, 0, 0)


def test_ha_versao_nova(monkeypatch):
    monkeypatch.setattr(atu, 'ultima_versao', lambda repo=None: 'v9.0.0')
    info = atu.verificar(manual=True, atual='1.3.0')
    assert info['versao'] == '9.0.0'
    assert info['instalador'].endswith('/v9.0.0/Penetro3D-Setup.exe')


def test_mesma_versao_nao_avisa(monkeypatch):
    monkeypatch.setattr(atu, 'ultima_versao', lambda repo=None: 'v1.3.0')
    assert atu.verificar(manual=True, atual='1.3.0') is None


def test_sem_internet_nao_avisa(monkeypatch):
    monkeypatch.setattr(atu, 'ultima_versao', lambda repo=None: None)
    assert atu.verificar(manual=True, atual='1.3.0') is None


def test_intervalo_entre_consultas(monkeypatch):
    chamadas = []
    monkeypatch.setattr(atu, 'ultima_versao', lambda repo=None: chamadas.append(1) or 'v9.0.0')
    assert atu.verificar(atual='1.3.0') is not None
    assert atu.verificar(atual='1.3.0') is None            # dentro das 20 h
    assert len(chamadas) == 1
    assert atu.verificar(manual=True, atual='1.3.0') is not None   # botão ignora o intervalo


def test_variavel_de_ambiente_desliga(monkeypatch):
    monkeypatch.setenv('PENETRO3D_SEM_ATUALIZACAO', '1')
    monkeypatch.setattr(atu, 'ultima_versao', lambda repo=None: pytest.fail('consultou'))
    assert atu.verificar(atual='1.3.0') is None


def test_ultima_versao_le_o_redirecionamento(monkeypatch):
    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def geturl(self): return 'https://github.com/x/y/releases/tag/v1.4.2'
    monkeypatch.setattr(atu, '_abrir', lambda url, t: Resp())
    assert atu.ultima_versao('x/y') == 'v1.4.2'


class _Download(io.BytesIO):
    def __init__(self, dados, total):
        super().__init__(dados)
        self.headers = {'Content-Length': str(total)}
    def __enter__(self): return self
    def __exit__(self, *a): pass


def test_download_completo(monkeypatch, tmp_path):
    monkeypatch.setattr(atu.tempfile, 'gettempdir', lambda: str(tmp_path))
    monkeypatch.setattr(atu, '_abrir', lambda url, t: _Download(b'x' * 1000, 1000))
    vistos = []
    p = atu.baixar({'versao': '9.0.0', 'instalador': 'u'}, lambda a, b: vistos.append(a))
    assert open(p, 'rb').read() == b'x' * 1000 and vistos[-1] == 1000


def test_download_cortado_nao_fica(monkeypatch, tmp_path):
    monkeypatch.setattr(atu.tempfile, 'gettempdir', lambda: str(tmp_path))
    monkeypatch.setattr(atu, '_abrir', lambda url, t: _Download(b'x' * 500, 1000))
    with pytest.raises(IOError):
        atu.baixar({'versao': '9.0.0', 'instalador': 'u'})
    assert not list(tmp_path.iterdir())
