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
4. Rode a validacao adequada.
5. Abra um pull request para merge na `main`.
6. Registre a validacao executada no pull request.
7. Atualize `CHANGELOG.md` quando o PR entregar uma mudanca real para usuarios
   ou manutencao.
8. Relacione o PR com a issue usando `Refs #N` ou `Closes #N`.

Artefatos criados no GitHub devem ser escritos em ingles: titulo e corpo de
issues, mensagens de commit, titulo e corpo de pull requests, comentarios de
review e notas de release. A documentacao do projeto pode continuar em
portugues enquanto esse for o idioma usado nos arquivos existentes.

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
uv run ayvu
uv run ayvu inspect livro.epub
uv run ayvu test-translator --url http://localhost:5000
uv run ayvu languages --url http://localhost:5000
uv run ayvu --preview livro.epub
uv run ayvu translate livro.epub --target pt
uv run ayvu translate livro.epub --source en --target pt --output livro-pt.epub
uv run ayvu extract livro.epub --output livro-extraido/
uv run ayvu --mode common translate livro.epub
uv run ayvu --mode developer translate livro.epub --target pt
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
- Atualize `README.md`, `docs/tutorial-modo-comum-e-dev.md` ou
  `docs/relatorio-tecnico.md` quando mudar comportamento de usuario, comandos,
  flags, cache, glossario, retomada, validacao, relatorios, configuracao ou
  formato de saida.
- Atualize `CHANGELOG.md` no mesmo PR quando a mudanca entregar comportamento,
  correcao ou manutencao relevante. Nao atualize o changelog apenas por abrir
  uma issue.
- Mantenha mudancas de documentacao e codigo separadas quando isso facilitar
  revisao.

## Pull Requests

O PR deve mirar a `main` e deve ser aberto como draft quando ainda houver
decisao, revisao ou validacao pendente. O titulo e a descricao devem ser em
ingles, descritivos e sem prefixos artificiais como `[codex]` ou `[ai]`.

A descricao deve usar esta estrutura:

```md
## Objective

Short explanation of the PR goal.

## What changed

- Concrete change 1.
- Concrete change 2.

## Out of scope

- Related work intentionally left out.

## Validation

- `uv run pytest`: X tests passing.
- `git diff --check`: no errors.

## Related issue

Closes #N
```

Use `Refs #N` quando o PR apenas avancar parte de uma issue e `Closes #N`
quando concluir a tarefa.

Para mudancas de codigo, rode:

```bash
uv run pytest
```

Para mudancas apenas de documentacao, rode pelo menos:

```bash
git diff --check
```

Se a mudanca alterar fluxo de usuario, flags, cache, glossario, retomada,
validacao ou formato de saida, confirme que a documentacao publica tambem foi
atualizada.
