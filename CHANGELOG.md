# Changelog

Todas as mudancas relevantes deste projeto serao registradas neste arquivo.

O formato segue a ideia de uma secao "Nao publicado" para mudancas ainda nao
lancadas e secoes versionadas quando uma release for publicada.

## Nao publicado

### Adicionado

- Modo comum guiado ao executar `uv run ayvu`.
- Modo desenvolvedor direto e opcao global `--mode`.
- Preview traduzido com `uv run ayvu --preview livro.epub`.
- Comando `languages` para listar idiomas retornados pelo LibreTranslate.
- Selecao guiada de idioma de destino no modo comum, usando o idioma padrao
  salvo ou a lista retornada pelo LibreTranslate.
- Configuracao local em JSON com idioma padrao, pasta base dos livros, nomes
  das pastas das funcionalidades e app leitor de EPUB.
- Fluxo de primeiro uso para escolher idioma padrao, pasta base e nomes de
  pastas antes de salvar a configuracao.
- Menu `Settings` para alterar idioma padrao, pasta base, nomes de pastas e app
  leitor.
- Biblioteca inicial para listar EPUBs originais e traduzidos e abrir o arquivo
  escolhido no leitor configurado ou detectado pelo sistema.
- Deteccao automatica do idioma de origem pelo metadado do EPUB quando
  `--source` nao e informado.
- Plano de traducao exibindo origem e destino antes de iniciar.
- Validacao de rota de traducao pelo LibreTranslate, com suporte a rota
  intermediaria via ingles quando nao houver rota direta.
- Preflight antes da traducao real, verificando EPUB, cache, glossario, idiomas,
  rota de traducao e tradutor.
- Estado local de retomada em `~/Documentos/Livros/Processando` ou na pasta de
  processamento configurada.
- Oferta de retomada no modo comum quando uma traducao em andamento e detectada.
- Relatorio Markdown opcional no modo comum.
- Validacao do EPUB gerado com barra de progresso, avisos de capitulos vazios,
  links internos quebrados e imagens referenciadas ausentes.
- Tutorial para modo comum, fluxo intermediario e modo desenvolvedor.
- Testes com EPUB minimo gerado por codigo.
- GitHub Actions para rodar `uv run pytest`.
- Documento de fluxo de issues, branches, pull requests e releases.
- Arquivos iniciais de manutencao do projeto: `LICENSE`, `CHANGELOG.md` e
  `CONTRIBUTING.md`.
- Glossario avancado com regras `translate`, `preserve` e `forbidden`,
  mantendo compatibilidade com o formato simples de pares de termos.
- Relatorio de uso do glossario com contagem de termos aplicados, termos
  obrigatorios ausentes e termos proibidos encontrados na saida.
- Menu guiado de glossarios no modo comum, com criacao, edicao, previa,
  validacao, salvamento local e selecao antes de traduzir.
- Opcao `--translate-metadata` para traduzir o titulo do EPUB e a navegacao
  EPUB 3 de forma explicita e conservadora.

### Atualizado

- Traducao de HTML agora ocorre por bloco (paragrafos, titulos e itens de
  lista), substituindo tags internas como `em`, `strong` e links por
  placeholders e restaurando-as depois. O cache passa a usar o bloco como
  unidade de traducao.
- Saida padrao da traducao no modo comum agora e confirmada antes de iniciar.
- Modo comum permite sobrescrever, escolher outro nome ou cancelar quando o EPUB
  de saida ja existe.
- Erros esperados mostram mensagens mais curtas no modo comum e detalhes
  tecnicos no modo desenvolvedor.
- Avisos da validacao final entram no relatorio do terminal e no relatorio
  Markdown.
- README e relatorio tecnico foram atualizados para refletir modos de uso,
  retomada, configuracao, biblioteca, validacao, CI e roadmap.
- `glossary.example.json` agora demonstra o formato avancado de glossario.

### Corrigido

- Interrupcao com `Ctrl+C` mostra progresso parcial e orienta reutilizar o
  cache.
- EPUB invalido em `inspect` e `extract` falha sem traceback.
- Texto duplicado no README foi removido.

### Interno

- Progresso de traducao foi extraido para `src/ayvu/cli_progress.py`.
- Responsabilidades do backend LibreTranslate foram separadas em classes e
  parsers menores.
- Erros estruturais de EPUB foram separados do relatorio de traducao.
- Formato de configuracao, estado de retomada e validacao final ganharam testes
  dedicados.

## 0.0.1 - Inicial

### Adicionado

- CLI `ayvu` para inspecionar, traduzir e extrair texto visivel de EPUBs
  locais.
- Backend HTTP inicial compativel com LibreTranslate.
- Cache SQLite para reaproveitar traducoes e retomar execucoes interrompidas.
- Glossario JSON opcional.
- Validacao basica do EPUB gerado.
- Relatorio final no terminal e opcao de salvar relatorio em Markdown.
