# Guida Italiana

UPS Monitor Mac è un progetto macOS in sviluppo. Riutilizza il servizio
Apple di rilevamento delle sorgenti di alimentazione e può configurare un
client NUT esplicito. Non sostituisce la protezione di arresto di macOS e non
invia comandi di controllo all'UPS.

## Stato e limiti

- Una sola osservazione nativa qualitativa ha restituito stato, carica batteria
  (rapporto) e tensione batteria (V); non ha restituito tensione di rete o
  potenza attiva. Non costituisce qualifica di un modello specifico.
- Le stime energetiche sono calcoli applicativi in Wh da intervalli di potenza
  attiva validi. `Input` usa `inputRealPower`; `UPS` usa `upsRealPower` e non è
  etichettata come misura del lato di uscita: il punto fisico non è qualificato.
  Non sono letture di contatore, dati di
  fatturazione o stime complete dei consumi domestici.
- Il percorso NUT ricco e l'integrazione energia hanno prove sintetiche, non una
  qualifica su UPS reale. Il driver sperimentale `apcmicrolink` è `NOT RUN`, non
  è distribuito nell'app e non è dimostrato come sola lettura.
- Il widget è compilato, ma accesso App Group firmato, installazione e resa
  effettiva non sono qualificati. macOS 14 e Mac Intel non hanno prove runtime
  registrate.

Le informazioni dettagliate sono in
[`COMPATIBILITY.md`](COMPATIBILITY.md), [`APP_HOST.md`](APP_HOST.md) e
[`NATIVE_BASELINE.md`](NATIVE_BASELINE.md).

## Compilazione locale

La compilazione richiede gli strumenti Apple registrati in
[`DEPENDENCIES.md`](DEPENDENCIES.md). Dalla radice del repository:

```sh
swift test
xcodebuild -project UPSMonitor.xcodeproj -scheme UPSMonitor \
  -configuration Debug -derivedDataPath .build/app build
```

I test sono destinati a fixture sintetiche; non configurare variabili che
puntino a un server NUT installato o a un UPS reale. La suite NUT opzionale usa
solo un bundle esplicitamente fornito e un server loopback sintetico.

## Anteprima locale

Il bundle Debug è ad-hoc firmato, non notarizzato e non pronto per la
distribuzione. L'anteprima seguente usa dati fissi, non legge hardware e non
scrive nella cronologia:

```sh
open '.build/app/Build/Products/Debug/UPS Monitor.app' --args --synthetic-preview
```

Non disattivare Gatekeeper o altre protezioni di macOS. Se il sistema blocca
l'avvio o la firma, interrompere la procedura e chiedere una verifica; non
aggirare l'avviso.

## Dati e sicurezza

Valori assenti o non validi non equivalgono a zero. W, VA, Wh e percentuale di
carica sono grandezze distinte. Le stime energia restano in memoria, si
interrompono ai buchi e ai cambi di sorgente e si esportano separatamente dalla
cronologia. L'export non è una misura calibrata.

L'app non avvia un driver UPS. Non installare o avviare il driver sperimentale
NUT USB per ottenere più campi: il suo percorso può inviare frame, autenticarsi,
fare recovery USB e contiene comandi modificanti. Nessun test documentato qui
qualifica tali effetti su hardware.
