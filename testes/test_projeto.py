"""Ponta a ponta: KML + planilha de exemplo → pasta com HTML, PDF e CSVs."""
import os
from pathlib import Path

import pandas as pd
import pytest

from penetro3d_core import processar_projeto


@pytest.fixture(scope='module')
def saida(tmp_path_factory):
    from conftest import EXEMPLOS
    pasta = tmp_path_factory.mktemp('saida')
    r = processar_projeto('Fazenda Exemplo',
                          [os.path.join(EXEMPLOS, 'talhoes_exemplo.kml')],
                          os.path.join(EXEMPLOS, 'penetrometria_exemplo.xlsx'),
                          str(pasta), log=lambda *_: None)
    return r


def test_estrutura_de_saida(saida):
    d = saida['destino']
    for t in ('Talhao_Norte', 'Talhao_Sul'):
        for arq in (f'{t}.html', f'{t}.pdf', 'perfis_brutos.csv', 'grade_interpolada.csv'):
            assert os.path.getsize(os.path.join(d, t, arq)) > 0, arq
    assert os.path.exists(os.path.join(d, 'resumo_do_projeto.csv'))
    assert os.path.exists(os.path.join(d, 'pontos_nao_atribuidos.csv'))


def test_html_e_autocontido_e_traz_os_dados(saida):
    html = open(saida['htmls'][0], encoding='utf-8').read()
    from penetro3d_core import _plotly_js
    if _plotly_js():                                       # instalador: tudo embutido
        assert 'plotly.js v2.35.2' in html and len(html) > 4_000_000
        assert '<script src="http' not in html
    else:                                                  # rodando do código, sem vendor/
        assert 'cdnjs.cloudflare.com/ajax/libs/plotly.js/2.35.2/' in html
    assert 'Penetro3D' in html
    assert 'ANUNCIATO, V.M.' in html


def test_pdf_tem_paginas(saida):
    pdf = os.path.join(saida['destino'], 'Talhao_Sul', 'Talhao_Sul.pdf')
    with open(pdf, 'rb') as f:
        conteudo = f.read()
    assert conteudo.startswith(b'%PDF') and conteudo.count(b'/Type /Page') >= 4
    assert b'ANUNCIATO, V.M.' in conteudo


def test_resumo_csv(saida):
    r = pd.read_csv(os.path.join(saida['destino'], 'resumo_do_projeto.csv'),
                    sep=';', decimal=',', encoding='utf-8-sig')
    assert len(r) == 2
    assert 'camadas_com_suporte_espacial' in r.columns


def test_grade_csv_sem_buracos(saida):
    g = pd.read_csv(os.path.join(saida['destino'], 'Talhao_Sul', 'grade_interpolada.csv'),
                    sep=';', decimal=',', encoding='utf-8-sig')
    assert len(g) > 1000 and not g.isna().any().any()


def test_interface_nao_oferece_servidor_local_para_celular():
    from conftest import RAIZ
    interface = Path(RAIZ, 'app', 'penetro3d_app.py').read_text(encoding='utf-8')

    assert 'Ver no celular' not in interface
    assert 'def _no_celular' not in interface


def test_rodape_da_interface_exibe_autoria_licenca_e_github():
    from conftest import RAIZ
    interface = Path(RAIZ, 'app', 'penetro3d_app.py').read_text(encoding='utf-8')

    assert "f'Autoria: {AUTOR} · Licença MIT'" in interface
    assert "f'https://github.com/{REPO_GITHUB}'" in interface


def test_aplicativo_e_instalador_nao_mencionam_fapa():
    from conftest import RAIZ
    arquivos = [
        Path(RAIZ, 'app', 'penetro3d_app.py'),
        Path(RAIZ, 'instalador', 'penetro3d.nsi'),
    ]

    for arquivo in arquivos:
        assert 'FAPA' not in arquivo.read_text(encoding='utf-8'), arquivo
