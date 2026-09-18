# Scope-Scaling via Epic-Praefix (GS)

Grosse Kampagnen bleiben lesbar, wenn Steps nach Epic-Praefix gruppiert,
gefiltert und gezaehlt werden. Dieses Dokument beschreibt die
Schnittregel, die CLI-Filter, die `by_epic`-Counts und das
`epic-campaign`-Rezept. Alle Bausteine sind warn-first: Hinweise statt
Gates, keine Exit-Semantik-Aenderung, kein Netz/Daemon, stdlib-only im
Kern.

## 1. Schnittregel: Epic ist der ID-Praefix

Das Epic einer Step-ID ist der fuehrende Grossbuchstaben-Praefix,
abgeleitet per `epic_of` aus `rfg/scope.py` (reine String-Praefixe,
stdlib-only, kein Roadmap-Schema-Feld, kein Hard-Gate):

| Step-ID | Epic |
|---|---|
| `GS1-epic-scope` | `GS` |
| `GS1t-epic-scope-tests` | `GS` |
| `KD-1` | `KD` |
| `XB-01` | `XB` |

Verwandte Helfer: `filter_by_epic(steps, epic)` (unbekanntes Epic ->
leere Liste), `list_epics(steps)` (sortierte Epics),
`unknown_epic_warning(steps, epic)` (Warntext oder `""`).

## 2. Filtern mit --epic (reine Anzeige)

`rfg plan --list --epic GS`, `rfg next --epic GS` (`--epic=GS` geht auch)
und `rfg progress --epic GS` zeigen nur Steps dieses Epics. Der Filter
ist reine Anzeige: kein neues Verb, kein MCP-Param (`plan`/`next`/
`progress` in `rfg/mcp.py` kennen kein `epic`), keine Scope-Aenderung.
`dag.recommend` bleibt per `recommend(rm, state, epic)` in-Epic; ein
unbekanntes Epic liefert `("", "unknown epic ...")` plus `warning`-Feld.

## 3. Gruppieren mit by_epic

`progress.report` meldet `by_epic`-Counts je Epic
(`total`/`verified`/`ready`), zusaetzlich zu den globalen Counts. Damit
sieht man auf einen Blick, welches Epic steht und welches hängt.

## 4. Warn-first, nie Gates

Unbekannte oder leere Epics warnen nur (`unknown epic 'ZZ' ...`,
warn-first, kein Gate), sie gaten nie. `doctor` meldet stale Epics
(`stale epic 'KD' ...`, Gruppe ohne verified/ready) ebenfalls nur als
Hinweis im `epics`-Check (`ok: true`); `doctor.epic_warnings(steps,
epic)` und `doctor.stale_epic_warnings(rm, state)` exiten nie.

## 5. Rezept: rfg/data/recipes/epic-campaign.yaml

Das Rezept `epic-campaign` (`rfg/data/recipes/epic-campaign.yaml`)
rendert eine valide Epic-Kette: ein Praefix (`EC`), verlinkte
`depends_on` (jeder Step haengt an Vorgaengern), je Step `engine` plus
`verify`. Anwenden per `rfg recipe apply epic-campaign`, inspizieren per
`rfg recipe show epic-campaign`.
