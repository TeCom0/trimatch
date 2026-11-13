# VAT rates for the fake company's products (CGI 2026)

Date: 2026-11-13. Source: Code Général des Impôts, édition 2026 (includes LF n° 50-25), PDF hosted by the Casablanca regional investment centre (https://casainvest.ma/sites/default/files/2026-02/Code%20impo%CC%82ts%202026.pdf), text extract provided by Youness. Page numbers are the CGI's own.

## Rates in force in 2026

Art. 99 (p. 180-186): "Le taux de la taxe sur la valeur ajoutée est fixé à : A.- 20 % ; B.- 10 % : …". There is no 7% or 14% left in art. 99 (art. 98 and art. 100 are "abrogé").

Art. 247-XXXXI (p. 481-482) sets the transition from the old rates. Every path ends at 10% or 20% by 1 Jan 2026. Examples:
- sugar 7% → 8% (2024) → 9% (2025) → **10% (2026)**
- electricity 14% → **20% (2026)**
- urban/road transport 14% → **10% (2026)**

**So in 2026 the only rates are 20%, 10% and exempt.** Odoo 20's `l10n_ma` chart still ships 14% and 7% purchase taxes. That's outdated, so the seed must not use them.

## What the CGI says about our product categories

| Item | CGI text | Treatment |
|---|---|---|
| Fresh/frozen meat | 91-I-A-6°: "la viande fraîche ou congelée assaisonnée ou non assaisonnée" | Exempt, no deduction |
| Fresh fish | 91-I-A-5°: "les produits de la pêche à l'état frais, congelés, entiers ou découpés" | Exempt |
| Milk, cream, butter | 91-I-A-2°: "les laits et crèmes de lait frais … ainsi que le beurre dérivé du lait d'origine animale" | Exempt |
| Household soap (bars) | 91-I-A-10°: "le savon de ménage (en morceaux ou en pain)" | Exempt |
| Short dry pasta | 91-I-A-1° (LF 2026): "les pâtes alimentaires courtes non cuites et non farcies" | Exempt (other pasta 10%) |
| Edible oils (not palm) | 99-B-1°: "les huiles fluides alimentaires à l'exclusion de l'huile de palme" | 10% |
| Milled rice | 99-B-1°: "le riz usiné" | 10% |
| Cooking salt | 99-B-1°: "le sel de cuisine (gemme ou marin)" | 10% |
| Water | 99-B-1° covers only "l'eau destinée aux réseaux de distribution publique" | Bottled water is **not** covered, so 20% |
| Soft drinks, juices, detergents, bleach, paper towels, bin bags | not listed in art. 91, 92 or 99 | 20% (default rate, art. 99-A) |
| Fresh fruit and vegetables | **not listed** in art. 91. Wholesalers are taxable under 89-I-2°-a. Art. 125 ter speaks of "taxe … non apparente" on locally sourced fresh fruit/veg bought by agri-food processors, which implies they usually reach the buyer without VAT shown (farm sales outside the scope). | **Unresolved** for a wholesaler selling to a hotel. Avoided in the slice. |

Note: the art. 91-I-A exemptions apply to sales "autrement qu'à consommer sur place". A supplier selling to a hotel kitchen qualifies, since the hotel's own restaurant sales are a separate taxable operation (art. 89-I-9°, 10% under art. 99-B-1°).

Invoice consequence: exempt lines need the exemption mention (art. 145-III). Check the exact wording when writing the generator template.

## Mandatory invoice mentions (art. 145-III, p. ~ "Tenue de la comptabilité")

Verbatim list: 1° identity of the seller; 2° "le numéro d'identification fiscale … ainsi que le numéro d'article d'imposition à la taxe professionnelle"; 3° date of the operation; 4° name and address of the buyer "et leur identifiant commun de l'entreprise"; 5° price, quantity and nature of goods; 6° the VAT amount shown separately. For art. 91/92/94 operations, "la mention de la taxe est remplacée par l'indication de l'exonération ou du régime suspensif"; 7° "les références et le mode de paiement"; 8° any other legal information. Art. 145-VIII: the seller's ICE must be on invoices.

Generator consequence: every invoice carries the seller's IF, TP (taxe professionnelle) and ICE, the buyer's ICE, payment method/terms, and an exemption mention on exempt lines (e.g. "Exonéré – art. 91-I-A-6° CGI").
