# MacroFlow

Aplicativo para gravar, editar, organizar e executar macros de teclado e mouse no Windows.
A interface usa CustomTkinter, tem tema claro/escuro, idiomas em arquivos JSON e fluxos separados para cadastro, execucao, playlist, macro inteligente e Farm Subaru Impreza 22B.

## Instalar

```powershell
python -m pip install -r requirements.txt
```

## Rodar

```powershell
python macro_recorder.py
```

## Telas principais

- `Criar / Editar Macro`: grava, edita, importa, exporta e salva macros convencionais.
- `Macro inteligente`: cria macros de navegacao por matriz, sempre partindo de L1C1.
- `Executar Macro`: executa um macro salvo, com contador, farol de inicio e opcao de loop.
- `Playlist de macro`: monta uma lista de macros, define repeticoes e executa em sequencia.
- `Farm Subaru Impreza 22B`: executa apenas macros com `ordem` maior que zero, seguindo a ordem configurada.
- `Configuracoes`: altera idioma, tema, atalhos e modo Farm.

## Atalhos padrao

- `F6`: executa playlist/Farm.
- `F7`: para playlist/Farm.
- `F8`: grava ou para a gravacao.
- `F9`: reproduz macro.
- `F10`: para reproducao.
- `F2`: fecha o aplicativo quando a janela esta em foco.

Os atalhos personalizados ficam salvos em `shortcuts.json`.

## Cadastro de macro

Na tela de cadastro voce pode:

- gravar eventos de teclado e mouse;
- acompanhar teclas e botoes pressionados em tempo real;
- editar eventos direto na tabela;
- limpar todos os eventos;
- importar e exportar JSON;
- definir `ordem`, `cor`, `posicao da marca` e `posicao do carro`;
- salvar teclas seguradas como um unico evento com duracao.

A gravacao comeca depois da contagem `3, 2, 1`.
As macros ficam salvas na pasta `macros`.

## Cores dos macros

Cada macro possui o campo `cor`, por exemplo:

```json
{
  "cor": "#07111f"
}
```

A cor padrao e `#07111f`, a mesma cor base dos cards do aplicativo.
Essa cor aparece como acento/borda nas listas, playlist e tela Farm.

## Farm Subaru Impreza 22B

A tela Farm lista somente macros com:

```json
{
  "ordem": 1
}
```

Regras principais:

- os macros sao exibidos e executados pela ordem numerica;
- cada macro tem repeticoes proprias;
- a opcao `Ignorar item` remove o macro da execucao sem apagar o cadastro;
- o intervalo de execucao padrao e `1000 ms`;
- o intervalo e aplicado ao final de cada repeticao, inclusive quando so existe uma repeticao;
- o card do macro em execucao fica com fundo `#06402B`;
- ao parar ou finalizar, os cards voltam para a cor normal;
- as configuracoes da tela ficam em `config/farm_subaru_impreza_22b.json`.

## Macros compostos

Um macro e tratado como composto na tela Farm quando possui `posicao da marca`, `posicao do carro` ou ambos.
Nesses casos, a tela mostra a tag `Composto`.

Marcadores durante a execucao:

- `Insert`: nao e executado como tecla; e substituido pela rotina de `Posicao da marca`.
- `Delete`: nao e executado como tecla; e substituido pela rotina de `Posicao do carro`.

Depois da rotina, o macro continua normalmente.
Exemplo:

```text
W, J, C, Insert, W, A
```

Durante a execucao vira:

```text
W, J, C, rotina da Posicao da marca, W, A
```

Se nao houver `Insert` ou `Delete`, o comportamento antigo continua: a rotina de posicao e executada no final do macro.

## Posicao da marca

`Posicao da marca` nao usa calculo de matriz.
Ela executa exatamente as quantidades informadas, nesta ordem:

```text
Cima, Baixo, Esquerda, Direita
```

O intervalo entre as setas e `300 ms`.

## Posicao do carro

`Posicao do carro` usa matriz de 3 linhas por N colunas.
A navegacao sempre parte de L1C1 e usa as setas para chegar ate a linha/coluna informada.

Ordem de incremento da matriz:

```text
L1C1, L2C1, L3C1, L1C2, L2C2, L3C2, L1C3 ...
```

## Macro inteligente

Use `Macro inteligente` para gerar uma navegacao por matriz.
O nome e gerado automaticamente no formato:

```text
L2C3(Matriz)
```

Esse macro tambem pode aparecer na playlist como referencia.
Quando executado em repeticoes, ele aplica auto incremento seguindo a ordem da matriz.

## Arquivos importantes

- `macro_recorder.py`: arquivo principal para executar o app.
- `macroflow/app.py`: interface grafica e fluxo das telas.
- `macroflow/engine.py`: gravacao, captura e reproducao de teclado/mouse.
- `macroflow/timeline.py`: desenho da linha do tempo visual.
- `macroflow/input_utils.py`: conversao e nomes de teclas/eventos.
- `macroflow/smart_engine.py`: leitura da tela e navegacao por alvo visual.
- `macroflow/constants.py`: caminhos usados pelo projeto.
- `language/pt-br.json`: textos em portugues.
- `language/en.json`: textos em ingles.
- `config/app.json`: configuracoes gerais do app.
- `config/farm_subaru_impreza_22b.json`: configuracoes da tela Farm.

## Build portable

Para gerar um executavel portable:

```powershell
python -m PyInstaller MacroFlow.spec --clean --noconfirm
```

O executavel fica em `dist/MacroFlow/MacroFlow.exe`.
