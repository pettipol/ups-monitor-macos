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
- Sullo Smart-UPS C 1500 (SMC1500I), la prova H09 ha letto carica, autonomia
  stimata, carico, tensioni e frequenze in ingresso e in uscita, corrente in
  uscita, tensione della batteria e temperatura. Il lettore ha calcolato W e
  VA dal carico e dai valori nominali. Nei dati acquisiti manca un contatore
  Wh/kWh. Stop ha restituito un errore; l’arresto regolare del lettore e la
  continuità restano da verificare.
- E70 serve a verificare il widget con dati simulati. Il widget medio di sistema identificato come
  **UPS Monitor E70 Synthetic Test** ha mostrato 74%, autonomia stimata 35 min,
  180 W e 215 VA. W e VA erano derivati. Dopo la chiusura
  normale dell’app ha mostrato **Stopped · stale · On line** conservando i
  valori. Per questa prova visiva basta tenere il formato **medio E70** sulla
  scrivania. Il formato piccolo è facoltativo. L’immagine nella guida mostra
  una [anteprima grafica del formato medio con dati simulati](images/widget-medium-named-offscreen.png).

Le informazioni dettagliate sono in
[`COMPATIBILITY.md`](COMPATIBILITY.md), [`APP_HOST.md`](APP_HOST.md) e
[`NATIVE_BASELINE.md`](NATIVE_BASELINE.md).

## Compilazione locale

Per scegliere tra anteprima simulata, app locale con dati Apple e candidata
sperimentale per le letture avanzate, vedi [Quale app aprire](#quale-app-aprire).

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

## Quale app aprire

Per vedere soltanto l’interfaccia con fixture, compila dalla radice del
repository usando `-derivedDataPath .build/app`, poi apri il bundle Debug
`.build/app/Build/Products/Debug/UPS Monitor.app` con l’argomento
`--synthetic-preview` come indicato in [Quickstart](../README.md#quickstart).
Questa anteprima usa dati simulati e non legge hardware.

La preview locale **E84** contiene l’app firmata **UPS Monitor.app** e il
widget aggiornato. Se hai ricevuto la cartella estratta, apri l’app con un
doppio clic per consultare i dati resi disponibili dal servizio Apple.
Se parti dall’archivio, controlla prima l’impronta ed estrailo seguendo la
[procedura di verifica delle quattro firme](REAL_PREVIEW_PACKAGE.md#verify-and-inspect-a-locally-staged-archive).
Nel collaudo con dati simulati la copia estratta ha aperto una finestra e
ha accettato la chiusura normale. In una verifica separata, lo strumento
di lettura del progetto ha rilevato tramite macOS un UPS su rete con carica
e tensione della batteria. L’autonomia mancava in quel campione.

La candidata **E66** serve al collaudo separato della lettura USB avanzata.
Lo stato delle prove sul dispositivo è registrato in [Compatibilità](COMPATIBILITY.md).

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

Quando E66 viene avviata nella modalità sperimentale USB, la finestra
attende il pulsante Start. L’apertura ordinaria usa il servizio Apple.
La modalità USB richiede un Mac con chip Apple e macOS 27 o
successivo. H12 si è conclusa con Quit prima di Start. Nel successivo collaudo
H13 da Terminale, il lettore ha prodotto otto campioni freschi sullo SMC1500I.
Il controller ha richiesto Stop circa 35 secondi dopo il primo campione.
Il lettore ha segnalato un errore di chiusura, pur liberando la sessione USB
e terminando i processi della prova. Lo Stop regolare resta da qualificare.

L’app chiede a WidgetKit di aggiornare il riquadro alla prima pubblicazione,
al primo campione della sessione e quando pubblica lo stato di arresto.
A stato invariato devono trascorrere
almeno cinque minuti tra richieste ordinarie. Un cambio di stato o sorgente
può anticipare la richiesta dopo 30 secondi. macOS decide quando ridisegnare
il riquadro. E70 mostrava valori simulati. Nella prova H09 il lettore ha
derivato W e VA dal carico e dalle potenze nominali. Tra i dati acquisiti
mancava un contatore Wh/kWh.
