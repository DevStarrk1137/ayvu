# ayvu

`ayvu` é uma CLI em Python para traduzir arquivos EPUB locais usando um tradutor HTTP local compatível com LibreTranslate. A ferramenta preserva a estrutura interna do livro e modifica apenas textos visíveis ao leitor.

O EPUB original nunca é alterado. A saída é gravada em um novo arquivo `.epub`.

## Recursos

- Tradução de documentos XHTML/HTML internos do EPUB.
- Preservação de tags, CSS, imagens, links, sumário e nomes de arquivos internos.
- Cache SQLite para retomar traduções interrompidas e evitar chamadas repetidas.
- Glossário JSON opcional para padronizar termos técnicos.
- Nome de saída automático baseado no idioma de destino.
- Modo `dry-run` para simular o processamento sem gerar arquivo.
- Extração de texto visível para Markdown.
- Validação básica do EPUB gerado.

## Aviso de Uso

Este projeto é destinado a uso pessoal, estudo e acessibilidade com arquivos EPUB fornecidos por você. Ele não remove DRM, não baixa livros e não deve ser usado para distribuir conteúdo protegido por copyright.

Por padrão, arquivos `.epub`, cache local e glossários privados ficam fora do Git.

## Requisitos

- Python 3.11+
- `uv` ou `pip`
- Um servidor local compatível com LibreTranslate

## Instalação Com uv

Dentro do diretório do projeto:

```bash
cd ayvu
uv sync --extra dev
```

Execute os comandos sem ativar manualmente o ambiente virtual:

```bash
uv run ayvu --help
```

## Instalação Com pip

```bash
cd ayvu
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Com o ambiente ativado:

```bash
ayvu --help
```

## Servidor de Tradução

Suba o LibreTranslate localmente com Docker:

```bash
docker run -it -p 5000:5000 libretranslate/libretranslate
```

Endpoint usado pela CLI:

```text
http://localhost:5000/translate
```

Teste a conexão:

```bash
uv run ayvu test-translator --url http://localhost:5000
```

## Uso

Inspecionar um EPUB:

```bash
uv run ayvu inspect livro.epub
```

Traduzir um EPUB:

```bash
uv run ayvu translate livro.epub \
  --source en \
  --target pt \
  --translator libretranslate \
  --url http://localhost:5000 \
  --cache .cache/traducoes.sqlite
```

Antes de iniciar a tradução, o Ayvu verifica internamente o par de idiomas, o glossário, o cache, o EPUB de entrada e, em traduções reais, o tradutor configurado. Se algo impedir a execução, o comando falha cedo com uma mensagem curta e um próximo passo.

Sem `--output`, a saída é criada ao lado do arquivo original usando o idioma de destino:

```text
livro-pt.epub
```

Para escolher manualmente o caminho da saída:

```bash
uv run ayvu translate livro.epub \
  --output livro-ptbr.epub
```

Usar glossário:

```bash
cp glossary.example.json glossary.json

uv run ayvu translate livro.epub \
  --output livro-ptbr.epub \
  --glossary glossary.json
```

Se a saída já existir, o Ayvu mostra o caminho calculado e pergunta se deve sobrescrever.
Para pular a pergunta e sobrescrever direto:

```bash
uv run ayvu translate livro.epub \
  --output livro-ptbr.epub \
  --overwrite
```

Simular uma tradução sem gravar EPUB:

```bash
uv run ayvu translate livro.epub \
  --output teste.epub \
  --dry-run
```

Ao final da tradução, o Ayvu mostra um relatório no terminal com o EPUB original,
idiomas, saída calculada, capítulos processados, textos traduzidos, cache e erros.
Também pergunta se deve salvar esse relatório em Markdown em
`~/Documentos/Livros/Relatorios`.

Extrair texto visível para Markdown:

```bash
uv run ayvu extract livro.epub \
  --output livro-extraido/
```

## Glossário

O glossário é um arquivo JSON simples com pares de termos:

```json
{
  "Game Loop": "loop de jogo",
  "Design Pattern": "padrão de projeto",
  "Observer": "Observer",
  "Command": "Command",
  "State": "State"
}
```

Use `glossary.example.json` como base. O arquivo `glossary.json` local é ignorado pelo Git para evitar versionar preferências pessoais ou conteúdo privado.

## Cache e Retomada

As traduções são armazenadas em SQLite. Se o processo for interrompido, rode o mesmo comando novamente usando o mesmo arquivo de cache:

```bash
uv run ayvu translate livro.epub \
  --output livro-ptbr.epub \
  --cache .cache/traducoes.sqlite
```

Trechos já traduzidos serão reaproveitados automaticamente.

Durante traduções reais, o Ayvu também grava um estado local da execução em
`~/Documentos/Livros/Processando`. Esse arquivo registra os caminhos e opções
necessários para uma retomada futura. Ele não substitui o cache e não é apagado
automaticamente.

## Testes

```bash
uv run pytest
```

## Fluxo do Projeto

O fluxo de trabalho do projeto usa issue por tarefa, branch curta por tarefa,
pull request para merge na `main`, milestone por versao e tag com GitHub Release
ao publicar. O passo a passo esta em
[`docs/release-workflow.md`](docs/release-workflow.md).

## Estrutura

```text
ayvu/
├── docs/
├── src/
│   └── ayvu/
├── tests/
├── glossary.example.json
├── pyproject.toml
├── README.md
└── uv.lock
```

## Limitações

- A tradução por nós de texto pode perder contexto em frases divididas por tags.
- EPUBs com XHTML malformado podem depender do comportamento do parser.
- Livros técnicos costumam exigir glossário para manter termos consistentes.
- A qualidade final depende do servidor de tradução usado.
