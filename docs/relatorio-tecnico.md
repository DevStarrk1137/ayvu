# Relatório técnico: ayvu

Este documento resume o que foi construído, quais decisões técnicas foram tomadas, quais bugs apareceram durante o uso real e como continuar o projeto depois.

## 1. Objetivo do projeto

O objetivo foi criar uma ferramenta CLI em Python chamada `ayvu` para traduzir arquivos EPUB locais usando um tradutor HTTP local, inicialmente compatível com LibreTranslate.

A ferramenta foi pensada para uso pessoal e estudo. Ela não remove DRM, não baixa livros e não distribui conteúdo protegido. O EPUB original nunca é modificado.

O fluxo desejado:

```text
arquivo.epub em inglês
-> extrair XHTML/HTML internos
-> traduzir só textos visíveis
-> preservar HTML, CSS, imagens, links e estrutura
-> salvar novo EPUB traduzido
-> usar cache SQLite para retomar depois
```

## 2. Estrutura criada

Estrutura principal do projeto:

```text
ayvu/
├── README.md
├── glossary.example.json
├── pyproject.toml
├── docs/
│   └── relatorio-tecnico.md
├── src/
│   └── ayvu/
│       ├── __init__.py
│       ├── cache.py
│       ├── chunking.py
│       ├── cli.py
│       ├── epub_io.py
│       ├── glossary.py
│       ├── html_translate.py
│       ├── translator.py
│       └── validation.py
└── tests/
    ├── test_cache.py
    ├── test_chunking.py
    ├── test_epub_io.py
    ├── test_glossary.py
    └── test_html_translate.py
```

## 3. Stack usada

Dependências principais:

- Python 3.11+
- `ebooklib`
- `beautifulsoup4`
- `lxml`
- `requests`
- `typer`
- `rich`
- `sqlite3` da biblioteca padrão
- `pytest`

O pacote é instalável via `pyproject.toml` e expõe o comando:

```bash
ayvu
```

## 4. Comandos implementados

Inspecionar um EPUB:

```bash
ayvu inspect game.epub
```

Testar o LibreTranslate local:

```bash
ayvu test-translator --url http://localhost:5000
```

Traduzir:

```bash
ayvu translate game.epub \
  --output game-ptbr.epub \
  --source en \
  --target pt \
  --translator libretranslate \
  --url http://localhost:5000 \
  --cache .cache/traducoes.sqlite \
  --glossary glossary.json
```

Rodar em modo dry-run:

```bash
ayvu translate game.epub \
  --output teste.epub \
  --dry-run
```

Extrair texto para Markdown:

```bash
ayvu extract game.epub --output livro-extraido/
```

Sobrescrever arquivo de saída existente:

```bash
ayvu translate game.epub \
  --output game-ptbr.epub \
  --overwrite
```

## 5. Como instalar e testar

Dentro do diretório do projeto:

```bash
cd ayvu

python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"

pytest
```

Estado atual dos testes após as correções:

```text
15 passed
```

## 6. Tradutor local

O tradutor foi abstraído por uma interface:

```python
class Translator:
    def translate(self, text: str, source: str, target: str) -> str:
        ...
```

A implementação inicial é `LibreTranslateTranslator`.

Endpoint padrão:

```text
http://localhost:5000/translate
```

Payload enviado:

```json
{
  "q": "text",
  "source": "en",
  "target": "pt",
  "format": "text"
}
```

Resposta esperada:

```json
{
  "translatedText": "texto traduzido"
}
```

Rodar LibreTranslate via Docker:

```bash
docker run -it -p 5000:5000 libretranslate/libretranslate
```

## 7. Cache SQLite

O cache fica em SQLite e permite retomar traduções interrompidas.

Tabela:

```sql
CREATE TABLE IF NOT EXISTS translations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_lang TEXT NOT NULL,
    target_lang TEXT NOT NULL,
    original_text_hash TEXT NOT NULL,
    original_text TEXT NOT NULL,
    translated_text TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_lang, target_lang, original_text_hash)
);
```

Funcionamento:

```text
texto original
-> calcula hash SHA-256
-> procura no cache por source/target/hash
-> se existir, usa tradução salva
-> se não existir, chama tradutor local
-> salva a tradução no cache
```

Isso foi importante durante o uso real, porque o primeiro EPUB tinha milhares de trechos. Quando o processo é interrompido ou falha, a execução seguinte reaproveita o que já foi salvo.

No caso testado, o cache chegou a ter mais de 5000 entradas `en -> pt`.

## 8. Tradução de HTML

A regra principal foi:

```text
Não mandar HTML inteiro para o tradutor.
Traduzir somente nós de texto visíveis.
```

Tags ignoradas:

```text
script, style, code, pre, kbd, samp, svg, math
```

Também foi corrigido um caso importante: a ferramenta não deve traduzir `DOCTYPE`, declarações XML, comentários ou instruções de processamento.

Exemplo:

Entrada:

```html
<p class="calibre1">Any programming book with <em>Patterns</em> in its name.</p>
```

Saída esperada:

