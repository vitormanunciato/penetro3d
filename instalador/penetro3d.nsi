; Instalador do Penetro3D para Windows (NSIS 3).
;
; Instala só para o usuário atual, em %LOCALAPPDATA%\Programs\Penetro3D — não pede
; senha de administrador, o que importa em computador corporativo. Leva junto um
; Python completo e todas as bibliotecas: quem instala não precisa de mais nada.
;
; Rodar a mesma versão (ou uma nova) por cima atualiza: o programa antigo é removido
; antes, para não sobrar arquivo de versão velha. Atalho na área de trabalho só é
; criado na primeira instalação — se a pessoa apagou, a atualização não o devolve.
;
; Montado por instalador/construir_windows.sh, que passa VERSAO, PALCO, SAIDA,
; ICONE e TAMANHO_KB. Linha de comando: /S instala sem perguntas; /D=pasta escolhe
; o destino (precisa ser o último argumento).

Unicode true
SetCompressor /SOLID lzma
SetCompressorDictSize 64

!include "MUI2.nsh"
!include "x64.nsh"
!include "LogicLib.nsh"

!define APP      "Penetro3D"
!define EDITOR   "ANUNCIATO, V.M."
!define CHAVE_UN "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP}"
!define CHAVE    "Software\${APP}"

Name "${APP} ${VERSAO}"
OutFile "${SAIDA}"
InstallDir "$LOCALAPPDATA\Programs\${APP}"
InstallDirRegKey HKCU "${CHAVE}" "Pasta"
RequestExecutionLevel user
ShowInstDetails nevershow
ShowUninstDetails nevershow
BrandingText "${APP} ${VERSAO}"

VIProductVersion "${VERSAO}.0"
VIAddVersionKey /LANG=0 "ProductName" "${APP}"
VIAddVersionKey /LANG=0 "ProductVersion" "${VERSAO}"
VIAddVersionKey /LANG=0 "FileVersion" "${VERSAO}"
VIAddVersionKey /LANG=0 "FileDescription" "Instalador do ${APP}"
VIAddVersionKey /LANG=0 "CompanyName" "${EDITOR}"
VIAddVersionKey /LANG=0 "LegalCopyright" "Código aberto"

Var Atualizando

; ── páginas ────────────────────────────────────────────────────────────────────
!define MUI_ICON   "${ICONE}"
!define MUI_UNICON "${ICONE}"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "Penetro3D ${VERSAO}"
!define MUI_WELCOMEPAGE_TEXT "Mapas 3D de compactação do solo a partir dos talhões (KML) e da planilha do penetrômetro Falker.$\r$\n$\r$\nAutoria: ANUNCIATO, V.M.$\r$\n$\r$\nA instalação é só para o seu usuário, não pede senha de administrador e já inclui tudo o que o programa precisa.$\r$\n$\r$\nSe uma versão anterior estiver instalada, ela será atualizada — seus relatórios não são tocados."
!define MUI_FINISHPAGE_TITLE "Penetro3D instalado"
!define MUI_FINISHPAGE_TEXT "O Penetro3D está no menu Iniciar. Na primeira vez, experimente com os arquivos da pasta exemplos (dentro da pasta do programa)."
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "Abrir o Penetro3D agora"
!define MUI_FINISHPAGE_RUN_FUNCTION Abrir

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "PortugueseBR"

; ── funções ────────────────────────────────────────────────────────────────────
Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "O Penetro3D precisa do Windows 64 bits." /SD IDOK
    Abort
  ${EndIf}
  StrCpy $Atualizando "0"
  IfFileExists "$INSTDIR\python\pythonw.exe" 0 +2
    StrCpy $Atualizando "1"
FunctionEnd

Function Abrir
  SetOutPath "$INSTDIR"
  Exec '"$INSTDIR\python\pythonw.exe" -E -s "$INSTDIR\app\penetro3d_app.py"'
FunctionEnd

