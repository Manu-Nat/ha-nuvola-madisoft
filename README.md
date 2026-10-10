# Nuvola Madisoft per Home Assistant

Integrazione **non ufficiale** per [Home Assistant](https://www.home-assistant.io/) che legge dal portale
famiglie **Nuvola** (Madisoft) i dati degli studenti: voti, compiti, assenze, avvisi, pagamenti.

> Progetto indipendente, non affiliato né approvato da Madisoft. Usa lo stesso accesso del sito web
> con le tue credenziali: se Nuvola cambia il portale, l'integrazione può smettere di funzionare.

## Funzioni

- Accesso con **username e password** Nuvola (login web tramite Keycloak).
- **Da 1 a 5 studenti** per account; un dispositivo per ogni studente.
- Sensori per studente: media, ultimo voto, numero voti, assenze, assenze non giustificate, ritardi,
  uscite anticipate, note, notifiche non lette, compiti di oggi e dei prossimi giorni, eventi/avvisi,
  pagamenti da pagare.
- Un sensore binario "compiti presenti oggi" e un calendario "scadenze e compiti".
- Gli studenti scelti si possono cambiare in seguito dalle opzioni dell'integrazione.

## Installazione

### Con HACS (repository personalizzato)

1. HACS → menu a tre puntini → **Repository personalizzati**.
2. Aggiungi `https://github.com/Manu-Nat/ha-nuvola-madisoft` come categoria **Integrazione**.
3. Cerca **Nuvola Madisoft**, scarica e riavvia Home Assistant.

### Manuale

Copia la cartella `custom_components/nuvola` in `/config/custom_components/nuvola` e riavvia.

## Configurazione

**Impostazioni → Dispositivi e servizi → Aggiungi integrazione → Nuvola Madisoft**, poi inserisci
username e password. Se l'account ha più studenti, scegli quali aggiungere.

## Limiti noti

- Non è supportata la verifica a due passaggi (OTP) né l'accesso con SPID.
- Quando Nuvola ti chiede di **cambiare la password** (scadenza periodica) l'accesso si interrompe:
  cambiala sul sito e aggiornala nell'integrazione.
- I sensori "Media" e "Ultimo voto" sono `unknown` finché non ci sono voti nel periodo corrente.

## Risoluzione dei problemi

Se il login fallisce, il messaggio indica il passo che si è interrotto. Per più dettagli, in
`configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.nuvola: debug
```

Nei log vengono scritti solo host e percorso degli indirizzi, ma **controlla sempre cosa pubblichi**
prima di allegare un log a una segnalazione: può contenere nomi degli studenti.

## Privacy

Le credenziali restano nella configurazione locale di Home Assistant. I dati degli studenti
(nomi, voti, pagamenti) sono dati personali di minorenni: non condividere screenshot o log senza
averli oscurati.