```html
<p class="calibre1">Qualquer livro de programação com <em>Patterns</em> no nome.</p>
```

A tag `<em>` continua existindo. O texto dentro dela pode ser traduzido ou mantido dependendo do tradutor/cache/glossário.

## 9. Glossário

Foi adicionado `glossary.example.json`:

```json
{
  "Game Loop": "loop de jogo",
  "Design Pattern": "padrão de projeto",
  "Observer": "Observer",
  "Command": "Command",
  "State": "State",
  "Singleton": "Singleton",
  "Object Pool": "pool de objetos"
}
```

O glossário serve para controlar termos técnicos. Ele é aplicado depois da tradução. Exemplo:

```text
Game Loop -> loop de jogo
Observer -> Observer
Command -> Command
```

Se não quiser usar glossário, basta remover a opção:

```bash
--glossary glossary.json
```

Também foi melhorado o erro quando o arquivo de glossário não existe. Antes aparecia traceback. Agora a CLI mostra:

```text
Glossary error: Glossary file not found: glossary.json
Create the file, pass the correct path, or remove --glossary to run without one.
```

## 10. Chunking

Textos grandes são divididos em blocos menores antes de enviar ao tradutor.

Regra atual:

```text
limite padrão: 3000 caracteres
tentativa de dividir por parágrafos
depois por frases
por fim por palavras
```

Isso evita mandar textos enormes para o LibreTranslate e reduz chance de timeout.

## 11. Progresso visual

No primeiro teste real, a ferramenta parecia travada porque ficava silenciosa durante a tradução.

Foi adicionado progresso com `rich`:

```text
Chapters 176/176: titlepage.xhtml
Texts 6170 | new 0 | cache 6011 | errors 159
```

Isso resolveu a sensação de travamento e deixou claro que o processo estava trabalhando.

## 12. Bug crítico: EPUB com tela branca

Sintoma:

```text
O EPUB final abria no leitor, mas mostrava tela branca.
```

Investigação:

O EPUB original tinha capítulos internos com milhares de bytes:

```text
text/part0007_split_001.html -> 9422 bytes
```

O EPUB traduzido defeituoso tinha capítulos com cerca de 264 bytes:

```text
EPUB/text/part0007_split_001.html -> 264 bytes
```

Ao abrir o XHTML interno:

```html
<head/>
<body/>
```

Ou seja: a estrutura do EPUB existia, mas os capítulos estavam vazios.

Diagnóstico:

O problema não estava na tradução isolada do HTML. A função `translate_html()` preservava conteúdo quando testada sozinha.

O problema apareceu no momento de gravar o EPUB com `ebooklib.write_epub()`. A biblioteca reconstruía os documentos `EpubHtml` e acabava produzindo capítulos com `<head/>` e `<body/>` vazios em alguns casos.

## 13. Correção do bug da tela branca

A estratégia foi alterada.

Antes:

```text
ebooklib lê EPUB
-> modifica EpubHtml
-> ebooklib.write_epub reescreve o EPUB inteiro
```

Depois:

```text
abre EPUB original como ZIP
-> lê XHTML/HTML original direto do ZIP
-> traduz o conteúdo
-> copia todos os arquivos originais para o novo EPUB
-> substitui somente os XHTML/HTML traduzidos
```

Isso é mais conservador e adequado para EPUB, porque preserva:

- `content.opf`
- `toc.ncx`
- imagens
- CSS
- caminhos internos
- arquivos não modificados
- estrutura geral do ZIP

O `ebooklib` ainda é usado para inspecionar e localizar documentos, mas não é mais usado para reconstruir o EPUB final.

Validação após correção:

```text
ValidationResult(ok=True, warnings=[], document_count=176)
```

Exemplo de capítulo interno após correção:

```html
<body class="calibre">
<h2 class="calibre10" id="calibre_pb_1">Configurar a Entrada</h2>
<p class="calibre1">Algures em cada jogo está um pedaço de código...</p>
```

O capítulo deixou de estar vazio.

## 14. Erros restantes do LibreTranslate

Em uma execução, o relatório mostrou:

```text
Texts 6170 | new 0 | cache 6011 | errors 159
```

Isso significa:

- 6011 textos foram carregados do cache;
- 159 textos não estavam no cache;
- esses 159 precisavam do LibreTranslate;
- mas o servidor local não estava acessível naquele momento.

Mensagem:

```text
Could not connect to LibreTranslate at http://localhost:5000/translate.
Is the local translation server running?
```

Solução:

Subir o LibreTranslate e rodar novamente com o mesmo cache:

```bash
docker run -it -p 5000:5000 libretranslate/libretranslate
```

Depois:

```bash
ayvu translate game.epub \
  --output game-ptbr.epub \
  --source en \
  --target pt \
  --translator libretranslate \
  --url http://localhost:5000 \
  --cache .cache/traducoes.sqlite \
  --glossary glossary.json \
  --overwrite
```

## 15. Arquivos importantes

CLI:

```text
src/ayvu/cli.py
```

Leitura, inspeção, extração e empacotamento EPUB:

