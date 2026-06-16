# Criar bot no Telegram para o MacroFlow

Este manual explica como criar seu proprio bot do Telegram para receber notificacoes do Farm no MacroFlow.

## 1. Criar o bot

1. Abra o Telegram.
2. Pesquise por `@BotFather`.
3. Abra o BotFather oficial.
4. Envie o comando:

```text
/newbot
```

5. O BotFather vai pedir um nome para o bot. Exemplo:

```text
Meu MacroFlow Bot
```

6. Depois ele vai pedir um username. O username precisa terminar com `bot`. Exemplo:

```text
meu_macroflow_123_bot
```

7. O BotFather vai responder com um token parecido com:

```text
123456789:ABCDEF_seu_token_aqui
```

8. Copie esse token. Ele sera usado no campo `Bot Token` do MacroFlow.

## 2. Iniciar conversa com o bot

1. Abra o bot que voce acabou de criar.
2. Envie:

```text
/start
```

Isso autoriza o bot a enviar mensagens para voce.

## 3. Descobrir o Chat ID

1. Abra o navegador.
2. Acesse o endereco abaixo, trocando `SEU_TOKEN` pelo token do seu bot:

```text
https://api.telegram.org/botSEU_TOKEN/getUpdates
```

Exemplo:

```text
https://api.telegram.org/bot123456789:ABCDEF_seu_token_aqui/getUpdates
```

3. Na pagina que abrir, procure por um trecho parecido com:

```json
"chat":{"id":123456789
```

4. Copie somente o numero do `id`.

Esse numero e o seu `Chat ID`.

## 4. Configurar no MacroFlow

1. Abra o MacroFlow.
2. Entre em `Configuracoes`.
3. Procure a secao `Telegram`.
4. Ative `Notificacoes Telegram`.
5. Cole o token no campo `Bot Token`.
6. Cole o numero no campo `Chat ID`.
7. Clique em `Salvar`.
8. Clique em `Enviar mensagem de teste`.

Se tudo estiver correto, voce recebera uma mensagem no Telegram.

## 5. Mensagens enviadas pelo Farm

O MacroFlow envia poucas mensagens para evitar spam:

- quando o Farm inicia;
- quando cada macro diferente inicia;
- quando o Farm finaliza com sucesso;
- quando o Farm e interrompido;
- quando ocorre erro.

Ele nao envia uma mensagem para cada repeticao.

Exemplo:

```text
MacroFlow
Farm Subaru iniciado
Data/Hora: 16/06/2026 22:14:03
```

```text
MacroFlow
Iniciando macro
Macro: [2] Macro Farm 99
Data/Hora: 16/06/2026 22:15:10
```

```text
MacroFlow
Farm finalizado com sucesso
Tempo total: 01:35:42
Data/Hora: 16/06/2026 23:49:45
```

## 6. Cuidados importantes

Nunca compartilhe seu `Bot Token`.

Se alguem tiver esse token, essa pessoa podera enviar mensagens usando o seu bot.

Se voce achar que o token vazou:

1. Abra o `@BotFather`.
2. Envie:

```text
/token
```

3. Escolha seu bot.
4. Gere um novo token.
5. Atualize o token no MacroFlow.

## 7. Problemas comuns

### A mensagem de teste nao chegou

Verifique:

- se voce enviou `/start` para o bot;
- se o `Bot Token` foi copiado completo;
- se o `Chat ID` esta correto;
- se o computador esta com internet.

### O getUpdates aparece vazio

Isso normalmente acontece quando voce ainda nao enviou `/start` para o bot.

Abra o bot, envie `/start` e acesse novamente:

```text
https://api.telegram.org/botSEU_TOKEN/getUpdates
```

### O Telegram retorna erro de token

Gere um novo token no `@BotFather` usando:

```text
/token
```
