"""Ponta a ponta: KML + planilha de exemplo → pasta com HTML, PDF e CSVs."""
import json
import os
import re

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
    m = re.search(r'const D\s*=\s*(\{.*?\});\s*\n', html, re.S)
    if 'cdn.plot.ly' not in html:
        assert 'Plotly' in html and len(html) > 1_000_000      # plotly.js embutido
    assert '</script' not in (m.group(1) if m else '')
    assert 'Penetro3D' in html


def test_pdf_tem_paginas(saida):
    pdf = os.path.join(saida['destino'], 'Talhao_Sul', 'Talhao_Sul.pdf')
    with open(pdf, 'rb') as f:
        conteudo = f.read()
    assert conteudo.startswith(b'%PDF') and conteudo.count(b'/Type /Page') >= 4


def test_resumo_csv(saida):
    r = pd.read_csv(os.path.join(saida['destino'], 'resumo_do_projeto.csv'),
                    sep=None, engine='python')
    assert len(r) == 2
    assert 'camadas_com_suporte_espacial' in r.columns


def test_grade_csv_sem_buracos(saida):
    g = pd.read_csv(os.path.join(saida['destino'], 'Talhao_Sul', 'grade_interpolada.csv'),
                    sep=None, engine='python')
    assert len(g) > 1000 and not g.isna().any().any()
