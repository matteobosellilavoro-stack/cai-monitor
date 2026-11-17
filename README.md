# CAI Monitor - Centro Italia (novita generiche + corsi evidenziati)

## Che cosa segnala
- **Ogni nuovo link significativo** e ogni nuovo titolo H2/H3/H4 presenti nell'area contenuti delle pagine monitorate, **anche senza parole chiave**.
- **Aggiornamenti** al titolo o al breve testo associato a un collegamento o un titolo gia noto.
- I contenuti relativi ad alpinismo, ghiaccio, ghiacciai, arrampicata, multipitch e ferrate vengono evidenziati con **🔥 CORSO/ATTIVITA PERTINENTE**; il resto arriva come **📰 NOVITA GENERICA**.
- Menu, intestazioni, footer, social, cookie, moduli e alcuni link strutturali sono ignorati per limitare le notifiche inutili.

Non e un rilevatore universale di ogni cambiamento grafico o di ogni parola: modifica solo parti significative della pagina. Nuove pagine non collegate, PDF gia esistenti modificati senza cambiare il collegamento, post solo social e siti caricati esclusivamente via JavaScript possono sfuggire. Un aggiornamento a testi dinamici puo generare falsi positivi.

## Attivazione
1. In Telegram cerca **@BotFather**, invia `/newbot` e conserva il token del bot. Non incollarlo nel repository.
2. Avvia la chat con il tuo bot, inviagli un messaggio, quindi apri `https://api.telegram.org/bot<TOKEN>/getUpdates` e recupera `message.chat.id`.
3. Crea un repository **privato** su GitHub e carica il contenuto di questa cartella, preservando `.github/workflows/monitor.yml`.
4. Nelle impostazioni del repository, **Settings > Secrets and variables > Actions**, crea due segreti `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID`.
5. In **Settings > Actions > General > Workflow permissions**, abilita **Read and write permissions**, per salvare `state.json` nel repository.
6. In **Actions > Monitor corsi CAI > Run workflow** avvia la prima esecuzione. La prima scansione di ogni nuova fonte salva i contenuti senza notificare annunci storici.
7. Lascia la schedulazione del workflow attiva: tre controlli giornalieri previsti (potrebbero subire ritardi).

Il repository privato usa i minuti inclusi nel piano GitHub gratuito, entro i relativi limiti.

## Aggiungere scuole
Aggiungi un oggetto `{ "name": "Nome scuola", "url": "https://..." }` a `sources.json`. Meglio usare pagine **notizie/corsi** specifiche anziche homepage molto generiche, per ridurre falsi positivi.

## Avvertenze
- Su un sito con link dinamici e consigliabile controllare i primi avvisi e, se necessario, perfezionare il filtro per quella pagina.
- Se Telegram non e configurato, lo script stampa messaggi nei log ma non aggiorna lo stato quando ci sono novita: questo consente di riprovare l'invio.
- Se una fonte non risponde, il suo stato precedente viene conservato.
- La notifica segnala la pubblicazione: occorre aprire il link per verificare date, requisiti, posti e iscrizioni.
