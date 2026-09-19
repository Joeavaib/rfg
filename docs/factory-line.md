# Fabrik-Linie: Prüfer, nicht Fabrik

rfg verleiht keine Fähigkeiten, es verweigert stilles Zuviel. Alles was
erzeugt, versteht, holt, behält oder dauerhaft läuft, gehört dem
User/Agent/Toolchain — nicht rfg. Im Zweifel: warn-first, nie raten,
sondern Exit 4 statt „all good".

## Tripwires (ein Treffer = Stopp, kein „später fixen")

- **T1 Braucht Netz.** `socket`/`urllib`-Import, neuer Socket, `telemetry.py` mehr als Append. `doctor` zeigt weiter `network: unused`.
- **T2 Lebt über Step-Ende.** Thread/Daemon/`Popen` ohne `wait`, Lock-/Sockendatei, Watch-Loop, Scheduler. Nach `tick`/`verify` läuft `ps` leer.
- **T3 Neue Non-Stdlib-Dep.** Import außerhalb Stdlib, `pip install` als Voraussetzung. Frisches Python ohne `pip` läuft die Suite grün.
- **T4 Versteht Semantik statt Strings.** Eigener Parser, Typauflösung, Live-LSP statt `which`-Präsenz. `caps.py` bleibt boolsch, `lsp.py` bleibt Erkennung.
- **T5 Cached über Runs mit Invalidierungslogik.** Persistenter Cache außerhalb Logs/Snapshots. Löschen von allem außer `roadmap.yaml`/`state.json`/`env` ändert kein Verify-Ergebnis.
- **T6 Führt Code außerhalb User-Verify aus.** `subprocess` nur in `verify.py`/`security.py` (+`gitops.py` für git, `astgrep.py`/`fmtutil.py` für Bins). Kein `os.system` in Apply-Pfaden.
- **T7 Schreibt außerhalb Worktree.** Write nur Worktree/`.rfg`-Store. `apply` ohne `land` lässt das Hauptrepo clean; `land` nur nach Re-Verify.

## Grauzonen (Urteil gilt für rfg-Kern, nicht User-Verifies)

- `pip install` im Verify: diesseits (User-Orakel, geloggt), kein Auto-`pip` durch rfg.
- Toolchain-Download: jenseits. Kompromiss: Rezept + `doctor`-Hint, Download bleibt Handarbeit.
- Watch-Mode, parallele Verifies als Default, Coverage-Enforcement, Cache-Besitz, Auto-Env-Write, Score-Gates, Auto-Fix: jenseits (teils als Rezept/Opt-in außerhalb, nie Default).

## Review-Checkliste

1. Stdlib-only? Offline? Kein Socket/Download?
2. Kein Prozess über Step-Ende? Kein Watch/Scheduler?
3. Kein eigener Parser/Typ/LSP-Call — nur which-Präsenz + Exit 4?
4. Code-Exec nur via User-verify im Worktree + Log?
5. Write nur Worktree/.rfg? Land nur nach Re-Verify?
6. Kein Cache mit Invalidierung? Löschen = gleiche Ergebnisse?
7. Scanner/Fuzzer nur wenn vorhanden, sonst Exit 4/OK-ran-False?
8. `.rfg/env` nur deklariert, nichts provisioniert?
9. Warn-first statt Raten? Sham/weak-Verify erkannt?
10. cxx-Subset-Ehrlichkeit gewahrt (kein stilles Parity-Versprechen)?

## Eskalation (ein Wort, Default bis dahin: warnen + Exit 4)

- **STEMPEL** — diesseits, Prüfer. Bauen wie vorgeschlagen.
- **REZEPT** — nicht in Kern, als Rezept/Doku-Beispiel außerhalb.
- **SCHLUESSEL** — nur als explizites Opt-in (`Flag`/`RFG_*=1`), Default bleibt Nein.
- **STOPP** — jenseits, Fabrik. Nicht bauen, Exit-4-Fall bleibt.

## Suite-Vorher/Nachher (Riesen-Patch-Protokoll, QB-02)

- **Vorher (A):** volle Suite grün + Laufzeit festhalten (`pytest tests/ -q`, Zeit notieren). Ohne grünes A kein Patch.
- **Nachher (B):** gleiche Suite + `scripts/mutation_sample.py` (Kill-Bericht). B rot oder Kill-Rate gefallen → kein Land.
- Beleg ins Log: Suite-Zeit + Kill-Bericht gehören ins Step-Verify-Log (`.rfg/verify/`), nie aus dem Kopf.

## Land-Gate-Tabelle (QW-04)

`land` kopiert erst nach Re-Verify; jede Zeile ist ein Test-Pin in `tests/test_gaps.py`:

- Offene Steps (`next` gesetzt) oder `failed` nicht leer → Exit 5 (`roadmap unfinished`).
- `applied` aber nicht `verified` → Exit 5 (`applied but not verified`); `verified != done` ist enforced, nicht empfohlen.
- Tracked-dirty Root ohne separaten Stop-Engine-Worktree → Exit 3 (`working tree dirty`).
- Triviales Verify (`true`/leer) im Worktree-Pfad → Revert + Exit 4 (kein Beweis, kein Land).
- Step-Verify, Suite-Gate (`rm.verify`) oder Acceptance rot → Revert + Exit 2 (Worktree-Copy wird zurückgerollt).
- Fehlende Toolchain im Gate → Skip mit Log (Exit 4-Eintrag), nie Fail.
- Alles verifiziert + clean → Exit 0 mit `state_backup` (`land-backups/`).
