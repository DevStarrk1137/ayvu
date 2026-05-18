# Changelog

Todas as mudancas relevantes deste projeto serao registradas neste arquivo.

O formato segue a ideia de uma secao "Nao publicado" para mudancas ainda nao
lancadas e secoes versionadas quando uma release for publicada.

## Nao publicado

### Adicionado

- Fluxo guiado inicial ao executar `uv run ayvu`.
- Modo comum e modo desenvolvedor via `--mode`.
- Preview traduzido com `uv run ayvu --preview livro.epub`.
- Comando `languages` para listar idiomas retornados pelo LibreTranslate.
- Formato inicial de configuracao em JSON para preferencias locais do Ayvu.
- Preflight antes da traducao real, verificando EPUB, cache, glossario,
  idiomas e tradutor.
- Estado local de retomada em `~/Documentos/Livros/Processando`.
- Relatorio Markdown opcional no modo comum.
- Tutorial para modo comum, fluxo intermediario e modo desenvolvedor.
- Tratamento limpo de interrupcao com `Ctrl+C`.
- Testes com EPUB minimo gerado por codigo.
- GitHub Actions para rodar `uv run pytest`.
- Documento de fluxo de issues, branches, pull requests e releases.
- Arquivos iniciais de manutencao do projeto: `LICENSE`, `CHANGELOG.md` e
  `CONTRIBUTING.md`.

### Atualizado

- README com recursos atuais, retomada pelo modo comum e correcao de texto
  duplicado.
- Relatorio tecnico alinhado ao estado atual do codigo, testes, CI e roadmap.

## 0.0.1 - Inicial

### Adicionado

- CLI `ayvu` para inspecionar, traduzir e extrair texto visivel de EPUBs
  locais.
- Backend HTTP inicial compativel com LibreTranslate.
- Cache SQLite para reaproveitar traducoes e retomar execucoes interrompidas.
- Glossario JSON opcional.
- Validacao basica do EPUB gerado.
- Relatorio final no terminal e opcao de salvar relatorio em Markdown.
