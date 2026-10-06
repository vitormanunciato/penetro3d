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


def test_sem_internet_automatico_fica_quieto_e_tenta_de_novo(monkeypatch):
    monkeypatch.setattr(atu, 'ultima_versao', lambda repo=None: None)
    assert atu.verificar(atual='1.3.0') is None
    assert atu._ultima_consulta() == 0           # falha não conta como consulta feita


def test_sem_internet_manual_avisa_que_nao_conseguiu(monkeypatch):
    monkeypatch.setattr(atu, 'ultima_versao', lambda repo=None: None)
    with pytest.raises(atu.SemResposta):
        atu.verificar(manual=True, atual='1.3.0')


def test_estado_corrompido_nao_trava(tmp_path):
    (tmp_path / 'estado.json').write_text('[]', encoding='utf-8')
    assert atu._ultima_consulta() == 0
    (tmp_path / 'estado.json').write_text('{"ultima_consulta": "x"}', encoding='utf-8')
    assert atu._ultima_consulta() == 0


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


@pytest.mark.parametrize('final, tag', [
    ('https://github.com/x/y/releases/tag/v1.4.2', 'v1.4.2'),
    ('https://github.com/x/y/releases/tag/v1.5.0-rc1', 'v1.5.0-rc1'),
    ('https://github.com/x/y/releases', None),
])
def test_ultima_versao_le_o_redirecionamento(monkeypatch, final, tag):
    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def geturl(self): return final
    monkeypatch.setattr(atu, '_abrir', lambda url, t: Resp())
    assert atu.ultima_versao('x/y') == tag


class _Download(io.BytesIO):
    def __init__(self, dados, total):
        super().__init__(dados)
        self.headers = {'Content-Length': str(total)}
    def __enter__(self): return self
    def __exit__(self, *a): pass


INFO = {'versao': '9.0.0', 'instalador': 'exe', 'hash': 'sha'}


def _servidor(conteudo, total, hash_txt):
    def abrir(url, t):
        if url == 'sha':
            if hash_txt is None:
                raise atu.urllib.error.URLError('404')
            return _Download(hash_txt.encode(), len(hash_txt))
        return _Download(conteudo, total)
    return abrir


def test_download_completo_e_conferido(monkeypatch, tmp_path):
    import hashlib
    dados = b'x' * 1000
    h = hashlib.sha256(dados).hexdigest()
    monkeypatch.setattr(atu.tempfile, 'gettempdir', lambda: str(tmp_path))
    monkeypatch.setattr(atu, '_abrir', _servidor(dados, 1000, f'{h}  Penetro3D-Setup.exe\n'))
    vistos = []
    p = atu.baixar(INFO, lambda a, b: vistos.append(a))
    assert open(p, 'rb').read() == dados and vistos[-1] == 1000


def test_hash_diferente_nao_instala(monkeypatch, tmp_path):
    monkeypatch.setattr(atu.tempfile, 'gettempdir', lambda: str(tmp_path))
    monkeypatch.setattr(atu, '_abrir', _servidor(b'x' * 1000, 1000, '0' * 64))
    with pytest.raises(IOError, match='SHA-256'):
        atu.baixar(INFO)
    assert not list(tmp_path.iterdir())


def test_sem_hash_publicado_nao_instala(monkeypatch, tmp_path):
    monkeypatch.setattr(atu.tempfile, 'gettempdir', lambda: str(tmp_path))
    monkeypatch.setattr(atu, '_abrir', _servidor(b'x' * 1000, 1000, None))
    with pytest.raises(IOError, match='SHA-256'):
        atu.baixar(INFO)
    assert not list(tmp_path.iterdir())


def test_download_cortado_nao_fica(monkeypatch, tmp_path):
    monkeypatch.setattr(atu.tempfile, 'gettempdir', lambda: str(tmp_path))
    monkeypatch.setattr(atu, '_abrir', _servidor(b'x' * 500, 1000, 'a' * 64))
    with pytest.raises(IOError):
        atu.baixar(INFO)
    assert not list(tmp_path.iterdir())
