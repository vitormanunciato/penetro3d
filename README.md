<img src="app/icone.svg" width="72" alt="">

# Penetro3D

**Autoria:** ANUNCIATO, V.M.

Mapas 3D de compactação do solo a partir dos contornos dos talhões (KML) e da planilha do penetrômetro **Falker PenetroLOG**. Para cada talhão o programa entrega:

- **relatório 3D interativo (HTML)**: bloco de resistência à penetração que gira com o mouse, cortes por camada, perfis e método. Abre em qualquer navegador, sem internet, inclusive no celular;
- **PDF** para arquivo e impressão: mapas por camada, espessura acima do limite, profundidade da resistência máxima, gráfico por ponto e tabela com uma linha por ponto;
- **CSVs** com os perfis brutos e a grade interpolada.

Também planeja a coleta (malha hexagonal em três níveis de densidade) e exporta o plano para Google Earth, GPS, SIG ou planilha.

## Instalar (Windows 10/11, 64 bits)

1. Baixe **`Penetro3D-Setup.exe`** na [página da versão mais recente](../../releases/latest).
2. Abra o arquivo. Não precisa de senha de administrador nem de Python.
   Se aparecer "O Windows protegeu o computador", clique em **Mais informações → Executar assim mesmo**. O aviso aparece porque o instalador não tem assinatura digital paga.
3. O Penetro3D fica no menu Iniciar e na área de trabalho.

**Atualizações:** o programa consulta esta página (no máximo uma vez por dia) e avisa quando há versão nova. Basta clicar em **Atualizar agora**. Relatórios já gerados não são tocados. Em computadores sem internet, ou onde a TI prefira controlar versões, defina a variável de ambiente `PENETRO3D_SEM_ATUALIZACAO=1`.

## Usar

| Aba | Entrada | Saída |
|---|---|---|
| **1 · Planejar coleta** | KML dos talhões | pontos em KMZ/KML para Google Earth, GPX, GeoJSON ou CSV |
| **2 · Gerar relatórios** | nome do projeto, KML dos talhões, uma planilha do Falker | uma pasta por talhão com HTML 3D, PDF e CSVs |

Os pontos da planilha são distribuídos entre os talhões pela posição GPS. Um ponto fora do polígono, a até 30 m da divisa, entra como "borda". Um ponto fora de todos os talhões aparece em `pontos_nao_atribuidos.csv`. Antes de gerar, o painel de conferência avisa sobre perfis incompletos, leituras atípicas (pedra, raiz) e densidade amostral baixa.

Para experimentar, use os arquivos da pasta `exemplos`, que também é instalada junto com o programa.

### Abrir o plano no Google Earth do celular

Depois de calcular a malha, selecione o nível, mantenha **Google Earth (.KMZ)** como formato e clique em **Exportar**.
Envie o arquivo `.kmz` ao celular e escolha **Abrir com Google Earth**. Ele contém o
limite do talhão, os pontos numerados, a ordem de coleta e a rota sugerida. A linha
liga os pontos para orientar a caminhada; ela não é uma rota por estradas.

## Como o mapa é feito, em resumo

- **Interpolação:** IDW (potência 2) camada a camada, a cada 2,5 cm, sem misturar profundidades, numa grade de 12 m recortada pelo talhão. Açudes e outros buracos do KML ficam fora.
- **Classes:** < 1.500 kPa baixa, 1.500–2.500 moderada, > 2.500 restritiva. A escala de cor satura em 3.500 kPa, para que um impedimento pontual não apague o contraste do resto.
- **Validação cruzada por camada:** o selo **com / sem suporte espacial** mostra se interpolar reduz o erro em relação a simplesmente usar a média do talhão naquela camada. Quando não reduz, o mapa diz *quanto*, mas não *onde*.

O relatório traz o método completo, as incertezas e o que conferir no campo.

## Tutorial de uso

### 1. Prepare os arquivos

Tenha em mãos:

- o **KML com o limite de cada talhão**; cada polígono deve ter um nome diferente;
- a **planilha exportada do Falker PenetroLOG**, com coordenadas GPS e leituras por profundidade.

Para conhecer o fluxo antes de trabalhar com dados próprios, use os arquivos fictícios da pasta `exemplos`.

### 2. Planeje a coleta

1. Abra o Penetro3D e entre na aba **1 · Planejar coleta**.
2. Selecione o arquivo KML dos talhões.
3. Escolha a densidade da malha: menor, recomendada ou maior.
4. Confira no mapa se os pontos estão distribuídos corretamente dentro dos limites.
5. Exporte o formato adequado ao trabalho:
   - **Google Earth (.KMZ):** opção padrão e mais simples para visualizar o limite, os pontos e a sequência no celular;
   - **Google Earth (.KML):** alternativa sem compactação para sistemas que exigem KML;
   - **GPX, GeoJSON ou CSV:** integração com outros aplicativos e equipamentos.

