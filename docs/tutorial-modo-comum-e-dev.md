# Tutorial: modo comum e modo desenvolvedor

Este tutorial mostra os fluxos principais do Ayvu para dois públicos:

- usuários comuns, que preferem menus guiados e confirmações antes de ações importantes;
- usuários técnicos, que preferem comandos diretos, scripts e argumentos explícitos.

O Ayvu traduz arquivos EPUB locais usando um servidor HTTP compatível com LibreTranslate. Ele não altera o EPUB original; a tradução sempre é gravada em um novo arquivo `.epub`.

## Antes de começar

Instale as dependências do projeto:

```bash
uv sync --extra dev
```

Suba um LibreTranslate local:

```bash
docker run -it -p 5000:5000 libretranslate/libretranslate
```

Teste a conexão:

```bash
uv run ayvu test-translator --url http://localhost:5000
```

Se quiser conferir os idiomas retornados pelo servidor:

```bash
uv run ayvu languages --url http://localhost:5000
```

## Tutorial básico: modo comum

Use o modo comum quando quiser que o Ayvu guie a execução no terminal.

Abra o menu inicial:

```bash
uv run ayvu
```

O menu permite iniciar uma tradução, gerar preview, ver ajuda, abrir biblioteca e acessar configurações. Biblioteca e configurações ainda aparecem como opções indisponíveis na versão atual; elas estão reservadas para os próximos passos do modo comum.

### Gerar um preview

O preview é o primeiro teste recomendado para um livro novo. Ele traduz uma amostra inicial do EPUB e preserva a estrutura do restante do arquivo.

Pelo menu, escolha a opção de preview e informe o caminho do EPUB quando solicitado.

Também é possível chamar o preview diretamente:

```bash
uv run ayvu --preview livro.epub
```

Por padrão, o arquivo é salvo em:

```text
~/Documentos/Livros/Preview/livro-preview.epub
```

Abra o preview no seu leitor de EPUB e confira capa, sumário, primeiro capítulo, links e trechos com formatação.

### Traduzir o livro completo

Pelo menu inicial, escolha traduzir livro e informe o caminho do EPUB. O Ayvu mostra o idioma de destino padrão, permite escolher outro código de idioma e confirma onde o arquivo traduzido será salvo.

Antes de iniciar uma tradução real, o Ayvu verifica EPUB, idioma, glossário, cache e tradutor. Se algo estiver errado, ele falha cedo com uma mensagem curta e um próximo passo.

Sem caminho de saída explícito, o padrão é:

```text
~/Documentos/Livros/Traduzidos/livro-pt.epub
```

Ao final, o Ayvu mostra um relatório no terminal com capítulos processados, textos traduzidos, textos reaproveitados do cache, erros e caminho de saída. No modo comum, ele também pode salvar esse relatório em Markdown em:

```text
~/Documentos/Livros/Relatorios
```

### Retomar uma tradução interrompida

Durante traduções reais, o Ayvu registra um estado local em:

```text
~/Documentos/Livros/Processando
```

Ao executar `uv run ayvu`, o modo comum procura estados em andamento e oferece retomar uma tradução detectada. O cache SQLite continua sendo a parte que evita retraduzir textos já concluídos.

## Tutorial intermediário: preview, glossário e organização

Use este fluxo quando estiver traduzindo livros técnicos ou quiser controlar melhor o resultado.

### Usar glossário

Crie um glossário a partir do exemplo versionado:

```bash
cp glossary.example.json glossary.json
```

Edite `glossary.json` com os termos que deseja padronizar. Exemplo:

```json
{
  "Game Loop": "loop de jogo",
  "Design Pattern": "padrão de projeto",
  "Observer": "Observer"
}
```

Depois, passe o glossário na tradução:

```bash
uv run ayvu translate livro.epub \
  --source en \
  --target pt \
  --url http://localhost:5000 \
  --cache .cache/traducoes.sqlite \
  --glossary glossary.json
```

O glossário é aplicado depois da tradução e também sobre textos vindos do cache.

### Usar cache de forma consistente

Para retomar com segurança, repita o mesmo cache entre execuções:

```bash
uv run ayvu translate livro.epub \
  --source en \
  --target pt \
  --url http://localhost:5000 \
  --cache .cache/traducoes.sqlite
```

Se o processo for interrompido, rode o comando novamente com o mesmo cache. O Ayvu reaproveita os trechos já traduzidos.

### Organizar biblioteca manualmente

A biblioteca guiada ainda não está completa. Enquanto isso, use a estrutura padrão como convenção local:

```text
~/Documentos/Livros/
├── Original/
├── Preview/
├── Traduzidos/
├── Relatorios/
└── Processando/
```

Mantenha EPUBs originais em `Original`, previews em `Preview`, traduções finais em `Traduzidos` e relatórios em `Relatorios`. O Ayvu já usa algumas dessas pastas nos fluxos atuais.

## Tutorial dev: comandos diretos

Use o modo desenvolvedor quando quiser execução previsível por terminal, automação ou scripts.

### Inspecionar um EPUB

```bash
uv run ayvu inspect livro.epub
```

### Testar o tradutor

```bash
uv run ayvu test-translator --url http://localhost:5000
```

### Listar idiomas

```bash
uv run ayvu languages --url http://localhost:5000
```

### Gerar preview

```bash
uv run ayvu --preview livro.epub
```

### Traduzir com saída explícita

```bash
uv run ayvu translate livro.epub \
  --output livro-pt.epub \
  --source en \
  --target pt \
  --translator libretranslate \
  --url http://localhost:5000 \
  --cache .cache/traducoes.sqlite
```

### Sobrescrever saída existente

```bash
uv run ayvu translate livro.epub \
  --output livro-pt.epub \
  --source en \
  --target pt \
  --url http://localhost:5000 \
  --cache .cache/traducoes.sqlite \
  --overwrite
```

### Simular sem gravar EPUB

```bash
uv run ayvu translate livro.epub \
  --output teste.epub \
  --source en \
  --target pt \
  --dry-run
```

### Extrair texto visível para Markdown

```bash
uv run ayvu extract livro.epub --output livro-extraido/
```

### Forçar modo comum ou desenvolvedor

A opção global `--mode` permite escolher o perfil de uso:

```bash
uv run ayvu --mode common translate livro.epub
```

```bash
uv run ayvu --mode developer translate livro.epub \
  --source en \
  --target pt \
  --url http://localhost:5000 \
  --cache .cache/traducoes.sqlite
```

## Checklist recomendado

Antes da tradução completa:

1. Rode `test-translator`.
2. Rode `languages` se tiver dúvida sobre códigos de idioma.
3. Gere um preview.
4. Confira o preview no leitor de EPUB.
5. Prepare um glossário se o livro for técnico.

Depois da tradução:

1. Leia o relatório no terminal.
2. Salve o relatório Markdown quando quiser histórico local.
3. Abra o EPUB traduzido no leitor.
4. Confira capa, sumário, capítulos do começo e do meio, links internos, imagens e trechos com tags como itálico ou negrito.

## Limites atuais

- Biblioteca e configurações ainda não estão completas.
- A tradução ainda acontece por nós de texto, então frases quebradas por tags podem perder contexto.
- A qualidade depende do servidor de tradução local.
- Livros técnicos costumam exigir glossário.
- EPUBs malformados podem depender do comportamento do parser HTML/XML.
