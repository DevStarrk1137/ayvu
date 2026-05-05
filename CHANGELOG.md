# Changelog

Todas as mudancas relevantes deste projeto serao registradas neste arquivo.

O formato segue a ideia de uma secao "Nao publicado" para mudancas ainda nao
lancadas e secoes versionadas quando uma release for publicada.

## Nao publicado

### Adicionado

- Arquivos iniciais de manutencao do projeto: `LICENSE`, `CHANGELOG.md` e
  `CONTRIBUTING.md`.

## 0.0.1 - Inicial

### Adicionado

- CLI `ayvu` para inspecionar, traduzir e extrair texto visivel de EPUBs
  locais.
- Backend HTTP inicial compativel com LibreTranslate.
- Cache SQLite para reaproveitar traducoes e retomar execucoes interrompidas.
- Glossario JSON opcional.
- Validacao basica do EPUB gerado.
- Relatorio final no terminal e opcao de salvar relatorio em Markdown.