### 3. Leve o plano ao celular

Envie o `.kmz` ao celular, toque no arquivo e escolha **Abrir com Google Earth**. A linha exibida é uma sugestão de sequência entre os pontos, não uma rota por estradas.

### 4. Faça a coleta no campo

1. Vá até cada ponto planejado e confirme a posição pelo GPS.
2. Realize a leitura com o penetrômetro conforme o procedimento da equipe.
3. Registre na ficha ou no procedimento da equipe qual ponto foi concluído antes de seguir para o próximo.
4. Ao terminar, exporte a planilha no software do Falker sem alterar nomes de colunas, coordenadas ou valores.

> **Atenção:** a precisão do GPS do celular varia. Use o Google Earth como orientação de navegação, não como substituto de um receptor de maior precisão quando o protocolo exigir posicionamento rigoroso.

### 5. Gere os relatórios

1. Volte ao Penetro3D e abra a aba **2 · Gerar relatórios**.
2. Informe o nome do projeto.
3. Selecione o mesmo KML usado no planejamento e a planilha exportada pelo Falker.
4. Escolha a pasta de saída e clique em **Gerar relatórios**.
5. Leia o painel de conferência antes de interpretar os mapas. Verifique pontos fora dos talhões, perfis incompletos, leituras atípicas e densidade amostral baixa.

O programa cria uma pasta para cada talhão com o relatório 3D em HTML, o relatório em PDF e os arquivos CSV. Abra o HTML para exploração interativa e use o PDF para impressão e arquivamento.

### 6. Interprete com cautela

- Confira se o número de pontos e os limites dos talhões estão corretos.
- Compare camadas, perfis e espessura acima do limite; não tome decisões por uma única imagem.
- Observe o selo de validação espacial. Quando ele indicar **sem suporte espacial**, os dados descrevem o nível médio de resistência, mas não sustentam a localização precisa de zonas dentro do talhão.
- Relacione os resultados com umidade, textura, manejo, tráfego de máquinas e observações de campo.
- Preserve os arquivos originais do KML e do Falker para permitir conferência e reprodução da análise.

## Dados neste repositório

O repositório é público e **não contém dados reais de nenhuma propriedade**. A pasta `exemplos/` tem uma fazenda fictícia gerada por `exemplos/gerar_exemplo.py`: polígonos inventados e leituras simuladas. Não adicione KMLs ou planilhas de campo aos commits. O `.gitignore` já exclui `saidas/`.

## Desenvolvimento

```bash
pip install -r requirements.txt
python -m pytest testes                          # 52 testes, ~10 s
python app/penetro3d_app.py                      # abre a janela
python app/penetro3d_app.py --cli --projeto Teste \
  --kml exemplos/talhoes_exemplo.kml --xlsx exemplos/penetrometria_exemplo.xlsx --saida saidas
```

`app/vendor/plotly.min.js` (plotly.js 2.35.2) não vai para o git. Sem ele, o relatório gerado a partir do código busca o plotly.js na internet. O instalador baixa e confere o arquivo.

**Montar o instalador** (no Linux; o GitHub Actions faz isso sozinho):

```bash
sudo apt install msitools nsis unzip curl python3.13
instalador/construir_windows.sh        # → dist/Penetro3D-Setup.exe
```

O script extrai o Python oficial para Windows dos MSIs do python.org, instala os wheels `win_amd64` com as versões exatas de `requirements-win.txt` e compila o instalador com o NSIS.

**Lançar uma versão:**

1. Mude `VERSAO` em `app/penetro3d_versao.py`.
2. Faça o commit, crie uma tag `vX.Y.Z` igual à versão do código e rode `git push --follow-tags`.
3. O workflow testa, monta o instalador, instala num Windows limpo, gera os relatórios do exemplo e publica a versão. O texto da tag vira o "O que mudou" que aparece no programa.

## Estrutura

```
app/
  penetro3d_app.py           janela (tkinter) e linha de comando
  penetro3d_core.py          KML, planilha Falker, interpolação, validação, HTML
  penetro3d_pdf.py           relatório PDF
  penetro3d_amostragem.py    malha hexagonal e rota de coleta
  penetro3d_atualizacao.py   consulta de versão nova no GitHub
  relatorio_template.html    o relatório 3D
exemplos/                    fazenda fictícia
instalador/                  script de montagem e instalador NSIS
testes/                      pytest
```
