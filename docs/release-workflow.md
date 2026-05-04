# Fluxo de Issues, Branches e Releases

Este documento descreve o fluxo padrao usado no Ayvu para organizar tarefas, revisao e publicacao de versoes.

## Fluxo Padrao

1. Criar ou selecionar uma issue para a tarefa.
2. Criar uma branch curta e descritiva a partir da `main`.
3. Implementar a mudanca com commits pequenos e coerentes.
4. Abrir um pull request para merge na `main`.
5. Validar a mudanca com testes ou checagens adequadas.
6. Fazer merge do pull request.
7. Sincronizar a `main` local e remover a branch da tarefa.
8. Usar milestones, tags e GitHub Releases para organizar versoes.

## Issues

Cada tarefa deve ter uma issue antes da implementacao quando fizer parte do fluxo principal do projeto. A issue deve explicar o objetivo, o comportamento esperado, a motivacao e, quando fizer sentido, uma branch sugerida.

Issues pequenas podem representar correcoes, documentacao, testes, refatoracoes ou funcionalidades. Tarefas grandes devem ser divididas em etapas menores para manter os pull requests revisaveis.

## Branches

Use uma branch por tarefa, criada a partir da `main` atualizada. O nome deve ter um prefixo de tipo e uma descricao curta em kebab-case.

Exemplos:

```text
fix/output-exists-message
docs/release-workflow
ci/pytest-github-actions
feat/internal-environment-check
refactor/cli-progress-module
```

Evite nomes genericos como `feat`, `fix`, `refactor` ou `main2`.

## Pull Requests

Todo merge na `main` deve passar por pull request. A descricao do PR deve deixar claro:

- objetivo;
- o que mudou;
- o que ficou fora do escopo;
- validacao executada;
- issue relacionada.

Use `Refs #N` quando o PR apenas avanca uma issue e `Closes #N` quando o PR conclui a tarefa.

Antes de mergear uma mudanca de codigo, rode:

```bash
uv run pytest
```

Para mudancas apenas de documentacao, use pelo menos:

```bash
git diff --check
```

## Milestones

Milestones agrupam issues e PRs por versao planejada. Cada milestone deve ter um objetivo pequeno e claro, como polimento de UX, base de manutencao ou robustez inicial.

Ao criar ou revisar issues, associe a milestone mais proxima do objetivo da tarefa quando ela ja existir.

## Tags e GitHub Releases

Quando uma versao estiver pronta:

1. Confira se a `main` local esta sincronizada com `origin/main`.
2. Rode a suite de testes.
3. Crie uma tag seguindo a versao planejada.
4. Publique a tag no GitHub.
5. Crie um GitHub Release com resumo das mudancas, validacao e avisos relevantes.

Exemplo:

```bash
git switch main
git pull
uv run pytest
git tag v0.0.2
git push origin v0.0.2
```

O release deve mencionar as principais issues fechadas e qualquer limitacao importante para usuarios.

## Limpeza Apos Merge

Depois de mergear um PR:

1. Sincronize a `main` local.
2. Rode os testes se houve mudanca de codigo.
3. Apague a branch local e remota, salvo se houver motivo para mante-la.

Esse fluxo mantem a `main` como linha principal estavel e evita branches antigas sem proposito.
