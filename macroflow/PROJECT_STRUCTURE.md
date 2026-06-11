# Estrutura do Projeto MacroFlow

MacroFlow e um aplicativo desktop para Windows que grava, exibe, edita, salva e reproduz macros de teclado e mouse.

## Visao geral

O projeto foi separado em modulos para facilitar manutencao, leitura e evolucao:

```text
macroflow/
+-- macro_recorder.py
+-- requirements.txt
+-- README.md
+-- config/
+   +-- app.json
+   +-- farm_subaru_impreza_22b.json
+   +-- shortcuts.json
+-- language/
+   +-- en.json
+   +-- pt-br.json
+-- macros/
+-- macroflow/
    +-- __init__.py
    +-- PROJECT_STRUCTURE.md
    +-- app.py
    +-- application/
    |   +-- dtos/
    |   +-- use_cases/
    +-- domain/
    |   +-- entities/
    |   +-- repositories/
    |   +-- value_objects/
    +-- infrastructure/
    |   +-- filesystem/
    |   +-- repositories/
    +-- presentation/
    |   +-- app.py
    |   +-- components/
    |   +-- view_models/
    |   +-- views/
    +-- constants.py
    +-- engine.py
    +-- input_utils.py
    +-- smart_engine.py
    +-- timeline.py
```

## Arquitetura em camadas

O MacroFlow agora segue uma organizacao inspirada em Clean Architecture. A migracao e incremental: o `macroflow/app.py` ainda concentra parte importante da tela, mas persistencia JSON, ports, entidades e alguns casos de uso ja foram separados.

### `macroflow/domain/`

Camada de regra pura.

Responsabilidades:

- definir entidades como `Macro`, `MacroMetadata` e `FarmItem`
- definir value objects como `MatrixPosition` e `Shortcut`
- definir interfaces de repositorio, tambem chamadas de ports
- nao depender de CustomTkinter, arquivos JSON, `pynput` ou detalhes externos

### `macroflow/application/`

Camada de casos de uso.

Responsabilidades:

- orquestrar acoes do sistema sem conhecer a interface
- expor operacoes como salvar macro e calcular a posicao do ultimo carro
- receber dados simples e devolver resultados simples para a camada de apresentacao

### `macroflow/infrastructure/`

Camada de adaptadores externos.

Responsabilidades:

- implementar repositorios JSON
- ler e gravar `config/app.json`, `config/farm_subaru_impreza_22b.json`, `config/shortcuts.json` e macros em `macros/` durante o desenvolvimento
- centralizar caminhos de filesystem usados pelos adaptadores

No executavel portable, esses arquivos continuam sendo gravados ao lado do `.exe`, nas pastas `config/` e `macros/`. Isso permite que o usuario final edite/copie seus dados sem entrar nos arquivos internos do pacote.

### `macroflow/presentation/`

Camada de interface.

Responsabilidades:

- servir como ponto de entrada visual por `macroflow.presentation.app`
- agrupar futuras telas, componentes e view models
- manter CustomTkinter e detalhes de layout afastados das regras puras

Nesta etapa, `presentation/app.py` delega para `macroflow/app.py`. As proximas extrações naturais sao mover cards, popups, timeline visual da tela e view models para `presentation/components`, `presentation/views` e `presentation/view_models`.

## Arquivos principais

### `macro_recorder.py`

Arquivo de entrada do programa.

Responsabilidades:

- importar `main` de `macroflow.presentation.app`
- iniciar a aplicacao quando executado pelo Python

Este arquivo deve continuar pequeno. A logica do app nao deve ser colocada aqui.

### `macroflow/app.py`

Modulo principal da interface grafica.

Responsabilidades:

- criar a janela principal com CustomTkinter
- mostrar a tela inicial com os acessos de Criar / Editar Macro, Executar Macro e Configuracoes
- montar barra lateral, cabecalho, painel ao vivo, timeline, tabela e editor
- exibir a tela de configuracoes com idioma, tema e inicializacao
- carregar textos traduzidos dos arquivos em `language/`
- salvar preferencias gerais em `config/app.json` no modo desenvolvimento
- processar eventos enviados pelo motor de macros
- salvar, carregar, excluir e limpar macros
- atualizar a tabela e a timeline visual
- controlar tema claro/escuro
- mostrar contagem regressiva antes da gravacao
- exibir alerta verde piscando durante reproducao
- mostrar atalhos em cards e abrir a tela de edicao de atalhos
- consumir repositorios e casos de uso das novas camadas

