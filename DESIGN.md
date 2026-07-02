# DESIGN.md — bess-arbitrage · direzione "Sala controllo"

Soggetto: strumento di analisi arbitraggio BESS sui mercati day-ahead EU.
Audience: Francesco (analisi), poi screenshot pubblici (LinkedIn).
Job della pagina: rendere tangibile quanto vale una batteria — e quanto di quel
valore una strategia reale porta a casa (capture ratio).

Vibe: monitoraggio notturno della rete — SCADA, quadri strumento, numeri mono.
Quieto ovunque, la boldness spesa in un solo punto (signature).

## Token

| Ruolo | Hex | Uso |
|---|---|---|
| bg | `#12161F` | sfondo app (blu-carbone, MAI nero puro) |
| surface | `#1B2230` | pannelli, metric card, strumento |
| border | `#2A3347` | bordi pannello, 1px |
| track | `#232B3B` | binari gauge, righe vuote |
| text | `#D8DEE9` | testo primario |
| muted | `#8A94A6` | label, eyebrow, assi |
| amber | `#F2A93B` | **il segnale**: prezzi, vendite, revenue reale, accent |
| cyan | `#5BC8D8` | strumentale: SOC, frecce di flusso |
| green | `#59B26B` | compra (carica a prezzo basso) |
| red | `#E06456` | solo errori/negativo |

## Type

- Display + body: **IBM Plex Sans** (400/600)
- Numeri e dati: **IBM Plex Mono** (400/600), sempre — ogni cifra a schermo è mono
- Eyebrow: Plex Mono, uppercase, letter-spacing .14em, muted

## Spacing / forma

- Radius 6px, bordi 1px `border`, niente ombre
- Pannelli: padding 12–22px; una sola gerarchia di superficie (surface su bg)

## Signature (una sola)

**Lo strumento capture**: pannello con ceiling → revenue reale in mono grande
ambra + gauge orizzontale flat che segna il capture ratio. È l'unico elemento
grande e caldo della pagina; tutto il resto resta quieto.

## Banned

Inter, blue/indigo Tailwind default, gradienti viola, cream+terracotta
(#F4F1EA/#D97757), nero puro + acid green, broadsheet hairline, hero
centrato + 3 card, ombre soffuse, emoji nei numeri.