```text
src/ayvu/epub_io.py
```

Tradução de HTML:

```text
src/ayvu/html_translate.py
```

Tradutor HTTP:

```text
src/ayvu/translator.py
```

Cache SQLite:

```text
src/ayvu/cache.py
```

Glossário:

```text
src/ayvu/glossary.py
```

Chunking:

```text
src/ayvu/chunking.py
```

Validação:

```text
src/ayvu/validation.py
```

## 16. Testes atuais

Cobertura criada:

- cache SQLite;
- divisão de texto em chunks;
- aplicação de glossário;
- tradução de HTML preservando tags;
- ignorar `script`, `style`, `code`, `pre`;
- não traduzir `DOCTYPE` e comentários;
- resolução de caminhos internos para EPUB com OPF na raiz ou em subpasta.

Rodar:

```bash
pytest
```

Resultado atual:

```text
15 passed
```

## 17. Próximos passos técnicos

Prioridades recomendadas:

1. Criar `.gitignore`, `LICENSE`, `CHANGELOG.md` e `CONTRIBUTING.md`.
2. Adicionar GitHub Actions rodando `pytest`.
3. Tratar `Ctrl+C` com relatório parcial mais limpo.
4. Melhorar o relatório final para resumir erros repetidos.
5. Criar testes com EPUB mínimo gerado por código.
6. Adicionar modo `--cache-only` para gerar EPUB usando apenas cache, sem chamar tradutor.
7. Melhorar qualidade da tradução preservando tags com placeholders.
8. Adicionar suporte opcional a outros tradutores locais.
9. Criar documentação de arquitetura.
10. Melhorar UX para uso open source.

## 18. Melhorias de qualidade de tradução

O MVP traduz nó de texto por nó de texto. Isso preserva HTML, mas pode perder contexto quando uma frase está dividida por tags.

Exemplo:

```html
<p>Any programming book with <em>Patterns</em> in its name.</p>
```

Hoje isso pode virar três traduções separadas:

```text
"Any programming book with "
"Patterns"
" in its name."
```

Uma melhoria futura seria traduzir o bloco inteiro usando placeholders:

```text
Any programming book with __TAG_1_OPEN__Patterns__TAG_1_CLOSE__ in its name.
```

Depois da tradução, os placeholders seriam substituídos de volta pelas tags.

Isso preservaria melhor contexto sem enviar HTML real ao tradutor.

## 19. Possível suporte a PDF

Foi discutida a possibilidade de aplicar ideia semelhante a PDFs.

Conclusão:

PDF é mais difícil que EPUB porque não é estrutura semântica de livro. PDF é mais próximo de páginas impressas com posições absolutas.

Caminho mais realista:

```text
PDF
-> extrair blocos de texto
-> gerar EPUB reflowable
-> usar pipeline atual de tradução EPUB
```

Um comando futuro poderia ser:

```bash
ayvu pdf-to-epub livro.pdf --output livro.epub
```

Depois:

```bash
ayvu translate livro.epub --output livro-ptbr.epub
```

Bibliotecas candidatas:

- `PyMuPDF`
- `pdfplumber`
- `ocrmypdf` e `tesseract` para PDFs escaneados

Não é recomendado começar tentando traduzir PDF preservando layout perfeito. Isso é frágil porque a tradução muda tamanho de texto, quebra caixas, colunas, tabelas e fontes.

## 20. Lições técnicas do processo

Algumas decisões importantes que apareceram durante o uso real:

- Progresso visual é parte da experiência de usuário, não detalhe cosmético.
- Cache é essencial em tarefas longas.
- EPUB deve ser tratado de forma conservadora; reescrever o pacote inteiro pode quebrar estrutura.
- Validar apenas “o arquivo existe” é insuficiente.
- É preciso inspecionar os arquivos internos quando algo abre em branco.
- O pipeline precisa continuar mesmo quando alguns capítulos ou textos falham.
- Erros repetidos devem ser resumidos no futuro para não poluir o terminal.

## 21. Comando recomendado para continuar

Subir o tradutor:

```bash
docker run -it -p 5000:5000 libretranslate/libretranslate
```

Em outro terminal:

```bash
cd ayvu
source .venv/bin/activate

ayvu test-translator --url http://localhost:5000

ayvu translate game.epub \
  --output game-ptbr.epub \
  --source en \
  --target pt \
  --translator libretranslate \
  --url http://localhost:5000 \
  --cache .cache/traducoes.sqlite \
  --glossary glossary.json \
  --overwrite
```

Depois abrir `game-ptbr.epub` no leitor e verificar:

- capa;
- sumário;
- primeiro capítulo;
- capítulos do meio;
- links internos;
- imagens;
- blocos de código;
- notas e referências.

## 22. Ideia central

O projeto deixou de ser apenas um script de tradução e virou uma base real para um software open source:

```text
CLI instalável
cache
tradução local
progresso visual
validação
testes
documentação
bug real investigado e corrigido
```

O próximo salto não é escrever mais código sem direção. É transformar isso em produto pequeno, confiável e bem documentado.
