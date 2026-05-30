# Estrutura do Projeto MacroFlow

MacroFlow e um aplicativo desktop para Windows que grava, exibe, edita, salva e reproduz macros de teclado e mouse.

## Visao geral

O projeto foi separado em modulos para facilitar manutencao, leitura e evolucao:

```text
outputs/
+-- macro_recorder.py
+-- requirements.txt
+-- README.md
+-- PROJECT_STRUCTURE.md
+-- macros/
+-- macroflow/
    +-- __init__.py
    +-- app.py
    +-- constants.py
    +-- engine.py
    +-- input_utils.py
    +-- timeline.py
```

## Arquivos principais

### `macro_recorder.py`

Arquivo de entrada do programa.

Responsabilidades:

- importar `main` de `macroflow.app`
- iniciar a aplicacao quando executado pelo Python

Este arquivo deve continuar pequeno. A logica do app nao deve ser colocada aqui.

### `macroflow/app.py`

Modulo da interface grafica.

Responsabilidades:

- criar a janela principal com CustomTkinter
- montar barra lateral, cabecalho, painel ao vivo, timeline, tabela e editor
- processar eventos enviados pelo motor de macros
- salvar, carregar, excluir e limpar macros
- atualizar a tabela e a timeline visual
- controlar tema claro/escuro

Quando mexer aqui:

- alterar layout da tela
- adicionar botoes
- mudar textos visuais
- mudar comportamento de clique na interface
- alterar edicao da tabela

### `macroflow/engine.py`

Modulo do motor de gravacao e reproducao.

Responsabilidades:

- capturar teclado e mouse usando `pynput`
- iniciar e parar gravacao
- guardar eventos com tempo relativo
- enviar eventos em tempo real para a interface
- reproduzir a macro capturada
- tratar atalhos globais como `F8`, `F9` e `Esc`

Quando mexer aqui:

- mudar como os eventos sao gravados
- adicionar novos tipos de evento
- alterar atalhos globais
- ajustar a velocidade ou comportamento da reproducao

### `macroflow/timeline.py`

Modulo responsavel por desenhar a linha do tempo visual.

Responsabilidades:

- desenhar blocos de teclas
- desenhar icones de mouse
- mostrar o tempo entre eventos em `ms` ou `s`
- adaptar cores ao tema claro/escuro

Quando mexer aqui:

- mudar o estilo visual da timeline
- alterar o formato dos blocos
- mudar cores, tamanhos ou espacamentos
- melhorar a representacao de mouse, scroll ou teclas especiais

### `macroflow/input_utils.py`

Modulo de utilidades para eventos de entrada.

Responsabilidades:

- converter teclas capturadas em dados salvos no JSON
- reconstruir teclas a partir dos dados salvos
- gerar nomes legiveis para teclas
- transformar os detalhes de um evento em texto JSON para a tabela

Quando mexer aqui:

- ajustar nomes de teclas
- mudar formato de serializacao
- melhorar a exibicao dos detalhes na tabela

### `macroflow/constants.py`

Modulo de constantes e caminhos.

Responsabilidades:

- definir o diretorio principal do app
- definir a pasta onde as macros sao salvas
- garantir que a pasta `macros/` exista

Quando mexer aqui:

- mudar o local onde as macros sao salvas
- adicionar novas constantes globais

### `requirements.txt`

Lista as dependencias Python do projeto:

- `pynput`: captura e reproduz teclado/mouse
- `customtkinter`: cria a interface grafica moderna

### `README.md`

Documento rapido de uso.

Responsabilidades:

- explicar como instalar dependencias
- explicar como executar o programa
- resumir comandos e atalhos principais

### `macros/`

Pasta onde as macros salvas ficam armazenadas em arquivos `.json`.

Cada macro salva contem:

- `version`: versao do formato
- `name`: nome exibido para a macro
- `updated_at`: data/hora da ultima gravacao
- `events`: lista de eventos capturados

## Fluxo de funcionamento

### Ao abrir o app

1. `macro_recorder.py` chama `main()`.
2. `main()` cria uma instancia de `MacroApp`.
3. `MacroApp` monta a interface.
4. `MacroApp` cria o `MacroEngine`.
5. Os listeners de teclado e mouse sao iniciados.
6. A lista de macros salvas e carregada da pasta `macros/`.

### Ao gravar uma macro

1. O usuario clica em `Gravar` ou pressiona `F8`.
2. `MacroApp` chama `engine.start_recording()`.
3. `MacroEngine` limpa a lista de eventos e inicia o contador de tempo.
4. Cada tecla, clique ou scroll capturado vira um evento.
5. O motor envia o evento para a interface via `ui_queue`.
6. A interface atualiza a tabela e a timeline em tempo real.
7. Ao parar, `MacroEngine` envia a lista final de eventos para a interface.

### Ao salvar uma macro

1. O usuario informa o nome da macro.
2. `MacroApp` cria um nome seguro para arquivo.
3. A macro e salva em `macros/<nome>.json`.
4. A lista lateral de macros e atualizada.

### Ao reproduzir uma macro

1. O usuario seleciona uma macro e clica em `Reproduzir` ou pressiona `F9`.
2. `MacroApp` envia os eventos atuais para `MacroEngine`.
3. O motor espera 3 segundos para o usuario focar a janela alvo.
4. Os eventos sao executados respeitando os intervalos de tempo capturados.

## Formato basico de evento

Exemplo de tecla:

```json
{
  "type": "key",
  "key": {
    "kind": "char",
    "value": "a"
  },
  "pressed": true,
  "t": 0.153
}
```

Exemplo de clique:

```json
{
  "type": "mouse_click",
  "x": 610,
  "y": 420,
  "button": "left",
  "pressed": true,
  "t": 1.245
}
```

Exemplo de movimento de mouse:

```json
{
  "type": "mouse_move",
  "x": 700,
  "y": 510,
  "t": 2.031
}
```

## Guia rapido para futuras alteracoes

Para mudar a aparencia da janela:

- edite `macroflow/app.py`

Para mudar a linha do tempo visual:

- edite `macroflow/timeline.py`

Para mudar a captura ou reproducao:

- edite `macroflow/engine.py`

Para mudar como teclas aparecem ou sao salvas:

- edite `macroflow/input_utils.py`

Para mudar onde macros sao salvas:

- edite `macroflow/constants.py`

## Boas praticas adotadas

- `macro_recorder.py` e apenas ponto de entrada.
- A interface nao executa diretamente a logica de captura.
- O motor de macros se comunica com a interface por fila (`ui_queue`).
- A timeline visual fica isolada em um modulo proprio.
- Arquivos de macro usam JSON legivel e editavel.
- Cada modulo tem uma responsabilidade principal.
