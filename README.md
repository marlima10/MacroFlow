# MacroFlow

Aplicativo simples para gravar, editar, salvar e reproduzir macros de teclado e mouse no Windows.
Agora a interface usa CustomTkinter, com botoes modernos e alternancia entre modo claro e escuro.

## Instalar

```powershell
python -m pip install -r requirements.txt
```

## Rodar

```powershell
python macro_recorder.py
```

## Como usar

- Clique em `Gravar` ou pressione `F8` para iniciar.
- Faca os cliques e teclas da macro.
- Veja no painel `Ao vivo` quais teclas ou botoes do mouse estao pressionados em tempo real.
- Clique em `Parar` ou pressione `F8` de novo para parar.
- Digite um nome e clique em `Salvar`.
- Selecione uma macro na lista lateral para carregar; a macro ativa fica destacada.
- Clique em `Reproduzir` ou pressione `F9`.
- Ative `Loop` para repetir a macro ate pressionar `F10`.
- Pressione `F10` para parar a reproducao da macro.
- Enquanto a macro estiver em reproducao, um alerta verde piscando aparece no painel superior.
- Veja os atalhos em cards no painel superior e use `Editar atalhos` para alterar os padroes.
- Veja os eventos no painel visual em formato de linha do tempo.
- Use `Limpar` para remover todos os eventos da macro atual.
- Dê duplo clique em uma celula da tabela para editar tempo, tipo ou dados JSON ali mesmo.
- Voce tambem pode selecionar um evento e editar pelos campos de baixo.
- Use o switch `Modo escuro` para alternar entre tema escuro e claro.
- Pressione `Esc` para fechar.

Ao reproduzir, o programa espera 3 segundos para voce colocar a janela certa em foco.
As macros ficam salvas na pasta `macros`.
Os atalhos personalizados ficam salvos em `shortcuts.json`.

## Macro inteligente

Use `Macro inteligente` no menu lateral para abrir a tela de navegacao visual.

Essa tela permite:

- informar um alvo visual, como `IMPREZA 22B`
- escanear a tela procurando a borda verde do item selecionado
- procurar o texto alvo com OCR
- navegar usando setas ate o alvo

Dependencias extras:

- `Pillow`
- `opencv-python`
- `pytesseract`
- Tesseract OCR instalado no Windows

Se alguma dependencia estiver ausente, clique em `Verificar dependencias` na tela inteligente.

## Organizacao do codigo

- `macro_recorder.py`: arquivo principal para executar o app.
- `macroflow/app.py`: interface grafica e fluxo da tela.
- `macroflow/engine.py`: gravacao, captura e reproducao de teclado/mouse.
- `macroflow/timeline.py`: desenho da linha do tempo visual.
- `macroflow/input_utils.py`: conversao e nomes de teclas/eventos.
- `macroflow/smart_engine.py`: leitura da tela e navegacao por alvo visual.
- `macroflow/constants.py`: caminhos usados pelo projeto.