; Quando a atualização parte de dentro do programa, ele fecha logo depois de abrir o
; instalador — mas pode levar alguns segundos. Enquanto o Python estiver em uso, a
; DLL dele fica travada; a espera é sobre ela.
Function EsperarFechar
  StrCpy $0 0
  laco:
    IfFileExists "$INSTDIR\python\python313.dll" 0 livre
    ClearErrors
    Rename "$INSTDIR\python\python313.dll" "$INSTDIR\python313.dll.velha"
    IfErrors 0 movida
    IntOp $0 $0 + 1
    IntCmp $0 30 pergunta
    Sleep 500
    Goto laco
  pergunta:
    MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "O Penetro3D ainda está aberto.$\r$\n$\r$\nFeche a janela do programa e clique em Repetir." /SD IDCANCEL IDRETRY repetir
    Abort "O Penetro3D estava aberto; nada foi alterado."
  repetir:
    StrCpy $0 0
    Goto laco
  movida:
    Delete "$INSTDIR\python313.dll.velha"
  livre:
FunctionEnd

; ── instalação ─────────────────────────────────────────────────────────────────
Section "Penetro3D" SecPrincipal
  SectionIn RO
  Call EsperarFechar

  ; versão anterior sai inteira: arquivo velho esquecido é fonte de erro difícil
  RMDir /r "$INSTDIR\python"
  RMDir /r "$INSTDIR\app"
  RMDir /r "$INSTDIR\exemplos"

  SetOutPath "$INSTDIR"
  File /r "${PALCO}\*"
  WriteUninstaller "$INSTDIR\Desinstalar.exe"

  ; atalhos apontam direto para o pythonw (sem janela preta de console). -E -s: um
  ; PYTHONPATH ou pacotes "pip --user" do computador não podem trocar as bibliotecas
  ; que vieram no instalador por outras versões.
  SetOutPath "$INSTDIR"
  CreateShortcut "$SMPROGRAMS\${APP}.lnk" "$INSTDIR\python\pythonw.exe" \
    '-E -s "$INSTDIR\app\penetro3d_app.py"' "$INSTDIR\app\icone.ico" 0 SW_SHOWNORMAL "" \
    "Mapas 3D de compactação do solo"
  ${If} $Atualizando == "0"
    CreateShortcut "$DESKTOP\${APP}.lnk" "$INSTDIR\python\pythonw.exe" \
      '-E -s "$INSTDIR\app\penetro3d_app.py"' "$INSTDIR\app\icone.ico" 0 SW_SHOWNORMAL "" \
      "Mapas 3D de compactação do solo"
  ${EndIf}

  WriteRegStr HKCU "${CHAVE}" "Pasta" "$INSTDIR"
  WriteRegStr HKCU "${CHAVE}" "Versao" "${VERSAO}"
  WriteRegStr HKCU "${CHAVE_UN}" "DisplayName" "${APP}"
  WriteRegStr HKCU "${CHAVE_UN}" "DisplayVersion" "${VERSAO}"
  WriteRegStr HKCU "${CHAVE_UN}" "Publisher" "${EDITOR}"
  WriteRegStr HKCU "${CHAVE_UN}" "DisplayIcon" "$INSTDIR\app\icone.ico"
  WriteRegStr HKCU "${CHAVE_UN}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${CHAVE_UN}" "UninstallString" '"$INSTDIR\Desinstalar.exe"'
  WriteRegStr HKCU "${CHAVE_UN}" "QuietUninstallString" '"$INSTDIR\Desinstalar.exe" /S'
  WriteRegDWORD HKCU "${CHAVE_UN}" "NoModify" 1
  WriteRegDWORD HKCU "${CHAVE_UN}" "NoRepair" 1
  WriteRegDWORD HKCU "${CHAVE_UN}" "EstimatedSize" ${TAMANHO_KB}
SectionEnd

; ── desinstalação ──────────────────────────────────────────────────────────────
; Apaga só o que o instalador pôs. A pasta do usuário (%LOCALAPPDATA%\Penetro3D,
; com preferências) e os relatórios gerados ficam.
Section "Uninstall"
  RMDir /r "$INSTDIR\python"
  RMDir /r "$INSTDIR\app"
  RMDir /r "$INSTDIR\exemplos"
  Delete "$INSTDIR\LEIA-ME.txt"
  Delete "$INSTDIR\Desinstalar.exe"
  RMDir "$INSTDIR"
  Delete "$SMPROGRAMS\${APP}.lnk"
  Delete "$DESKTOP\${APP}.lnk"
  DeleteRegKey HKCU "${CHAVE_UN}"
  DeleteRegKey HKCU "${CHAVE}"
SectionEnd
