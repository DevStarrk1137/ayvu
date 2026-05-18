# Relatório técnico: Ayvu

Este documento registra o estado técnico atual do Ayvu, as decisões principais de arquitetura, os fluxos implementados e os próximos riscos conhecidos.

Última atualização: 2026-05-15.

## 1. Objetivo do projeto

O Ayvu é uma CLI Python para traduzir arquivos EPUB locais usando um tradutor HTTP local compatível com LibreTranslate.

A ferramenta foi pensada para uso pessoal, estudo e acessibilidade. Ela não remove DRM, não baixa livros e não distribui conteúdo protegido. O EPUB original nunca é modificado; a saída é sempre um novo arquivo `.epub`.

Fluxo principal:

```text
arquivo.epub
-> abrir EPUB sem alterar o original
-> localizar documentos XHTML/HTML internos
-> traduzir apenas textos visíveis ao leitor
-> preservar HTML, CSS, imagens, links, sumário e nomes internos
-> usar cache SQLite para reaproveitar traduções
-> copiar o EPUB original substituindo somente documentos traduzidos
-> validar o EPUB gerado
```

## 2. Estado atual

O Ayvu já possui:

- tradução de EPUB com preservação da estrutura interna;
- inspeção de EPUB;
- extração de texto visível para Markdown;
- preview traduzido de uma amostra inicial do livro;
- cache SQLite;
- glossário JSON simples;
- chunking de textos longos;
- progresso visual com `rich`;
- preflight antes de traduções reais;
- relatório final no terminal;
- opção de salvar relatório Markdown no modo comum;
- modo comum guiado e modo desenvolvedor direto;
- retomada local de traduções interrompidas;
- comando para listar idiomas do LibreTranslate;
- formato inicial de configuração local;
- validação básica do EPUB gerado;
- testes automatizados e CI no GitHub Actions.

Ainda não possui:

- interface completa para editar configurações persistentes do Ayvu;
- biblioteca completa de livros;
- gerenciamento automático do LibreTranslate;
- tradução por bloco preservando tags internas;
- validação EPUB avançada com EPUBCheck;
- backends alternativos além de LibreTranslate;
- interface gráfica ou web.

## 3. Estrutura do projeto

Estrutura versionável principal:

```text
ayvu/
├── .github/
│   └── workflows/
│       └── tests.yml
├── docs/
│   ├── relatorio-tecnico.md
│   └── release-workflow.md
├── src/
│   └── ayvu/
│       ├── __init__.py
│       ├── cache.py
│       ├── chunking.py
│       ├── cli.py
│       ├── cli_progress.py
│       ├── config.py
│       ├── domain.py
│       ├── epub_io.py
│       ├── glossary.py
│       ├── html_translate.py
│       ├── preflight.py
│       ├── resume.py
│       ├── translator.py
│       └── validation.py
├── tests/
│   ├── conftest.py
│   ├── test_cache.py
│   ├── test_chunking.py
│   ├── test_cli.py
│   ├── test_cli_progress.py
│   ├── test_config.py
│   ├── test_epub_io.py
│   ├── test_glossary.py
│   ├── test_html_translate.py
│   ├── test_preflight.py
│   ├── test_resume.py
│   ├── test_translator.py
│   └── test_validation.py
├── CHANGELOG.md
├── CONTRIBUTING.md
├── LICENSE
├── README.md
├── glossary.example.json
├── pyproject.toml
└── uv.lock
```

Arquivos locais e privados ficam fora do Git, incluindo EPUBs, PDFs, caches SQLite locais e glossários pessoais.

## 4. Stack

Dependências principais:

- Python 3.11+;
- `typer` para CLI;
- `rich` para saída de terminal;
- `ebooklib` para inspeção de EPUB;
- `beautifulsoup4` e `lxml` para HTML/XML;
- `requests` para HTTP;
- `sqlite3` da biblioteca padrão para cache;
- `pytest` para testes.

O gerenciador preferido do projeto é `uv`.

## 5. Instalação e validação local

Instalar dependências de desenvolvimento:

```bash
uv sync --extra dev
```

Ver ajuda da CLI:

```bash
uv run ayvu --help
```

Rodar testes:

```bash
uv run pytest
```

Para mudanças apenas de documentação, a validação mínima é:

```bash
git diff --check
```

## 6. Comandos implementados

Inspecionar um EPUB:

```bash
uv run ayvu inspect livro.epub
```

Testar o LibreTranslate local:

```bash
uv run ayvu test-translator --url http://localhost:5000
```

Listar idiomas disponíveis no LibreTranslate:

