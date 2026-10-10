# Nuvola Madisoft — Home Assistant custom integration

Integrazione non ufficiale per Home Assistant basata sul portale studente Nuvola Madisoft.

## Installazione

Copia la cartella `custom_components/nuvola` in:

`/config/custom_components/nuvola`

Riavvia Home Assistant, poi:

**Impostazioni → Dispositivi e servizi → Aggiungi integrazione → Nuvola Madisoft**

Inserisci username e password Nuvola.

## Più studenti

La versione 1.1 supporta **da 1 a 5 studenti per account**.

- Usa un solo login Nuvola.
- Seleziona gli studenti durante la configurazione.
- Ogni studente viene rappresentato da un dispositivo Home Assistant separato.
- Se l'account contiene più di 5 studenti, puoi sceglierne fino a 5.
- Gli studenti selezionati possono essere modificati in seguito dalle opzioni dell'integrazione.
- La sessione/token API viene condivisa tra gli studenti della stessa configurazione.

## Dati

L'integrazione tenta di leggere:
- studente/classe/scuola
- periodo corrente
- voti
- medie per materia
- assenze, ritardi e uscite
- assenze non giustificate
- note
- notifiche non lette
- compiti per i prossimi 14 giorni
- eventi classe/materia/personali quando disponibili
- argomenti delle lezioni (API disponibile, non ancora esposta come entità dedicata)
- pagamenti quando disponibili

## Aggiornamento

Default: ogni 10 minuti.

Il JWT viene richiesto nuovamente automaticamente quando Nuvola risponde HTTP 401.

## Nota

Le API `/api-studente/v1` utilizzate qui non sono documentate pubblicamente da Madisoft: sono state ricostruite tramite analisi del traffico del portale e possono cambiare. L'integrazione non è affiliata a Madisoft.
