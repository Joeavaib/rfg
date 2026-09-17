# rfg Test-Fokus (ROI, Konvention, kein Gate — stoppt Regress)

1. Verify <30s, offline, Exit-Code=Wahrheit; sonst kein Step-Verify.
2. Immer: Crash auf Fehl-Input + falscher Exit-Code (billig, häufig).
3. Immer: Boundary empty/1/n + Sonderzeichen-Pfad.
4. Immer: Shell-Quoting + CWE-78 wenn sh -c/subprocess vorkommt.
5. Bei FS-Steps: Stale-State (2x laufen lassen muss idempotent sein).
6. Kein Mock-Framework; echte tmp-Dirs unter /tmp/opencode.
7. Kein E2E pro Step; nur 1 Gold-Pfad pro Feature am Ende.
8. Flaky-Verbot: kein sleep/curl/order-abhängig.
9. Pesticide-Regel: nach 3 grünen Runs Verify-Variante rotieren.
10. Stopp-Regel: max. 3 Verifies/Step; Rest ist Doku, kein Test.
