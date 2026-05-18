# ayvu

`ayvu` é uma CLI em Python para traduzir arquivos EPUB locais usando um tradutor HTTP local compatível com LibreTranslate. A ferramenta preserva a estrutura interna do livro e modifica apenas textos visíveis ao leitor.

O EPUB original nunca é alterado. A saída é gravada em um novo arquivo `.epub`.

## Recursos

- Tradução de documentos XHTML/HTML internos do EPUB.
- Preservação de tags, CSS, imagens, links, sumário e nomes de arquivos internos.
- Cache SQLite para retomar traduções interrompidas e evitar chamadas repetidas.
- Glossário JSON opcional para padronizar termos técnicos.
- Nome de saída automático baseado no idioma de destino.
- Preview traduzido de uma amostra inicial do EPUB.
- Modo comum guiado e modo desenvolvedor direto.
- Checagens internas antes de iniciar traduções reais.
- Modo `dry-run` para simular o processamento sem gerar arquivo.
- Extração de texto visível para Markdown.
- Relatório final no terminal e opção de salvar relatório Markdown no modo comum.
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

## Modos de Uso

O Ayvu possui dois modos de execução que equilibram facilidade de uso com eficiência técnica:

- **Modo Comum (common)**: Focado em uma experiência guiada. Oferece sugestões de retomada de traduções interrompidas, convites para gerar previews e solicita confirmações antes de ações importantes (como sobrescrever arquivos). É o modo padrão ao executar apenas `ayvu`.
- **Modo Desenvolvedor (developer)**: Focado em execução direta e automação. Pula perguntas interativas e assume as configurações padrão ou passadas via argumentos. É o modo padrão ao utilizar subcomandos como `translate` ou `inspect`.

Para um passo a passo dos dois fluxos, leia o
[`tutorial de modo comum e modo desenvolvedor`](docs/tutorial-modo-comum-e-dev.md).

Você pode forçar um modo específico usando a opção global `--mode`:

```bash
uv run ayvu --mode common translate livro.epub
```

Liste os idiomas disponíveis no LibreTranslate local:

```bash
uv run ayvu languages --url http://localhost:5000
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

Gerar um preview traduzido:

```bash
uv run ayvu --preview livro.epub
```

O preview traduz os primeiros documentos internos do EPUB, preserva o restante da estrutura e
salva por padrão em:

```text
~/Documentos/Livros/Preview/livro-preview.epub
```

No primeiro uso do modo comum, o Ayvu pergunta o idioma padrão de leitura/tradução e o
salva na configuração. Nas próximas execuções esse idioma é usado como destino padrão
em traduções e previews, sem perguntar de novo.

Ao executar apenas `uv run ayvu`, o Ayvu abre um primeiro menu guiado com opções para traduzir
livro, gerar preview, abrir biblioteca, acessar configurações, mostrar ajuda ou sair. Biblioteca
ainda aparece como opção indisponível. A opção `Settings` permite ver e alterar o idioma
padrão, salvando a mudança na configuração (o restante das configurações ainda não está
pronto). Nos fluxos guiados de tradução e preview, o Ayvu mostra o idioma de destino padrão
salvo e permite escolher outro código a partir dos idiomas informados pelo LibreTranslate.
No modo desenvolvedor, o idioma de destino continua sendo definido por `--target`.

Antes de iniciar a tradução, o Ayvu verifica internamente o par de idiomas, o glossário, o cache, o EPUB de entrada e, em traduções reais, o tradutor configurado. Se algo impedir a execução, o comando falha cedo com uma mensagem curta e um próximo passo.

Sem `--output`, o Ayvu salva por padrão em:

```text
~/Documentos/Livros/Traduzidos/livro-pt.epub
```

No **Modo Comum**, o Ayvu mostra a pasta padrão de saída, o nome calculado para o EPUB
traduzido e pergunta se você deseja manter esse local antes de iniciar a tradução. Se preferir
outro caminho, responda não à pergunta e informe o caminho desejado. No **Modo Desenvolvedor**,
use `--output` para escolher manualmente o caminho da saída:

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

No **Modo Comum**, se a saída já existir, o Ayvu mostra o caminho calculado e pergunta se deve sobrescrever. Para pular a pergunta e sobrescrever direto (comportamento padrão do Modo Desenvolvedor):

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

Ao final da tradução, o Ayvu mostra um relatório no terminal com o EPUB original, idiomas, saída calculada, capítulos processados, textos traduzidos, cache e erros. No **Modo Comum**, também pergunta se deve salvar esse relatório em Markdown em `~/Documentos/Livros/Relatorios`.

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

Ao executar `uv run ayvu`, o modo comum procura estados de tradução em andamento
nessa pasta e oferece retomar uma execução detectada.

## Configuração

O Ayvu já define um formato inicial para preferências locais. O modo comum já
usa o campo `default_target_language`: ele é perguntado no primeiro uso e pode
ser alterado depois pela opção `Settings`. Os demais campos ainda não têm
interface dedicada. O arquivo fica em:

```text
$XDG_CONFIG_HOME/ayvu/config.json
```

Quando `XDG_CONFIG_HOME` não estiver definido, o fallback é:

```text
~/.config/ayvu/config.json
```

Formato inicial:

```json
{
  "version": 1,
  "default_target_language": "pt",
  "books_dir": "~/Documentos/Livros",
  "folders": {
    "original": "Original",
    "translated": "Traduzidos",
    "preview": "Preview",
    "reports": "Relatorios",
    "processing": "Processando"
  },
  "reader_app": null
}
```

A precedência planejada é:

```text
argumentos da CLI > arquivo de configuração > padrões internos
```

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
│   ├── release-workflow.md
│   ├── relatorio-tecnico.md
│   └── tutorial-modo-comum-e-dev.md
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
