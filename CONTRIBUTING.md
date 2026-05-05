# Contribuindo com o Ayvu

Obrigado por contribuir com o Ayvu. Este projeto prioriza mudancas pequenas,
revisaveis e alinhadas ao fluxo de issues, branches, pull requests e releases.

## Escopo do Projeto

O Ayvu e uma CLI para traduzir EPUBs locais usando um tradutor HTTP local
compativel com LibreTranslate. A ferramenta nunca deve alterar o EPUB original,
remover DRM, baixar livros ou facilitar distribuicao de conteudo protegido.

## Fluxo de Trabalho

O fluxo padrao esta documentado em
[`docs/release-workflow.md`](docs/release-workflow.md). Antes de implementar uma
tarefa, confira se existe uma issue relacionada.

Resumo:

1. Selecione ou crie uma issue para a tarefa.
2. Crie uma branch curta e descritiva a partir da `main`.
3. Faca uma mudanca pequena e coerente com a issue.
4. Abra um pull request para merge na `main`.
5. Registre a validacao executada no pull request.
6. Relacione o PR com a issue usando `Refs #N` ou `Closes #N`.

Use nomes de branch com prefixo e descricao curta em kebab-case:

```text
fix/output-exists-message
docs/release-workflow
ci/pytest-github-actions
feat/internal-environment-check
refactor/cli-progress-module
```

## Desenvolvimento Local

Instale as dependencias de desenvolvimento com `uv`:

```bash
uv sync --extra dev
```

Rode a suite de testes:

```bash
uv run pytest
```

Comandos uteis:

```bash
uv run ayvu --help
uv run ayvu inspect livro.epub
uv run ayvu test-translator --url http://localhost:5000
```

## Regras de Contribuicao

- Preserve a estrutura interna dos EPUBs.
- Traduza apenas textos visiveis ao leitor.
- Nao altere o arquivo EPUB original.
- Use fakes ou mocks nos testes; nao dependa de um LibreTranslate real na suite
  automatica.
- Use `tmp_path` para arquivos temporarios em testes.
- Nao versione EPUBs, PDFs, caches SQLite, glossarios privados ou arquivos de
  uso pessoal.
- Atualize `README.md` ou `docs/` quando mudar comportamento de usuario,
  comandos, flags, cache, glossario ou formato de saida.

## Pull Requests

Um PR deve explicar:

- objetivo;
- o que mudou;
- o que ficou fora do escopo;
- validacao executada;
- issue relacionada.

Para mudancas de codigo, rode:

```bash
uv run pytest
```

Para mudancas apenas de documentacao, rode pelo menos:

```bash
git diff --check
```
