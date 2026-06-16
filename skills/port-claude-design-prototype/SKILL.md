---
name: port-claude-design-prototype
description: Porta um protótipo HTML/React (index.html + pasta de módulos .jsx/.js + offline.html auto-contido) gerado pelo Claude Design para a stack do projecto actual, preservando look-and-feel e regras de negócio com paridade verificável. Usar quando o utilizador pedir para portar, converter, integrar ou implementar um protótipo com esta estrutura na sua codebase.
license: MIT
---

# Port de protótipo HTML/React para a stack do projecto

Esta skill converte um protótipo de design (gerado em HTML + React/Babel) numa
implementação nativa da codebase onde estás a trabalhar. O objectivo é **paridade
visual e comportamental**, não tradução de código.

## 1. Localizar e validar os artefactos

Procura no repositório (ou pede ao utilizador) três artefactos:

| Artefacto                             | Como reconhecer                                                                   | Papel                                                                                                          |
| ------------------------------------- | --------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `index.html`                          | Entrypoint com um grande bloco `<style>` e `<script type="text/babel" src="...">` | **Fonte de verdade do VISUAL** — variáveis CSS, classes, estados, temas (`data-theme`/`data-*`), media queries |
| Pasta de módulos                      | Ficheiros `.jsx`/`.js` referenciados pelo entrypoint                              | **Fonte de verdade do COMPORTAMENTO** — estados, regras de negócio, limites, permissões, copy                  |
| `offline.html` (ou `*(offline).html`) | Ficheiro único e grande (centenas de KB), auto-contido                            | **Referência executável** — abrir no browser e usar como critério final de aceitação                           |

Regras sobre os artefactos:

- **Nunca leias nem edites o `offline.html` como código** — está compilado. Serve apenas para correr e comparar.
- Ficheiros tipo `data.js`/seeds são dados de demonstração: identifica-os cedo e marca-os para substituição por dados/API reais.
- Ignora ficheiros de infra-estrutura do protótipo (ex.: `tweaks-panel.jsx`, painéis de afinação de design): são ferramentas de design-time, **não fazem parte do produto a portar** — salvo indicação do utilizador.
- Se faltar algum artefacto, pára e pede-o antes de começar.

## 2. Detectar a stack alvo

Não perguntes se conseguires inferir. Examina a codebase: gestor de pacotes,
framework de UI, sistema de templates, convenções de componentes, mecanismo de
estado, pipeline de estilos (CSS plano, SCSS, Tailwind, CSS-in-JS…) e estrutura
de pastas. O port deve parecer escrito por quem mantém esse repositório.

Se a codebase usar um framework CSS que conflitue com o CSS do protótipo
(ex.: Tailwind com preflight, bibliotecas de componentes com tema próprio),
**pergunta antes de decidir** entre isolar o CSS do protótipo ou mapeá-lo para o
sistema existente.

## 3. Extracção de primários: ícones, componentes e layouts

Estas três categorias são a maior fonte de retrabalho em ports. Extrai-as como
artefactos próprios ANTES de implementar qualquer ecrã — não as descubras à medida.

### 3.1 Ícones

Os protótipos costumam definir os ícones como SVG inline num único componente
(ex.: um `Icon` com um mapa nome → paths, geralmente em `shell.jsx` ou similar).

- Localiza esse mapa e **extrai TODOS os ícones de uma vez** para o formato da stack
  alvo (sprite SVG, componentes individuais, ou a biblioteca de ícones já usada na
  codebase — vê primeiro o que existe).
- Copia os paths **verbatim**, incluindo `viewBox`, `stroke-width`, `stroke-linecap`/
  `linejoin` e `fill`/`stroke` — a personalidade de um set de ícones está nesses
  atributos, não só nos paths. Não substituas por ícones "parecidos" de outra
  biblioteca sem perguntar.
- Produz uma tabela nome → onde é usado → tamanhos usados (`size=` nos call sites),
  e verifica no fim que nenhum nome ficou por mapear (um grep pelos usos apanha isto).

### 3.2 Catálogo de componentes

Antes de recriar ecrãs, produz um `PORT-COMPONENTS.md`: para cada componente do
protótipo (percorre os módulos ficheiro a ficheiro), regista:

- nome, ficheiro de origem e responsabilidade numa linha;
- props/parâmetros e variantes (ex.: `btn--primary`, `btn--ghost`, `btn--xs`);
- estados visuais (hover, focus, disabled, active, erro) e de dados (vazio, loading);
- **mapeamento para a stack alvo**: componente existente da codebase a reutilizar,
  ou novo a criar — decisão explícita por componente, não implícita.
- componentes partilhados (botões, badges, modais, campos) implementam-se PRIMEIRO
  e uma só vez; os ecrãs só começam quando o catálogo base está verificado.

### 3.3 Esqueletos de layout

Screenshots não chegam para reproduzir layout — a estrutura está no CSS. Para cada
ecrã/região principal, regista o **esqueleto**:

- a árvore de containers com o mecanismo de cada um (`flex` vs `grid`, direcção,
  `gap`, `grid-template-columns/rows`, alinhamentos);
- larguras máximas e centragens (ex.: `max-width: 760px; margin: 0 auto`), pinning
  (headers/prompt bars fixos vs. conteúdo scrollável — onde vive o `overflow`);
- breakpoints e o que muda em cada um (lê os `@media` do `index.html` todos de uma vez);
- z-index/camadas (drawers, modais, overlays) e as suas transições.

Reproduz o layout copiando estas regras do CSS fonte — não "a olho" a partir do
`offline.html`. O `offline.html` serve para confirmar, não para inferir.

## 4. Inventário antes de código

Abre o `offline.html` e percorre TUDO. Produz um ficheiro `PORT-INVENTORY.md` com:

- Lista de ecrãs/vistas e como se chega a cada um;
- Estados de cada ecrã: vazio, loading/streaming, erro, cheio, limites atingidos;
- Roles/permissões e o que cada role vê ou não vê;
- Fluxos completos (ex.: login → acção → resultado), incluindo casos-limite;
- Regras de negócio com valores exactos (quotas, máximos, timeouts), **confirmados
  no código fonte dos módulos — nunca inferidos visualmente**.

Este inventário é o contrato de aceitação. Mostra-o ao utilizador antes de
implementar se houver qualquer ambiguidade.

## 5. Implementação (por esta ordem)

1. **Design tokens** — extrai as variáveis CSS do `index.html` para o mecanismo de
   theming da stack alvo, sem alterar valores. Preserva todos os temas/modos.
2. **CSS** — copia as classes quase literalmente, mantendo os nomes sempre que
   possível (torna a auditoria visual trivial). Não modernizes, não troques fontes,
   não reinterpretes espaçamentos. Estados hover/focus/disabled e breakpoints fazem
   parte do contrato.
3. **Ícones** — porta o set completo de uma vez (secção 3.1) e verifica a tabela
   de usos antes de avançar.
4. **Componentes base** — implementa primeiro o catálogo partilhado (secção 3.2):
   botões com todas as variantes, badges, campos, modais. Compara cada um isolado
   com o `offline.html` antes de o usar em ecrãs.
5. **Layouts** — monta os esqueletos de cada ecrã (secção 3.3) com conteúdo
   placeholder e valida estrutura/scroll/breakpoints antes de preencher.
6. **Comportamento** — reimplementa a lógica dos módulos preservando exactamente:
   limites numéricos, condições de permissão, ordem de operações, e o que acontece
   em cada caso-limite. Liga estado em memória/seeds à API real mantendo o contrato.
7. **Copy** — preserva todos os textos, mensagens de erro, avisos legais e microcopy
   no idioma original do protótipo, salvo indicação em contrário.

A ordem importa: tokens → ícones → componentes → layouts → comportamento. Cada
camada só começa quando a anterior está verificada — é isto que evita múltiplas
passagens de correcção.

## 6. Regras invioláveis

- Em dúvidas de **aparência**: vale o que o `offline.html` mostra.
- Em dúvidas de **comportamento**: vale o que os módulos fonte dizem.
- Não adicionar funcionalidades, ecrãs ou conteúdo que não existam no protótipo
  sem perguntar primeiro.
- Não introduzir dependências de UI que conflituem com o CSS do protótipo.
- Acessibilidade do protótipo (focus states, áreas de toque ≥44px, contraste,
  reduced-motion) é parte do contrato, não um extra.

## 7. Verificação ecrã-a-ecrã

Para cada linha do inventário:

1. Coloca o port e o `offline.html` no mesmo estado (mesmos dados, mesmo viewport).
2. Compara screenshots lado a lado.
3. Regista no `PORT-INVENTORY.md`: ✅ paridade · ⚠️ divergência justificada · ❌ por corrigir.

Nenhum ecrã está pronto sem esta comparação. No fim, nenhuma linha pode ficar em ❌.

Além dos ecrãs, verifica as três categorias da secção 3 transversalmente:

- **Ícones**: nenhum uso por mapear; stroke/fill/tamanhos iguais aos do protótipo.
- **Componentes**: cada variante do catálogo comparada isolada, não só em contexto.
- **Layouts**: testa nos breakpoints definidos nos `@media` E num viewport estreito
  (≤400px); confirma que o scroll vive nos containers certos e que elementos fixos
  (headers, prompt bars, drawers) não deslizam com o conteúdo.

## 8. Entrega

- Código integrado, a passar lint/checks existentes do projecto.
- `PORT-INVENTORY.md` completo com o estado de verificação de cada ecrã.
- `PORT-COMPONENTS.md` com o catálogo e o mapeamento componente→stack alvo.
- Tabela de ícones portados com os respectivos usos.
- Secção final "Decisões": pontos onde o protótipo era ambíguo e a opção tomada,
  para revisão humana.