Quando mexer aqui:

- alterar layout da tela
- adicionar botoes
- mudar textos visuais
- mudar comportamento de clique na interface
- alterar edicao da tabela

Observacao:

- este modulo ainda e grande por compatibilidade; novas regras de negocio devem nascer em `application/` e novas implementacoes externas devem nascer em `infrastructure/`

### `macroflow/engine.py`

Modulo do motor de gravacao e reproducao.

Responsabilidades:

- capturar teclado e mouse usando `pynput`
- iniciar e parar gravacao
- aguardar contagem regressiva antes de gravar
- guardar eventos com tempo relativo
- registrar teclas seguradas como eventos com duracao (`key_hold`)
- enviar eventos em tempo real para a interface
- reproduzir a macro capturada
- reproduzir a macro em loop ate interrupcao
- parar a reproducao em andamento
- tratar atalhos globais configuraveis como `F8`, `F9`, `F10` e `Esc`

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

### `macroflow/smart_engine.py`

Modulo da macro inteligente por visao de tela.

Responsabilidades:

- verificar dependencias de captura/OCR
- capturar a tela em tempo real
- detectar a borda verde do item selecionado
- procurar o texto alvo via OCR
- calcular a direcao do alvo
- enviar setas ate o item alvo ser selecionado

Quando mexer aqui:

- melhorar deteccao da borda verde
- calibrar OCR para jogos/telas especificas
- mudar estrategia de navegacao
- adicionar suporte a templates/imagens de referencia

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
- definir a pasta onde as macros sao salvas em desenvolvimento e no portable
- definir o arquivo `config/shortcuts.json` em desenvolvimento
- definir os atalhos padrao
- garantir que as pastas de dados existam

Quando mexer aqui:

- mudar o local onde as macros sao salvas
- adicionar novas constantes globais

### `config/app.json`

Arquivo de preferencias gerais do aplicativo.

Responsabilidades:

- guardar o idioma selecionado
- guardar o tema selecionado
- guardar se o app deve iniciar com o Windows

### `config/farm_subaru_impreza_22b.json`

Arquivo de preferencias da tela Farm Subaru.

Responsabilidades:

- guardar intervalo de execucao
- guardar quantidade de roletas
- guardar posicoes gerais usadas pelo farm
- guardar flags como desligar o PC ao finalizar

### `language/pt-br.json` e `language/en.json`

Arquivos de idioma da interface.

Responsabilidades:

- centralizar os textos visuais do MacroFlow
- permitir trocar o idioma sem espalhar textos fixos pelo codigo
- servir de base para adicionar novos idiomas no futuro

### `requirements.txt`

Lista as dependencias Python do projeto:

- `pynput`: captura e reproduz teclado/mouse
- `customtkinter`: cria a interface grafica moderna
- `Pillow`: captura screenshot da tela
- `opencv-python`: detecta borda verde e regioes visuais
- `pytesseract`: le texto dos cards via OCR

### `config/shortcuts.json`

Arquivo criado automaticamente quando o usuario edita atalhos.

Atalhos padrao:

- `record`: `F8`
- `play`: `F9`
- `stop_playback`: `F10`
- `close`: `F2`

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
6. A lista de macros salvas e carregada da pasta `macros/` no modo desenvolvimento.

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
3. A macro e salva em `macros/<nome>.json` no modo desenvolvimento.
4. A lista lateral de macros e atualizada.

### Ao reproduzir uma macro

1. O usuario seleciona uma macro e clica em `Reproduzir` ou pressiona `F9`.
2. `MacroApp` envia os eventos atuais para `MacroEngine`.
3. Os eventos sao executados imediatamente respeitando os intervalos de tempo capturados.
4. Se o usuario pressionar `F10`, o motor interrompe a reproducao.

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

Exemplo de tecla segurada:

```json
{
  "type": "key_hold",
  "key": {
    "kind": "char",
    "value": "w"
  },
  "t": 5.6465,
  "duration": 25.1491
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
