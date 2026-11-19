You do not see the page: you get its OCR text, one printed row per line, read left to right. " | " marks a wide gap between two cells; a single space is a gap inside one cell (several cells may still be joined by spaces when they are close).
Rules for this OCR text:
- The line table has the columns Réf. | Désignation | Qté | Unité | P.U. HT | TVA | Montant HT (a delivery note has only the first four). Each item row starts with its Réf. code (e.g. "HYG-SM24"). Split that row into the fields: supplier_ref = the code, description = the product name only, quantity, unit, then the prices. Never copy " | " or a column header into a field.
- An "art. ... CGI" line printed under an exempt row belongs to that row's exemption_ref.
- number: the document number only, without the "N°" label (e.g. "FA-HP-2026-0581").
- OCR can confuse O/0, l/1, I/l and drop accents; "art. 91-1-A" is OCR for "art. 91-I-A". Copy the text otherwise as given.
- There is no box field for you: positions come from the OCR. Ignore the rule below about boxes.
