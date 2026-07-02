# Come funziona `bess-arbitrage` — guida per chi viene dai mercati finanziari

> Spiegazione discorsiva del progetto, pensata per chi conosce bene i mercati
> finanziari ma non l'energia né il codice. Si legge con calma in ~10 minuti.
> Ogni concetto tecnico è tradotto in un'analogia finanziaria.

---

## 1. In una frase

È un **desk di trading per una batteria**. Una batteria collegata alla rete elettrica
può comprare energia quando costa poco e rivenderla quando costa tanto. Questo
programma prende i prezzi reali dell'elettricità e calcola **quanto avrebbe potuto
guadagnare al massimo** una batteria gestita in modo perfetto.

In gergo finanziario: è un **modello di storage arbitrage** su una commodity
(l'elettricità), con il calcolo del **profitto teorico massimo** della strategia.

---

## 2. Perché esiste l'opportunità: lo spread intraday

Il punto di partenza è una stranezza dei mercati elettrici moderni. L'elettricità
**non si stocca facilmente**: va prodotta e consumata nello stesso istante. Quindi il
prezzo si muove tantissimo nell'arco della giornata, molto più di qualsiasi azione o
materia prima.

Cosa succede in una giornata tipo, in un mercato pieno di pannelli solari (la Germania):

- **Mezzogiorno** — c'è sole, milioni di pannelli producono insieme. L'offerta esplode,
  la domanda no → il prezzo **crolla**, a volte va **negativo** (ti *pagano* per
  consumare; nel nostro run su giugno 2025 il 5° percentile è **−15,6 €/MWh**).
- **Sera (19–22)** — il sole cala ma la gente torna a casa, accende tutto, e d'estate
  i condizionatori restano accesi. La domanda resta alta, l'offerta no → il prezzo
  **schizza**. Durante l'ondata di calore del 23 giugno 2026 il Belgio ha toccato
  **1.038 €/MWh** in serata.

Questa curva a "U" tra mezzogiorno e sera si chiama **duck curve**. La differenza tra
il minimo di mezzogiorno e il picco serale è lo **spread intraday** — ed è la materia
prima del business.

**Analogia finanziaria.** È esattamente un *contango/backwardation*, ma compresso in
24 ore e fortemente prevedibile nella forma (sempre basso a mezzogiorno, alto la sera).
Comprare il future di metà giornata e venderlo la sera, ogni giorno. La batteria è il
veicolo che ti permette di fare fisicamente questa carry trade — è il tuo **magazzino**.

E lo spread si sta **allargando ogni anno** man mano che entra più solare: non è un
evento, è un trend strutturale. Per questo lo storage è *il* business dell'energy
transition.

---

## 3. L'asset: la batteria come un magazzino con vincoli

Una batteria è un magazzino di energia, e come ogni magazzino ha dei limiti. Per
modellarla servono quattro parametri — tutti hanno un equivalente finanziario:

| Parametro | Cosa significa | Analogia finance |
|---|---|---|
| **Potenza** (MW) | quanto in fretta può caricare/scaricare | velocità di esecuzione / size per tick |
| **Durata** (ore) → **Capienza** (MWh) | quanta energia tiene in totale | dimensione massima della posizione / inventory cap |
| **Efficienza** (RTE, ~85%) | perdi energia ad ogni ciclo | costo di transazione / slippage |
| **Cicli/giorno** | quante volte al giorno la puoi usare (l'uso la consuma) | limite di turnover per non bruciare l'asset |

Esempio del nostro default: **1 MW / 2 ore = 2 MWh** di capienza. Significa che può
erogare 1 MW per 2 ore prima di scaricarsi. L'efficienza dell'85% vuol dire che se
metti dentro 100, ne riprendi 85 (il resto è perso in calore — la "commissione" fisica
del trade).

---

## 4. Cosa fa concretamente il programma

Dato lo **storico reale dei prezzi** ora per ora (un anno = 8.760 ore), il programma
decide, per ogni singola ora, se la batteria deve **caricare, scaricare o stare ferma**,
in modo da massimizzare il profitto totale — rispettando tutti i vincoli del magazzino.

Non lo fa per tentativi. Lo formula come un **problema di ottimizzazione** e lo risolve
in modo esatto.

**Cos'è un'ottimizzazione lineare (LP), spiegata semplice.** Immagina di dover scegliere
8.760 decisioni (una per ora) per massimizzare il PnL, ma con regole rigide: non puoi
scaricare più energia di quanta ne hai dentro, non puoi superare la capienza, non puoi
fare più di tot cicli al giorno. Un **solver LP** è un motore matematico che trova *la*
combinazione ottima di tutte queste decisioni insieme, garantita la migliore possibile.

**Analogia finanziaria.** È identico a un'ottimizzazione di portafoglio
(tipo Markowitz): massimizzi un obiettivo (qui il profitto, lì il rendimento) sotto una
serie di vincoli (qui capienza ed efficienza, lì budget e limiti di rischio). Stessa
matematica, stesso tipo di solver.

L'obiettivo che massimizza, scritto per esteso, è semplicemente:

> somma su tutte le ore di **(prezzo × energia venduta − prezzo × energia comprata)**

cioè: ricavi dalle scariche meno costo delle cariche. Buy low, sell high, 8.760 volte,
ottimizzato in colpo solo.

---

## 5. Il concetto chiave: "perfect foresight" = il tetto teorico

C'è un trucco importante. Il programma **conosce in anticipo tutti i prezzi** dell'anno.
Quindi gioca con le carte scoperte: sa già quando sarà il minimo e quando il picco.

Questo è **deliberato**. Il risultato non è quanto guadagnerebbe un operatore reale — è
il **massimo assoluto** che la batteria avrebbe potuto estrarre da quel mercato. Il
**ceiling**, il tetto.

**Analogia finanziaria — e qui un trader capisce subito.** È un **backtest con
lookahead**, un *perfect-information upper bound*. È il numero che ottieni se conosci il
futuro. Nessuna strategia reale lo batte; tutte ne catturano una **percentuale**.

E proprio per questo è utile, in due modi:

1. **Quanto valore c'è sul piatto.** Il ceiling ti dice il potenziale massimo di quel
   mercato per quel tipo di batteria. È la dimensione dell'opportunità.
2. **Come si misura un operatore.** Se un trader reale (che usa *previsioni* di prezzo,
   non il futuro vero) porta a casa l'80% del ceiling, ha una **capture ratio dell'80%**.
   È *esattamente* la metrica con cui si valuta la performance di chi gestisce una
   batteria — il mestiere del "revenue & optimisation analyst" nello storage.

---

## 6. La tecnologia dietro, pezzo per pezzo

Tre componenti, niente di esotico:

- **I dati — `energy-charts.info`.** I prezzi spot orari arrivano da un'API pubblica e
  gratuita del Fraunhofer Institute (l'ente di ricerca tedesco). Stesso ruolo di un
  Bloomberg/Refinitiv per i prezzi storici, ma aperto. Coordinate del mercato: la
  **"bidding zone"** (es. `DE-LU` = Germania-Lussemburgo) è l'equivalente del *ticker*.
- **Il solver — HiGHS.** Il motore matematico open-source che risolve l'ottimizzazione
  lineare. Una libreria standard, la stessa categoria di solver usati nei desk quant.
- **Il linguaggio — Python.** Il codice è ~85 righe di modello più la parte dati. Tre
  file: uno scarica i prezzi, uno costruisce e risolve l'ottimizzazione, uno è
  l'interfaccia da riga di comando.

Lo lanci così:

```bash
uv run python -m bess_arbitrage --bzn DE-LU --start 2025-01-01 --end 2025-12-31
```

---

## 7. Come leggere il risultato

Output reale su Germania, anno 2025 intero:

```
DE-LU  2025-01-01..2025-12-31   (8760 h)
  price: mean 89.3  p5 -0.1  p95 162.4 EUR/MWh
  battery: 1.0 MW / 2.0 h (2.0 MWh), RTE 85%, cap 1.5 cyc/d
  CEILING revenue: 84,901 EUR/MW/year  (total 84,901 EUR)
  capex 250,000 EUR -> simple payback 2.9 y
```

Come si legge, riga per riga:

- **price** — il prezzo medio è stato 89 €/MWh, ma il 5° percentile è ~0 e il 95° è 162:
  ecco lo spread su cui si lavora. La dispersione *è* l'opportunità.
- **CEILING revenue: 84.901 €/MW/anno** — il numero chiave. Una batteria da 1 MW gestita
  perfettamente avrebbe potuto incassare ~85 mila euro nel 2025 dal solo arbitraggio
  day-ahead. (Su giugno 2025, mese più volatile, lo stesso conto annualizzato dà
  **114 mila** — più solare a mezzogiorno = spread più larghi = più margine.)
- **payback 2,9 anni** — con un costo di ~250 mila € per quella batteria (benchmark di
  mercato $125/kWh), il ceiling la ripaga in ~3 anni. È un **payback a foresight
  perfetto**: quello reale è più lungo, perché un operatore vero cattura solo una
  frazione del tetto.

**Reality check.** ~85k €/MW/anno di solo arbitraggio è coerente con i numeri di mercato
pubblicati (Modo Energy stima ~100k €/MW/anno in Germania nel 2025, ma includendo anche
i servizi di rete oltre all'arbitraggio puro). Stesso ordine di grandezza → il modello
non sta dicendo sciocchezze.

---

## 8. Cosa NON fa ancora (onestà intellettuale)

Per non vendere fumo, ecco i limiti dichiarati — sono anche la roadmap:

- **Non usa previsioni reali.** Oggi conosce il futuro (è il ceiling). Il passo
  successivo è far girare la strategia con *previsioni* di prezzo e misurare la capture
  ratio vs il tetto. Lì si vede la bravura vera.
- **Solo arbitraggio day-ahead.** Una batteria reale guadagna anche da altri mercati
  (servizi di bilanciamento/frequenza). Aggiungerli ("revenue stacking") alza i numeri.
- **Degrado semplificato.** Modella l'usura con un tetto di cicli/giorno, non con una
  curva di degradazione dettagliata della chimica della batteria.
- **Un solo asset, un solo mercato per volta.** Niente portafoglio multi-sito ancora.

---

## 9. Perché questo progetto conta

Lo storage è il pezzo che rende possibile la transizione energetica: senza batterie, il
solare di mezzogiorno è sprecato e le sere restano fossili. Il valore di una batteria
**è** la sua capacità di catturare lo spread intraday — e questo programma è il motore
minimo che quel valore lo **misura**, sui dati veri.

Da lì si scala in tutte le direzioni: confronto tra mercati (Germania vs Belgio vs UK),
strategia con previsioni reali, valutazione di un intero portafoglio. Ma il cuore —
*"dato un mercato, quanto vale una batteria e come si misura chi la gestisce"* — è già
qui, in ~85 righe che girano sui prezzi reali.
