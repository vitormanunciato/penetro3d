#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Penetro3D — planejamento amostral e relatórios de compactação do solo.

Duas etapas, duas abas:

  1 · Planejar coleta   KML → malha hexagonal em três níveis de densidade, com rota
                        de caminhamento, exportada em KMZ (padrão), KML, GPX,
                        GeoJSON ou CSV.

  2 · Gerar relatórios  KML + planilha do Falker → conferência dos dados antes de
                        processar, depois HTML interativo, PDF e CSV por talhão.

    python penetro3d_app.py                     abre a janela
    python penetro3d_app.py --cli --projeto "Safra 26" \\
        --kml t1.kml t2.kml --xlsx penetro.xlsx --saida ./saidas
    python penetro3d_app.py --plano --kml t1.kml --saida ./planos
    python penetro3d_app.py --versao

As dependências pesadas (pandas, pyproj, matplotlib…) só são importadas quando o
processamento começa, para que a janela abra rápido.
"""

import os
import queue
import sys
import threading
import traceback

AQUI = os.path.dirname(os.path.abspath(__file__))
if AQUI not in sys.path:
    sys.path.insert(0, AQUI)

from penetro3d_versao import AUTOR, REPO_GITHUB, VERSAO  # noqa: E402

APP = 'Penetro3D'

VERDE1, VERDE3, VERDE5 = '#155A54', '#00A76D', '#72BF44'
FUNDO, CARTAO, LINHA = '#F4F6F2', '#FFFFFF', '#DCE3D9'
TINTA, TINTA2, TINTA3 = '#12211D', '#3E4F49', '#6C7B75'
AMBAR, VERMELHO, CINZA = '#C8860D', '#C62828', '#727D84'
AVISO_FUNDO = '#E4F1E9'

CORES_NIVEL = {'ok': VERDE1, 'atencao': AMBAR, 'erro': VERMELHO}
ICONES = {'ok': '✓', 'atencao': '!', 'erro': '×'}
ROTULO_GRAU = {'alta': 'PRESCREVER', 'media': 'ZONEAR',
               'baixa': 'CARACTERIZAR', 'insuficiente': 'EXPLORATÓRIO'}

FORMATOS_PLANO = (
    ('Google Earth (.KMZ)', 'kmz'),
    ('Google Earth (.KML)', 'kml'),
    ('GPS (.GPX)', 'gpx'),
    ('GeoJSON (.GeoJSON)', 'geojson'),
    ('Tabela de pontos (.CSV)', 'csv'),
    ('Todos os formatos', 'todos'),
)
FORMATO_PLANO_PADRAO = FORMATOS_PLANO[0][0]


def _preparar_windows():
    """Ajustes que só existem no Windows, feitos antes de criar a janela.

    · Nitidez: sem declarar suporte a DPI, o Windows estica a janela em telas com
      escala de 125–150% e todo o texto fica borrado.
    · Barra de tarefas: sem um AppUserModelID próprio, o Windows agrupa a janela com
      o Python e mostra o ícone dele, não o do Penetro3D.
    """
    if not sys.platform.startswith('win'):
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('FAPA.Penetro3D')
    except (AttributeError, OSError):
        pass


# ══════════════════════════════════════════════════════════════════ interface ══
def abrir_janela():
    _preparar_windows()
    import tkinter as tk
    import webbrowser
    from tkinter import filedialog, messagebox, ttk

    class Janela:
        def __init__(self, raiz):
            self.raiz = raiz
            self.fila = queue.Queue()
            self.rodando = False
            self.destino = None
            self.conf = None
            self.planos = None
            self.talhoes_plano = None
            self.htmls = []
            self.kmls_rel, self.kmls_pl = [], []
            self.info_atualizacao = None

            raiz._penetro3d = self          # ponto de entrada para testes de interface
            raiz.title(f'{APP} {VERSAO} — penetrometria')
            raiz.configure(bg=FUNDO)
            # medidas em pixel acompanham a escala da tela (125%, 150%…)
            self.esc = max(1.0, min(2.5, raiz.winfo_fpixels('1i') / 96.0))
            raiz.minsize(self.px(940), self.px(720))
            raiz.geometry(f'{self.px(1000)}x{self.px(800)}')
            ico = os.path.join(AQUI, 'icone.ico')
            if sys.platform.startswith('win') and os.path.isfile(ico):
                try:
                    raiz.iconbitmap(default=ico)
                except tk.TclError:
                    pass
            # logo do cabeçalho: o PNG mais próximo da escala da tela (Tk não reamostra bem)
            self.logo = None
            alvo = 48 * self.esc
            lado = min((48, 72, 96), key=lambda n: abs(n - alvo))
            try:
                self.logo = tk.PhotoImage(file=os.path.join(AQUI, f'icone_{lado}.png'))
                if not sys.platform.startswith('win'):
                    raiz.iconphoto(True, self.logo)
            except tk.TclError:
                pass
            self._estilos()

            topo = ttk.Frame(raiz, padding=(20, 14, 20, 0))
            topo.pack(fill='x')
            if self.logo is not None:
                tk.Label(topo, image=self.logo, bg=FUNDO, bd=0).pack(
                    side='left', padx=(0, self.px(12)))
            esq = ttk.Frame(topo)
            esq.pack(side='left')
            ttk.Label(esq, text='PENETROMETRIA · RESISTÊNCIA DO SOLO À PENETRAÇÃO',
                      style='Olho.TLabel').pack(anchor='w')
            ttk.Label(esq, text=APP, style='Titulo.TLabel').pack(anchor='w')
            self.lb_versao = ttk.Label(topo, text=f'versão {VERSAO} · verificar atualizações',
                                       style='Link.TLabel', cursor='hand2')
            self.lb_versao.pack(side='right', anchor='ne', pady=(4, 0))
            self.lb_versao.bind('<Button-1>', lambda e: self._verificar_atualizacao(True))

            # aviso de versão nova: escondido até haver o que dizer
            self.aviso = tk.Frame(raiz, bg=AVISO_FUNDO, highlightthickness=1,
                                  highlightbackground='#B9D9C5')
            self.lb_aviso = tk.Label(self.aviso, bg=AVISO_FUNDO, fg=TINTA, anchor='w',
                                     font=('Segoe UI', 10), justify='left')
            self.lb_aviso.pack(side='left', padx=(14, 10), pady=9, fill='x', expand=True)
            self.bt_depois = ttk.Button(self.aviso, text='Depois',
                                        command=lambda: self.aviso.pack_forget())
            self.bt_depois.pack(side='right', padx=(4, 10), pady=6)
            self.bt_notas = ttk.Button(self.aviso, text='O que mudou',
                                       command=lambda: webbrowser.open(
                                           self.info_atualizacao['pagina']))
            self.bt_notas.pack(side='right', padx=4, pady=6)
            self.bt_atualizar = ttk.Button(self.aviso, text='Atualizar agora',
                                           style='Acao.TButton',
                                           command=self._atualizar_agora)
            self.bt_atualizar.pack(side='right', padx=4, pady=6)

            self.abas = ttk.Notebook(raiz)
            self.abas.pack(fill='both', expand=True, padx=16, pady=(10, 14))
            self.aba_pl = ttk.Frame(self.abas, padding=16)
            self.aba_rel = ttk.Frame(self.abas, padding=16)
            self.abas.add(self.aba_pl, text='  1 · Planejar coleta  ')
            self.abas.add(self.aba_rel, text='  2 · Gerar relatórios  ')
            rodape = ttk.Frame(raiz)
            rodape.pack(fill='x', padx=20, pady=(0, 10))
            ttk.Label(rodape, text=f'Autoria: {AUTOR} · Licença MIT',
                      style='Dica.TLabel').pack(side='left')
            url_github = f'https://github.com/{REPO_GITHUB}'
            link_github = ttk.Label(
                rodape, text=url_github, style='Link.TLabel', cursor='hand2', takefocus=True)
            link_github.pack(side='right')
            link_github.bind('<Button-1>', lambda _e: webbrowser.open(url_github))
            link_github.bind('<Return>', lambda _e: webbrowser.open(url_github))
            link_github.bind('<space>', lambda _e: webbrowser.open(url_github))

            self._montar_planejamento()
            self._montar_relatorios()
            self.raiz.after(120, self._bombear)
            self.raiz.after(1500, lambda: self._verificar_atualizacao(False))

        def px(self, n):
            return int(round(n * self.esc))

        # ─────────────────────────────────────────────────────────── estilos ──
        def _estilos(self):
            e = ttk.Style()
            try:
                e.theme_use('clam')
            except tk.TclError:
                pass
            e.configure('TFrame', background=FUNDO)
            e.configure('TNotebook', background=FUNDO, borderwidth=0)
            e.configure('TNotebook.Tab', font=('Segoe UI', 10), padding=(14, 8))
            e.map('TNotebook.Tab', background=[('selected', CARTAO)],
                  foreground=[('selected', VERDE1)])
            e.configure('TLabel', background=FUNDO, foreground=TINTA, font=('Segoe UI', 10))
            e.configure('Rot.TLabel', foreground=TINTA2, font=('Segoe UI', 9))
            e.configure('Dica.TLabel', foreground=TINTA3, font=('Segoe UI', 8))
            e.configure('Link.TLabel', foreground=VERDE1, font=('Segoe UI', 9, 'underline'))
            e.configure('Titulo.TLabel', foreground=TINTA, font=('Segoe UI', 18, 'bold'))
            e.configure('Olho.TLabel', foreground=TINTA3, font=('Segoe UI', 8, 'bold'))
            e.configure('Secao.TLabel', foreground=TINTA, font=('Segoe UI', 10, 'bold'))
            e.configure('TButton', font=('Segoe UI', 9), padding=(10, 5))
            e.configure('Acao.TButton', font=('Segoe UI', 10, 'bold'), padding=(16, 9))
            e.configure('TEntry', fieldbackground=CARTAO)
            e.configure('TCheckbutton', background=FUNDO, foreground=TINTA2,
                        font=('Segoe UI', 9))
            e.configure('Treeview', background=CARTAO, fieldbackground=CARTAO,
                        font=('Segoe UI', 9), rowheight=self.px(24))
            e.configure('Treeview.Heading', font=('Segoe UI', 8, 'bold'), foreground=TINTA3)

        # ──────────────────────────────────────────────── peças reutilizáveis ──
        def _lista_kml(self, pai, destino, ao_mudar):
            """Caixa de KMLs com os três botões. `destino` é a lista que recebe."""
            env = ttk.Frame(pai)
            cx = tk.Listbox(env, height=4, font=('Consolas', 9), bg=CARTAO, fg=TINTA,
                            relief='solid', bd=1, highlightthickness=0,
                            selectbackground=VERDE3, activestyle='none')
            cx.pack(side='left', fill='both', expand=True)
            bt = ttk.Frame(env)
            bt.pack(side='left', fill='y', padx=(8, 0))

            def add():
                for c in filedialog.askopenfilenames(
                        title='Selecione os KML dos talhões',
                        filetypes=[('Google Earth KML', '*.kml'), ('Todos', '*.*')]):
                    if c not in destino:
                        destino.append(c)
                        cx.insert('end', os.path.basename(c))
                ao_mudar()

            def rem():
                for i in reversed(cx.curselection()):
                    cx.delete(i); destino.pop(i)
                ao_mudar()

            def limpa():
                cx.delete(0, 'end'); destino.clear(); ao_mudar()

            ttk.Button(bt, text='Adicionar…', command=add).pack(fill='x')
            ttk.Button(bt, text='Remover', command=rem).pack(fill='x', pady=(4, 0))
            ttk.Button(bt, text='Limpar', command=limpa).pack(fill='x', pady=(4, 0))
            return env

        def _campo_arquivo(self, pai, var, titulo, tipos, ao_mudar, pasta=False):
            env = ttk.Frame(pai)
            ttk.Entry(env, textvariable=var, font=('Segoe UI', 9)).pack(
                side='left', fill='x', expand=True)

            def escolher():
                c = (filedialog.askdirectory(title=titulo) if pasta else
                     filedialog.askopenfilename(title=titulo, filetypes=tipos))
                if c:
                    var.set(c)
                ao_mudar()

            ttk.Button(env, text='Procurar…', command=escolher).pack(side='left', padx=(8, 0))
            return env

        def _mapinha(self, canvas, aneis_ll, pontos=None):
            """Desenha talhões e pontos num canvas, em lon/lat, mantendo a proporção.

            Longitude é comprimida por cos(lat) para o talhão não sair achatado — um
            grau de longitude vale menos metros que um de latitude.
            """
            import math
            canvas.delete('all')
            L = int(canvas['width']), int(canvas['height'])
            todos = [p for anel in aneis_ll for p in anel]
            if pontos:
                todos += [(x, y) for x, y, *_ in pontos]
            if len(todos) < 2:
                return
            lat_m = sum(p[1] for p in todos) / len(todos)
            k = math.cos(math.radians(lat_m))
            xs = [p[0] * k for p in todos]; ys = [p[1] for p in todos]
            x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
            larg, alt = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)
            m = self.px(10)
            esc = min((L[0] - 2 * m) / larg, (L[1] - 2 * m) / alt)
            offx = (L[0] - larg * esc) / 2
            offy = (L[1] - alt * esc) / 2

            def T(lon, lat):
                return (offx + (lon * k - x0) * esc, L[1] - offy - (lat - y0) * esc)

            for anel in aneis_ll:
                pts = [c for lon, lat in anel for c in T(lon, lat)]
                if len(pts) >= 6:
                    canvas.create_polygon(pts, outline=TINTA3, fill=CARTAO, width=1)
            r = self.px(3)
            for x, y, *resto in (pontos or []):
                cor = resto[0] if resto else VERDE1
                cx, cy = T(x, y)
                canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill=cor,
                                   outline=TINTA, width=1)

        def _texto(self, pai, altura):
            env = ttk.Frame(pai)
            t = tk.Text(env, height=altura, font=('Consolas', 9), bg=CARTAO, fg=TINTA2,
                        relief='solid', bd=1, highlightthickness=0, wrap='word',
                        padx=8, pady=6, state='disabled')
            rol = ttk.Scrollbar(env, command=t.yview)
            t.configure(yscrollcommand=rol.set)
            t.pack(side='left', fill='both', expand=True)
            rol.pack(side='right', fill='y')
            for nivel, cor in CORES_NIVEL.items():
                t.tag_configure(nivel, foreground=cor)
            t.tag_configure('forte', font=('Consolas', 9, 'bold'), foreground=TINTA)
            t.tag_configure('fraco', foreground=TINTA3)
            return env, t

        def _escreve(self, widget, txt, tag=None, rolar=True):
            widget.configure(state='normal')
            widget.insert('end', txt + '\n', tag or ())
            if rolar:
                widget.see('end')            # log: acompanha o fim
            widget.configure(state='disabled')

        def _limpa(self, widget):
            widget.configure(state='normal')
            widget.delete('1.0', 'end')
            widget.configure(state='disabled')

        # ═══════════════════════════════════════════ aba 1 · planejar coleta ══
        def _montar_planejamento(self):
            q = self.aba_pl
            q.columnconfigure(0, weight=1)
            self.v_epsg_pl = tk.StringVar(value='31982')
            self.v_recuo = tk.StringVar(value='15')
            self.v_saida_pl = tk.StringVar(
                value=os.path.join(os.path.expanduser('~'), 'Documents'))

            ttk.Label(q, text='Antes de ir a campo: quantos pontos, onde, e o que cada '
                              'densidade permite afirmar.', style='Rot.TLabel'
                      ).grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 12))

            ttk.Label(q, text='Talhões (KML)', style='Secao.TLabel').grid(
                row=1, column=0, sticky='w', pady=(0, 4))
            self._lista_kml(q, self.kmls_pl, self._kml_plano_mudou).grid(
                row=2, column=0, columnspan=2, sticky='we')

            opc = ttk.Frame(q)
            opc.grid(row=3, column=0, columnspan=2, sticky='we', pady=(12, 0))
            ttk.Label(opc, text='EPSG', style='Rot.TLabel').pack(side='left')
            ttk.Entry(opc, textvariable=self.v_epsg_pl, width=8).pack(side='left', padx=(6, 4))
            self.lb_epsg_pl = ttk.Label(opc, text='', style='Dica.TLabel')
            self.lb_epsg_pl.pack(side='left', padx=(0, 18))
            ttk.Label(opc, text='Recuo da bordadura (m)', style='Rot.TLabel').pack(side='left')
            ttk.Entry(opc, textvariable=self.v_recuo, width=6).pack(side='left', padx=(6, 18))
            self.bt_calcular = ttk.Button(opc, text='Calcular malha',
                                          command=self._planejar, state='disabled')
            self.bt_calcular.pack(side='left')

            ttk.Label(q, text='A bordadura é sempre mais compactada por manobra; '
                              'amostrar ali enviesa o talhão inteiro.',
                      style='Dica.TLabel').grid(row=4, column=0, columnspan=2,
                                                sticky='w', pady=(4, 12))

            corpo = ttk.Frame(q)
            corpo.grid(row=5, column=0, columnspan=2, sticky='nsew')
            q.rowconfigure(5, weight=1)
            corpo.columnconfigure(0, weight=1)

            cols = ('nivel', 'pontos', 'dens', 'malha', 'cobertura', 'km', 'horas')
            self.tv = ttk.Treeview(corpo, columns=cols, show='headings', height=4)
            for c, t, w in (('nivel', 'Nível', 150), ('pontos', 'Pontos', 60),
                            ('dens', 'pt/ha', 60), ('malha', 'Malha', 70),
                            ('cobertura', 'Pior dist.', 75), ('km', 'Caminhada', 80),
                            ('horas', 'Tempo est.', 80)):
                self.tv.heading(c, text=t)
                self.tv.column(c, width=self.px(w), anchor='center' if c != 'nivel' else 'w')
            self.tv.grid(row=0, column=0, sticky='we')
            self.tv.bind('<<TreeviewSelect>>', lambda e: self._previa_plano())

            self.cv_pl = tk.Canvas(corpo, width=self.px(230), height=self.px(200), bg=FUNDO,
                                   highlightthickness=1, highlightbackground=LINHA)
            self.cv_pl.grid(row=0, column=1, rowspan=3, sticky='n', padx=(14, 0))

            self.lb_nivel = ttk.Label(corpo, text='', style='Rot.TLabel',
                                      wraplength=self.px(640), justify='left')
            self.lb_nivel.grid(row=1, column=0, sticky='we', pady=(10, 6))

            env, self.txt_pl = self._texto(corpo, 7)
            env.grid(row=2, column=0, sticky='nsew')
            corpo.rowconfigure(2, weight=1)

            rod = ttk.Frame(q)
            rod.grid(row=6, column=0, columnspan=2, sticky='we', pady=(12, 0))
            ttk.Label(rod, text='Salvar em', style='Rot.TLabel').pack(side='left')
            self._campo_arquivo(rod, self.v_saida_pl, 'Onde salvar os planos', None,
                                lambda: None, pasta=True).pack(
                side='left', fill='x', expand=True, padx=(8, 8))
            self.v_formato_pl = tk.StringVar(value=FORMATO_PLANO_PADRAO)
            ttk.Label(rod, text='Formato', style='Rot.TLabel').pack(side='left', padx=(8, 6))
            self.cb_formato_pl = ttk.Combobox(
                rod, textvariable=self.v_formato_pl,
                values=[rotulo for rotulo, _ in FORMATOS_PLANO],
                state='readonly', width=23)
            self.cb_formato_pl.pack(side='left')
            self.bt_exportar = ttk.Button(
                rod, text='Exportar', style='Acao.TButton',
                command=self._exportar_plano, state='disabled')
            self.bt_exportar.pack(side='left', padx=(8, 0))

        def _kml_plano_mudou(self):
            self.bt_calcular.configure(
                state='normal' if self.kmls_pl and not self.rodando else 'disabled')
            self.bt_exportar.configure(state='disabled')
            self.planos = None
            for i in self.tv.get_children():
                self.tv.delete(i)
            self.cv_pl.delete('all')
            self.lb_nivel.configure(text='')
            if self.kmls_pl:
                self._limpa(self.txt_pl)
                self._escreve(self.txt_pl, 'Clique em "Calcular malha".', 'fraco')
                threading.Thread(target=self._deduzir_epsg, daemon=True,
                                 args=(list(self.kmls_pl), 'pl')).start()

        def _deduzir_epsg(self, kmls, onde):
            try:
                from penetro3d_core import carregar_talhoes, epsg_sugerido
                t = carregar_talhoes(kmls)
                self.fila.put(('epsg', (onde, *epsg_sugerido(t))))
            except Exception as e:                                   # noqa: BLE001
                self.fila.put(('epsg_erro', (onde, str(e))))

        def _planejar(self):
            try:
                epsg = int(self.v_epsg_pl.get().strip())
                recuo = float(self.v_recuo.get().strip().replace(',', '.'))
                if recuo < 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror(APP, 'EPSG deve ser inteiro e o recuo, um número '
                                          'não negativo.')
                return
            self.rodando = True
            self.bt_calcular.configure(state='disabled')
            self._limpa(self.txt_pl)
            self._escreve(self.txt_pl, 'Calculando…', 'fraco')
            kmls = list(self.kmls_pl)

            def trabalho():
                try:
                    from penetro3d_amostragem import comparar
                    from penetro3d_core import carregar_talhoes
                    saida = [(t, *comparar(t, epsg, recuo)) for t in carregar_talhoes(kmls)]
                    self.fila.put(('plano', saida))
                except Exception as e:                               # noqa: BLE001
                    self.fila.put(('erro', (str(e), traceback.format_exc(), 'pl')))

            threading.Thread(target=trabalho, daemon=True).start()

        def _mostrar_plano(self, saida):
            from penetro3d_amostragem import NIVEIS
            self.talhoes_plano = saida
            self.planos = saida[0][2]
            for i in self.tv.get_children():
                self.tv.delete(i)
            self._limpa(self.txt_pl)
            for t, tab, planos in saida:
                self._escreve(self.txt_pl, t['nome'], 'forte')
                for _, r in tab.iterrows():
                    self._escreve(self.txt_pl,
                                  f"  {r['nivel']:<18} {r['pontos']:>3} pontos · "
                                  f"{r['densidade_real_pt_ha']} pt/ha · malha "
                                  f"{r['espacamento_m']:.0f} m · {r['caminhada_km']} km")
            for chave, p in self.planos.items():
                cfg = NIVEIS[chave]
                self.tv.insert('', 'end', iid=chave, values=(
                    cfg['rotulo'] + (' (piso)' if p['piso_aplicado'] else ''), p['n'],
                    p['densidade_real'], f"{p['espacamento_m']:.0f} m",
                    f"{p['cobertura_m']:.0f} m", f"{p['caminhada_km']} km",
                    f"{round(p['n'] * 4.5 / 60 + p['caminhada_km'] / 4.0, 1)} h"))
            self.tv.selection_set('intermediario')
            self.bt_exportar.configure(state='normal')

        def _previa_plano(self):
            if not self.planos:
                return
            sel = self.tv.selection()
            if not sel:
                return
            from penetro3d_amostragem import NIVEIS
            chave = sel[0]
            cfg = NIVEIS[chave]
            p = self.planos[chave]
            self.lb_nivel.configure(
                text=f"{cfg['rotulo']} — para {cfg['para_que']}. "
                     f"Entrega: {cfg['entrega']}. Não entrega: {cfg['nao_entrega']}.")
            t = self.talhoes_plano[0][0]
            aneis_ll = [t['anel']] + list(t.get('ilhas') or [])
            pts = [(r.lon, r.lat, VERDE1) for r in p['pontos'].itertuples()]
            self._mapinha(self.cv_pl, aneis_ll, pts)

        def _exportar_plano(self):
            sel = self.tv.selection()
            chave = sel[0] if sel else 'intermediario'
            destino = self.v_saida_pl.get().strip()
            if not os.path.isdir(destino):
                messagebox.showerror(APP, 'A pasta de saída não existe.')
                return
            try:
                from penetro3d_amostragem import exportar, exportar_formato
                pasta = os.path.join(destino, 'plano_amostral')
                rotulo = self.v_formato_pl.get()
                formato = dict(FORMATOS_PLANO).get(rotulo, 'kmz')
                saidas = []
                for t, tab, planos in self.talhoes_plano:
                    if formato == 'todos':
                        saidas.extend(exportar(planos[chave], pasta).values())
                    else:
                        saidas.append(exportar_formato(planos[chave], pasta, formato))
                self._escreve(self.txt_pl, '')
                self._escreve(self.txt_pl,
                              f'{len(saidas)} arquivo(s) em {rotulo} salvo(s) em {pasta}',
                              'ok')
                if formato == 'kmz':
                    self._escreve(
                        self.txt_pl,
                        'O formato padrão abre diretamente no Google Earth do celular.',
                        'fraco')
            except Exception as e:                                   # noqa: BLE001
                messagebox.showerror(APP, str(e))

        # ══════════════════════════════════════════ aba 2 · gerar relatórios ══
        def _montar_relatorios(self):
            q = self.aba_rel
            q.columnconfigure(0, weight=1)
            self.v_projeto = tk.StringVar()
            self.v_xlsx = tk.StringVar()
            self.v_saida = tk.StringVar(value=os.path.join(os.path.expanduser('~'),
                                                           'Documents'))
            self.v_epsg = tk.StringVar(value='31982')
            self.v_res = tk.StringVar(value='12')
            self.v_tol = tk.StringVar(value='30')
            self.v_offline = tk.BooleanVar(value=True)

            lin = 0
            ttk.Label(q, text='Nome do projeto', style='Secao.TLabel').grid(
                row=lin, column=0, sticky='w'); lin += 1
            ttk.Entry(q, textvariable=self.v_projeto, font=('Segoe UI', 10)).grid(
                row=lin, column=0, sticky='we', pady=(2, 10)); lin += 1

            ttk.Label(q, text='Talhões (KML)', style='Secao.TLabel').grid(
                row=lin, column=0, sticky='w'); lin += 1
            self._lista_kml(q, self.kmls_rel, self._entrada_mudou).grid(
                row=lin, column=0, sticky='we', pady=(2, 10)); lin += 1

            ttk.Label(q, text='Penetrometria (Excel do Falker)', style='Secao.TLabel').grid(
                row=lin, column=0, sticky='w'); lin += 1
            self._campo_arquivo(q, self.v_xlsx, 'Selecione a planilha do Falker',
                                [('Excel', '*.xlsx *.xlsm'), ('Todos', '*.*')],
                                self._xlsx_escolhido).grid(
                row=lin, column=0, sticky='we', pady=(2, 10)); lin += 1

            opc = ttk.Frame(q)
            opc.grid(row=lin, column=0, sticky='we'); lin += 1
            ttk.Label(opc, text='EPSG', style='Rot.TLabel').pack(side='left')
            ttk.Entry(opc, textvariable=self.v_epsg, width=8).pack(side='left', padx=(6, 4))
            self.lb_epsg = ttk.Label(opc, text='', style='Dica.TLabel')
            self.lb_epsg.pack(side='left', padx=(0, 16))
            for rot, var in (('Grade (m)', self.v_res), ('Borda (m)', self.v_tol)):
                ttk.Label(opc, text=rot, style='Rot.TLabel').pack(side='left')
                ttk.Entry(opc, textvariable=var, width=6).pack(side='left', padx=(6, 16))
            ttk.Checkbutton(opc, text='HTML abre sem internet',
                            variable=self.v_offline).pack(side='left')

            ttk.Label(q, text='Conferência', style='Secao.TLabel').grid(
                row=lin, column=0, sticky='w', pady=(14, 2)); lin += 1
            conf = ttk.Frame(q)
            conf.grid(row=lin, column=0, sticky='nsew')
            q.rowconfigure(lin, weight=1); lin += 1
            conf.columnconfigure(0, weight=1)
            env, self.txt_conf = self._texto(conf, 11)
            env.grid(row=0, column=0, sticky='nsew')
            conf.rowconfigure(0, weight=1)
            self.cv_rel = tk.Canvas(conf, width=self.px(210), height=self.px(190), bg=FUNDO,
                                    highlightthickness=1, highlightbackground=LINHA)
            self.cv_rel.grid(row=0, column=1, sticky='n', padx=(12, 0))

            rod = ttk.Frame(q)
            rod.grid(row=lin, column=0, sticky='we', pady=(12, 0)); lin += 1
            ttk.Label(rod, text='Salvar em', style='Rot.TLabel').pack(side='left')
            self._campo_arquivo(rod, self.v_saida, 'Onde salvar os relatórios', None,
                                lambda: None, pasta=True).pack(
                side='left', fill='x', expand=True, padx=(8, 10))
            self.barra = ttk.Progressbar(rod, mode='indeterminate', length=self.px(110))
            self.barra.pack(side='left', padx=(0, 10))
            self.bt_gerar = ttk.Button(rod, text='Selecione os arquivos',
                                       style='Acao.TButton', command=self._gerar,
                                       state='disabled')
            self.bt_gerar.pack(side='left')

            # depois de gerar: o que o usuário faz em seguida, em uma linha só
            depois = ttk.Frame(q)
            depois.grid(row=lin, column=0, sticky='w', pady=(8, 0)); lin += 1
            self.bt_relatorio = ttk.Button(depois, text='Abrir relatório 3D',
                                           state='disabled', command=self._abrir_relatorio)
            self.bt_relatorio.pack(side='left', padx=(0, 6))
            self.bt_abrir = ttk.Button(depois, text='Abrir pasta', state='disabled',
                                       command=lambda: self._abrir(self.destino))
            self.bt_abrir.pack(side='left')

            env2, self.txt_log = self._texto(q, 5)
            env2.grid(row=lin, column=0, sticky='we', pady=(10, 0))

            for v in (self.v_projeto, self.v_xlsx, self.v_saida):
                v.trace_add('write', lambda *a: self._rotulo_botao())
            self._rotulo_botao()

        def _xlsx_escolhido(self):
            c = self.v_xlsx.get().strip()
            if c and not self.v_projeto.get().strip():
                self.v_projeto.set(os.path.splitext(os.path.basename(c))[0])
            self._entrada_mudou()

        def _entrada_mudou(self):
            self.conf = None
            self._rotulo_botao()
            if self.kmls_rel:
                threading.Thread(target=self._deduzir_epsg, daemon=True,
                                 args=(list(self.kmls_rel), 'rel')).start()
            if self.kmls_rel and self.v_xlsx.get().strip():
                self._conferir()

        def _rotulo_botao(self):
            if self.rodando:
                self.bt_gerar.configure(state='disabled', text='Processando…')
                return
            if not self.kmls_rel:
                txt, ok = 'Selecione os KML', False
            elif not self.v_xlsx.get().strip():
                txt, ok = 'Selecione a planilha', False
            elif not self.v_projeto.get().strip():
                txt, ok = 'Dê um nome ao projeto', False
            elif not os.path.isdir(self.v_saida.get().strip()):
                txt, ok = 'Escolha a pasta de saída', False
            elif self.conf is None:
                txt, ok = 'Conferindo…', False
            elif not self.conf['pode_prosseguir']:
                txt, ok = 'Dados insuficientes', False
            else:
                n = sum(1 for t in self.conf['talhoes'] if t['n'] >= 3)
                txt, ok = (f'Gerar {n} relatório' + ('s' if n > 1 else ''), True)
            self.bt_gerar.configure(state='normal' if ok else 'disabled', text=txt)

        def _conferir(self):
            self._limpa(self.txt_conf)
            self._escreve(self.txt_conf, 'Conferindo os arquivos…', 'fraco')
            kmls, xlsx = list(self.kmls_rel), self.v_xlsx.get().strip()
            epsg_txt, tol_txt = self.v_epsg.get().strip(), self.v_tol.get().strip()

            def trabalho():
                try:
                    from penetro3d_core import (atribuir_pontos, carregar_talhoes,
                                                conferencia, epsg_sugerido, ler_falker)
                    talhoes = carregar_talhoes(kmls)
                    try:
                        epsg = int(epsg_txt)
                    except ValueError:
                        epsg = epsg_sugerido(talhoes)[0]
                    tol = float(tol_txt.replace(',', '.') or 30)
                    c = conferencia(kmls, xlsx, epsg, tol)
                    pontos, *_ = ler_falker(xlsx)
                    _, sit = atribuir_pontos(pontos, talhoes, epsg, tol)
                    pts = [(float(pontos.lon.iloc[i]), float(pontos.lat.iloc[i]), sit[i])
                           for i in range(len(pontos))]
                    self.fila.put(('conf', (c, talhoes, pts)))
                except Exception as e:                               # noqa: BLE001
                    self.fila.put(('conf_erro', (str(e), traceback.format_exc())))

            threading.Thread(target=trabalho, daemon=True).start()

        def _mostrar_conferencia(self, c, talhoes, pts):
            self.conf = c
            self._limpa(self.txt_conf)
            E = lambda t, tag=None: self._escreve(self.txt_conf, t, tag, rolar=False)  # noqa
            for t in c['talhoes']:
                grau = t['grau']
                E(t['nome'], 'forte')
                E(f"  {t['n']} perfis · {t['area_ha']} ha · {t['densidade']} pt/ha"
                  f"   →   {ROTULO_GRAU[grau]}",
                  'erro' if grau == 'insuficiente' else ('atencao' if grau == 'baixa' else 'ok'))
                E(f"  {t['frase']}", 'fraco')
            E('')
            for a in c['achados']:
                E(f"{ICONES[a['nivel']]} {a['titulo']}", a['nivel'])
                E(f"   {a['detalhe']}")
                if a['acao']:
                    E(f"   → {a['acao']}", 'fraco')
            self.txt_conf.see('1.0')          # começa mostrando o topo, não o fim

            # miniatura: talhões + pontos coloridos pela situação
            cores = {'interno': VERDE1, 'borda': AMBAR, 'fora': VERMELHO}
            aneis_ll = []
            for t in talhoes:
                aneis_ll.append(t['anel'])
                aneis_ll += list(t.get('ilhas') or [])
            self._mapinha(self.cv_rel, aneis_ll, [(x, y, cores[s]) for x, y, s in pts])
            self._rotulo_botao()

        def _gerar(self):
            try:
                epsg = int(self.v_epsg.get().strip())
                res = float(self.v_res.get().strip().replace(',', '.'))
                tol = float(self.v_tol.get().strip().replace(',', '.'))
                if res <= 0 or tol < 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror(APP, 'EPSG deve ser inteiro, a grade maior que zero e '
                                          'a tolerância não negativa.')
                return
            if not os.path.isdir(self.v_saida.get()):
                messagebox.showerror(APP, 'A pasta de saída não existe.')
                return

            self.rodando = True
            self._rotulo_botao()
            for b in (self.bt_abrir, self.bt_relatorio):
                b.configure(state='disabled')
            self.barra.start(12)
            self._limpa(self.txt_log)
            self._escreve(self.txt_log, f'Projeto "{self.v_projeto.get().strip()}" — iniciando…')

            args = (self.v_projeto.get().strip(), list(self.kmls_rel),
                    self.v_xlsx.get().strip(), self.v_saida.get().strip(),
                    epsg, res, tol, self.v_offline.get())

            def trabalho():
                try:
                    from penetro3d_core import processar_projeto
                    r = processar_projeto(args[0], args[1], args[2], args[3], epsg=args[4],
                                          res_m=args[5], tol_borda=args[6], offline=args[7],
                                          log=lambda m: self.fila.put(('log', m)))
                    self.fila.put(('fim', r))
                except Exception as e:                               # noqa: BLE001
                    self.fila.put(('erro', (str(e), traceback.format_exc(), 'rel')))

            threading.Thread(target=trabalho, daemon=True).start()

        # ─────────────────────────────────────────────── abrir e compartilhar ──
        def _abrir(self, caminho):
            """Abre um arquivo ou pasta no aplicativo padrão do sistema."""
            if not caminho:
                return
            if sys.platform.startswith('win'):
                os.startfile(caminho)                                # noqa: S606
            elif sys.platform == 'darwin':
                os.system(f'open "{caminho}"')                       # noqa: S605
            else:
                os.system(f'xdg-open "{caminho}"')                   # noqa: S605

        def _abrir_relatorio(self):
            self._abrir(self.htmls[0] if self.htmls else None)

        # ─────────────────────────────────────────────────────── atualização ──
        def _verificar_atualizacao(self, manual):
            if manual:
                self.lb_versao.configure(text=f'versão {VERSAO} · verificando…')

            def trabalho():
                try:
                    from penetro3d_atualizacao import verificar
                    info = verificar(manual=manual)
                except Exception:                                    # noqa: BLE001
                    info = None
                self.fila.put(('atualizacao', (info, manual)))

            threading.Thread(target=trabalho, daemon=True).start()

        def _mostrar_aviso(self, info):
            self.info_atualizacao = info
            self.lb_aviso.configure(
                text=f"Nova versão {info['versao']} disponível — você usa a {VERSAO}. "
                     f"A atualização leva cerca de um minuto.")
            self.bt_atualizar.configure(state='normal', text='Atualizar agora')
            self.aviso.pack(fill='x', padx=16, pady=(10, 0), before=self.abas)

        def _atualizar_agora(self):
            info = self.info_atualizacao
            if not info:
                return
            if self.rodando:
                messagebox.showinfo(APP, 'Espere o processamento atual terminar.')
                return
            if not sys.platform.startswith('win'):
                webbrowser.open(info['pagina'])
                return
            self.bt_atualizar.configure(state='disabled', text='Baixando… 0%')

            def progresso(feito, total):
                if total:
                    self.fila.put(('baixando', int(feito * 100 / total)))

            def trabalho():
                try:
                    from penetro3d_atualizacao import baixar
                    self.fila.put(('baixado', baixar(info, progresso)))
                except Exception as e:                               # noqa: BLE001
                    self.fila.put(('baixar_erro', str(e)))

            threading.Thread(target=trabalho, daemon=True).start()

        # ────────────────────────────────────────────── fila de mensagens ──
        def _bombear(self):
            try:
                while True:
                    tipo, carga = self.fila.get_nowait()
                    self._tratar(tipo, carga)
            except queue.Empty:
                pass
            self.raiz.after(120, self._bombear)

        def _tratar(self, tipo, carga):
            if tipo == 'log':
                self._escreve(self.txt_log, carga)
            elif tipo == 'epsg':
                onde, epsg, nota = carga
                (self.v_epsg_pl if onde == 'pl' else self.v_epsg).set(str(epsg))
                (self.lb_epsg_pl if onde == 'pl' else self.lb_epsg).configure(text=nota)
            elif tipo == 'epsg_erro':
                onde, msg = carga
                (self.lb_epsg_pl if onde == 'pl' else self.lb_epsg).configure(
                    text='KML não lido')
                if onde == 'pl':
                    self._limpa(self.txt_pl)
                    self._escreve(self.txt_pl, 'ERRO: ' + msg, 'erro')
            elif tipo == 'conf':
                self._mostrar_conferencia(*carga)
            elif tipo == 'conf_erro':
                msg, _ = carga
                self._limpa(self.txt_conf)
                self._escreve(self.txt_conf, 'ERRO: ' + msg, 'erro')
                self.conf = None
                self._rotulo_botao()
            elif tipo == 'plano':
                self.rodando = False
                self._mostrar_plano(carga)
                self._previa_plano()
                self.bt_calcular.configure(state='normal')
            elif tipo == 'fim':
                self.barra.stop()
                self.rodando = False
                self.destino = carga['destino']
                self.htmls = carga.get('htmls') or []
                self._escreve(self.txt_log, '')
                self._escreve(self.txt_log, f"Pronto — {len(carga['talhoes'])} talhão(ões): "
                              + ', '.join(carga['talhoes']), 'ok')
                self._escreve(self.txt_log, f"Salvo em {carga['destino']}", 'ok')
                if carga['orfaos']:
                    self._escreve(self.txt_log, 'Pontos não atribuídos: '
                                  + ', '.join(carga['orfaos']), 'atencao')
                self.bt_abrir.configure(state='normal')
                self.bt_relatorio.configure(state='normal' if self.htmls else 'disabled')
                # um talhão só: abre o relatório, que é o que o usuário faria em seguida
                if len(self.htmls) == 1:
                    self._abrir(self.htmls[0])
                self._rotulo_botao()
            elif tipo == 'erro':
                msg, tb, onde = carga
                self.barra.stop()
                self.rodando = False
                alvo = self.txt_pl if onde == 'pl' else self.txt_log
                self._escreve(alvo, '')
                self._escreve(alvo, 'ERRO: ' + msg, 'erro')
                for linha in tb.strip().splitlines()[-3:]:
                    self._escreve(alvo, '  ' + linha, 'fraco')
                self.bt_calcular.configure(state='normal' if self.kmls_pl else 'disabled')
                self._rotulo_botao()
                messagebox.showerror(APP, msg)
            elif tipo == 'atualizacao':
                info, manual = carga
                self.lb_versao.configure(text=f'versão {VERSAO} · verificar atualizações')
                if info:
                    self._mostrar_aviso(info)
                elif manual:
                    messagebox.showinfo(APP, f'Você está na versão mais recente ({VERSAO}).\n\n'
                                             f'Se estiver sem internet, a verificação não '
                                             f'consegue consultar o GitHub.')
            elif tipo == 'baixando':
                self.bt_atualizar.configure(text=f'Baixando… {carga}%')
            elif tipo == 'baixado':
                v = self.info_atualizacao['versao']
                if messagebox.askyesno(APP, f'Instalador da versão {v} baixado.\n\n'
                                            f'O Penetro3D vai fechar para instalar. '
                                            f'Continuar?'):
                    try:
                        from penetro3d_atualizacao import executar_instalador
                        executar_instalador(carga)
                        self.raiz.after(300, self.raiz.destroy)
                    except Exception as e:                           # noqa: BLE001
                        messagebox.showerror(APP, f'Não consegui abrir o instalador:\n{e}')
                else:
                    self.bt_atualizar.configure(state='normal', text='Atualizar agora')
            elif tipo == 'baixar_erro':
                self.bt_atualizar.configure(state='normal', text='Tentar de novo')
                messagebox.showerror(APP, f'Não consegui baixar a atualização:\n{carga}\n\n'
                                          f'Você também pode baixar pela página:\n'
                                          f'https://github.com/{REPO_GITHUB}/releases')

    raiz = tk.Tk()
    Janela(raiz)
    raiz.mainloop()


# ══════════════════════════════════════════════════════════════════════ CLI ══
def linha_de_comando(argv):
    import argparse
    ap = argparse.ArgumentParser(prog='penetro3d', description=f'{APP} {VERSAO}')
    ap.add_argument('--cli', action='store_true', help='gera relatórios sem janela')
    ap.add_argument('--plano', action='store_true', help='só planeja a malha amostral')
    ap.add_argument('--projeto')
    ap.add_argument('--kml', nargs='+', required=True)
    ap.add_argument('--xlsx')
    ap.add_argument('--saida', required=True)
    ap.add_argument('--epsg', type=int, default=None)
    ap.add_argument('--res', type=float, default=12.0)
    ap.add_argument('--tol', type=float, default=30.0)
    ap.add_argument('--recuo', type=float, default=15.0)
    ap.add_argument('--nivel', default='todos')
    ap.add_argument('--online', action='store_true',
                    help='HTML busca o plotly.js na internet (arquivo bem menor)')
    a = ap.parse_args(argv)

    from penetro3d_core import carregar_talhoes, epsg_sugerido
    epsg = a.epsg
    if epsg is None:
        epsg, nota = epsg_sugerido(carregar_talhoes(a.kml))
        print(f'EPSG {epsg} — {nota}')

    if a.plano:
        from penetro3d_amostragem import NIVEIS, comparar, exportar, planejar
        for t in carregar_talhoes(a.kml):
            print(f"\n{t['nome']}")
            planos = (comparar(t, epsg, a.recuo)[1] if a.nivel == 'todos'
                      else {a.nivel: planejar(t, a.nivel, epsg, a.recuo)})
            for chave, p in planos.items():
                print(f"  {NIVEIS[chave]['rotulo']:<18} {p['n']:>3} pontos · "
                      f"{p['densidade_real']} pt/ha · malha {p['espacamento_m']:.0f} m "
                      f"· {p['caminhada_km']} km")
                exportar(p, a.saida)
        print(f'\n-> {a.saida}')
        return 0

    if not (a.projeto and a.xlsx):
        ap.error('--cli exige --projeto e --xlsx')
    from penetro3d_core import processar_projeto
    r = processar_projeto(a.projeto, a.kml, a.xlsx, a.saida, epsg=epsg, res_m=a.res,
                          tol_borda=a.tol, offline=not a.online)
    print(f"Salvo em {r['destino']}")
    return 0


def _registrar_falha(exc):
    """Sem console (modo janela), um erro na abertura sumiria sem deixar rastro."""
    import datetime
    alvo = None
    try:
        from penetro3d_atualizacao import pasta_usuario
        alvo = os.path.join(pasta_usuario(), 'erro.txt')
        with open(alvo, 'a', encoding='utf-8') as f:
            f.write(f'\n=== {datetime.datetime.now():%d/%m/%Y %H:%M} · {APP} {VERSAO} ===\n')
            f.write(f'Python {sys.version}\n')
            traceback.print_exc(file=f)
    except Exception:                                                # noqa: BLE001
        alvo = None
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk(); r.withdraw()
        messagebox.showerror(APP, f'{APP} não conseguiu abrir.\n\n{exc}\n\n'
                                  + (f'Detalhes gravados em:\n{alvo}' if alvo else ''))
        r.destroy()
    except Exception:                                                # noqa: BLE001
        print('ERRO:', exc, file=sys.stderr)


if __name__ == '__main__':
    # console do Windows redirecionado usa cp1252: "✓" ou "≥" derrubariam um print
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass                                  # pythonw: não há console
    modo_texto = any(a in sys.argv for a in ('--cli', '--plano', '--versao'))
    try:
        if '--versao' in sys.argv:
            print(VERSAO)
            sys.exit(0)
        if modo_texto:
            sys.exit(linha_de_comando(sys.argv[1:]))
        abrir_janela()
    except SystemExit:
        raise
    except BaseException as e:                                       # noqa: BLE001
        if modo_texto:                            # em linha de comando, nada de janela
            traceback.print_exc()
            sys.exit(1)
        _registrar_falha(e)
        sys.exit(1)