```bash
uv run ayvu languages --url http://localhost:5000
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

Gerar preview traduzido:

```bash
uv run ayvu --preview livro.epub
```

Extrair texto visível para Markdown:

```bash
uv run ayvu extract livro.epub --output livro-extraido/
```

Executar o menu guiado:

```bash
uv run ayvu
```

O modo guiado permite iniciar tradução, gerar preview, ver ajuda e acessar placeholders de biblioteca e configurações. Também pode detectar estados locais de tradução interrompida.

## 7. Modos de uso

O Ayvu separa dois perfis:

- `common`: modo comum, guiado, com confirmações e perguntas antes de ações importantes.
- `developer`: modo direto, adequado para automação e uso explícito por subcomandos.

Ao executar apenas `uv run ayvu`, o modo comum abre o menu guiado. Ao usar subcomandos como `translate`, `inspect` e `extract`, o comportamento padrão é mais direto.

A opção global `--mode` permite forçar o modo:

```bash
uv run ayvu --mode common translate livro.epub
```

## 8. Responsabilidades dos módulos

`src/ayvu/cli.py` concentra comandos Typer, argumentos, prompts, confirmações, progresso, relatórios e orquestração. Não deve receber regra pesada de EPUB, HTML ou HTTP.

`src/ayvu/domain.py` guarda tipos de domínio compartilhados, como `LanguagePair`, `OutputPlan`, `TranslationOptions` e `UserMode`.

`src/ayvu/epub_io.py` cuida de leitura, inspeção, extração, tradução estrutural e escrita do EPUB final.

`src/ayvu/html_translate.py` traduz HTML/XHTML em nível de nó de texto visível, preservando tags e ignorando conteúdo que não deve ser traduzido.

`src/ayvu/translator.py` define o contrato `Translator` e o backend `LibreTranslateTranslator`.

`src/ayvu/cache.py` persiste traduções em SQLite usando idioma de origem, idioma de destino e hash do texto original.

`src/ayvu/glossary.py` lê e aplica glossário JSON simples.

`src/ayvu/chunking.py` divide textos longos preservando ordem e evitando cortar palavras quando possível.

`src/ayvu/preflight.py` valida idioma, glossário, cache, EPUB e tradutor antes da tradução real.

`src/ayvu/resume.py` registra e lê estados locais de retomada em `~/Documentos/Livros/Processando`.

`src/ayvu/cli_progress.py` adapta callbacks de tradução para `rich.Progress` e mantém contadores de textos.

`src/ayvu/config.py` define o formato inicial de configuração JSON, o caminho padrão do arquivo, leitura/gravação e resolução das pastas locais do Ayvu.

`src/ayvu/validation.py` faz validação básica do EPUB gerado.

## 9. Configuração local

O formato inicial da configuração local fica em:

```text
$XDG_CONFIG_HOME/ayvu/config.json
```

Quando `XDG_CONFIG_HOME` não estiver definido, o fallback é:

```text
~/.config/ayvu/config.json
```

Formato versionado atual:

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

A precedência planejada para os próximos fluxos é:

```text
argumentos da CLI > arquivo de configuração > padrões internos
```

## 10. Pipeline de EPUB

A decisão mais importante do pipeline é não reconstruir o EPUB inteiro com `ebooklib.write_epub()`.

O fluxo atual é conservador:

```text
abrir EPUB original como ZIP
-> localizar documentos XHTML/HTML com ebooklib e caminhos internos reais
-> traduzir somente os documentos elegíveis
-> copiar todas as entradas originais para o novo EPUB
-> substituir apenas os documentos traduzidos
-> manter mimetype sem compressão
```

Essa abordagem preserva:

- `mimetype`;
- `content.opf`;
- `toc.ncx` e arquivos de navegação;
- CSS;
- imagens;
- links internos;
- nomes de arquivos internos;
- entradas não modificadas do ZIP.

## 11. Tradução de HTML

A regra principal é:

```text
Não achatar HTML.
Não usar get_text() no fluxo de tradução.
Traduzir somente nós de texto visíveis.
```

Tags ignoradas:

```text
script, style, code, pre, kbd, samp, svg, math
```

Também são ignorados comentários, `DOCTYPE`, declarações XML e processing instructions.

Exemplo:

```html
<p>Any programming book with <em>Patterns</em> in its name.</p>
```

Hoje isso pode ser traduzido em três nós separados:

```text
"Any programming book with "
"Patterns"
" in its name."
```

Essa escolha preserva a estrutura, mas pode perder contexto. A melhoria planejada é traduzir blocos com placeholders de tags, sem enviar HTML real ao tradutor.

## 12. Cache, glossário e chunking

O cache SQLite usa chave baseada em:

```text
source_lang + target_lang + SHA-256(texto original)
```

O glossário é aplicado depois da tradução e também sobre textos recuperados do cache. Isso mantém o comportamento consistente entre texto novo e texto reaproveitado.

Textos longos são divididos antes de serem enviados ao tradutor. A regra atual tenta dividir por:

```text
parágrafos
-> frases
-> palavras
-> corte inevitável de tokens muito grandes
```

O limite padrão é `3000` caracteres.

## 13. Preflight e erros esperados

Antes de uma tradução real, o Ayvu verifica:

- par de idiomas;
- glossário;
- criação do tradutor;
- escrita no cache;
- leitura do EPUB;
- chamada de teste ao tradutor.

Em `--dry-run`, a chamada real ao tradutor é pulada. Falhas esperadas são convertidas em mensagens curtas com causa provável e próximo passo, evitando traceback para erro comum de usuário.

## 14. Retomada local

Além do cache SQLite, traduções reais registram um estado local em:

```text
~/Documentos/Livros/Processando
```

Esse estado guarda caminhos e opções da execução para facilitar retomada pelo modo comum. Ele não substitui o cache e não é apagado automaticamente.

O cache continua sendo a parte que evita retraduzir textos já concluídos.

## 15. Relatórios

Ao final da tradução, o Ayvu mostra um relatório no terminal com:

- EPUB original;
- idiomas;
- saída gerada;
- capítulos processados;
- textos traduzidos;
- textos reaproveitados do cache;
- textos pulados no dry-run;
- erros.

No modo comum, o Ayvu também oferece salvar esse relatório em Markdown em `~/Documentos/Livros/Relatorios`, sem sobrescrever relatórios anteriores.

## 16. Bug crítico: EPUB com tela branca

Durante o desenvolvimento inicial, um EPUB traduzido abria no leitor, mas mostrava tela branca.

O EPUB original tinha capítulos internos com milhares de bytes, mas o EPUB gerado tinha documentos reduzidos a algo como:

```html
<head/>
<body/>
```

O problema não estava na tradução isolada do HTML. A função de tradução preservava o conteúdo quando testada separadamente.

O problema aparecia ao reescrever o livro com `ebooklib.write_epub()`, que reconstruía alguns documentos `EpubHtml` vazios.

A correção foi abandonar a reescrita completa pelo `ebooklib` e copiar o EPUB original como ZIP, substituindo somente os documentos traduzidos. Essa decisão continua sendo central para a estabilidade do Ayvu.

## 17. LibreTranslate

O backend atual é `LibreTranslateTranslator`.

Endpoint de tradução:

```text
http://localhost:5000/translate
```

Endpoint de idiomas:

```text
http://localhost:5000/languages
```

Subir LibreTranslate com Docker:

```bash
docker run -it -p 5000:5000 libretranslate/libretranslate
```

Testar conexão:

```bash
uv run ayvu test-translator --url http://localhost:5000
```

Se o servidor estiver indisponível, o Ayvu deve falhar com uma mensagem orientada a ação, não com traceback bruto.

## 18. Testes e CI

A suíte atual tem 100 testes definidos em `tests/`, cobrindo:

- cache SQLite;
- chunking;
- glossário;
- configuração local;
- tradução de HTML;
- preservação de tags;
- extração de texto visível;
- caminhos internos de EPUB;
- cópia conservadora do EPUB;
- validação do EPUB gerado;
- backend LibreTranslate;
- listagem de idiomas;
- preflight;
- estado de retomada;
- progresso;
- comandos CLI e fluxos guiados.

O CI está em `.github/workflows/tests.yml` e roda:

```bash
uv sync --extra dev --frozen
uv run pytest
```

## 19. Próximos passos técnicos

Prioridades que ainda fazem sentido:

1. Traduzir blocos HTML preservando tags internas por placeholders.
2. Proteger termos especiais antes da tradução: URLs, comandos, caminhos, versões, placeholders e código inline.
3. Evoluir o glossário para regras explícitas de preservar, traduzir e proibir termos.
4. Melhorar validação pós-tradução, incluindo links, capítulos vazios, imagens ausentes e texto não traduzido.
5. Criar configuração persistente para idioma padrão, pastas e preferências.
6. Melhorar cache com inspeção, limpeza, exportação e escopo por backend/modelo/glossário.
7. Adicionar modo `--cache-only`.
8. Suportar backends alternativos.
9. Documentar arquitetura em um documento dedicado.
10. Preparar empacotamento e releases públicas.

## 20. Possível suporte a PDF

PDF continua sendo um alvo futuro e mais difícil que EPUB, porque não é uma estrutura semântica de livro. PDF é mais próximo de páginas impressas com posições absolutas.

Caminho mais realista:

```text
PDF
-> extrair blocos de texto
-> gerar EPUB reflowable
-> usar pipeline atual de tradução EPUB
```

Não é recomendado começar tentando traduzir PDF preservando layout perfeito. A tradução muda tamanho de texto e pode quebrar caixas, colunas, tabelas e fontes.

## 21. Ideia central

O Ayvu deixou de ser um script de tradução e virou uma base real de CLI:

```text
CLI instalável
EPUB original preservado
cache
glossário
tradução local
preflight
progresso visual
retomada
validação
testes
CI
documentação
```

O próximo salto é melhorar qualidade de tradução, robustez de validação e experiência de configuração sem comprometer a regra principal: nunca alterar o EPUB original.
