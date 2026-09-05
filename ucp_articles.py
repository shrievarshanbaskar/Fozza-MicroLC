"""Team: Fozza · Product: MicroLC — one-line UCP 600 style references.

Paraphrased reminders of the articles the examiner cites. They exist so that
discrepancy notices and negotiation prompts can quote a stable reference; they
are not the text of the ICC publication.
"""

ARTICLES: dict[str, str] = {
    "UCP600-2": "Art. 2: a complying presentation accords with the credit, UCP and international standard banking practice.",
    "UCP600-4a": "Art. 4(a): a credit is separate from the sale contract; banks deal with documents only.",
    "UCP600-5": "Art. 5: banks deal with documents and not with the goods, services or performance they relate to.",
    "UCP600-6d-i": "Art. 6(d)(i): a credit must state an expiry date for presentation; presentation after expiry is not complying.",
    "UCP600-6d-ii": "Art. 6(d)(ii): the place of the bank with which the credit is available is the place for presentation.",
    "UCP600-7a": "Art. 7(a): the issuing bank must honour a complying presentation.",
    "UCP600-14a": "Art. 14(a): banks examine a presentation on its face to determine whether documents appear to comply.",
    "UCP600-14b": "Art. 14(b): banks have a maximum of five banking days following presentation to determine compliance.",
    "UCP600-14c": "Art. 14(c): transport documents must be presented within 21 calendar days after shipment and before expiry.",
    "UCP600-14d": "Art. 14(d): data in a document need not be identical to, but must not conflict with, other documents or the credit.",
    "UCP600-14e": "Art. 14(e): in documents other than the invoice, goods may be described in general terms not conflicting with the credit.",
    "UCP600-14f": "Art. 14(f): a document whose issuer or content is not stipulated is accepted if it fulfils its function.",
    "UCP600-14g": "Art. 14(g): a document presented but not required by the credit is disregarded.",
    "UCP600-14i": "Art. 14(i): a document may be dated prior to the credit but must not be dated later than its presentation.",
    "UCP600-14j": "Art. 14(j): addresses of beneficiary and applicant need not match the credit but must be in the same country.",
    "UCP600-16a": "Art. 16(a): a bank that determines a presentation does not comply may refuse to honour.",
    "UCP600-16c": "Art. 16(c): a refusal notice must state each discrepancy and the disposition of the documents.",
    "UCP600-16f": "Art. 16(f): a bank that fails to act per Art. 16 is precluded from claiming the presentation does not comply.",
    "UCP600-18a-i": "Art. 18(a)(i): a commercial invoice must appear to be issued by the beneficiary.",
    "UCP600-18a-ii": "Art. 18(a)(ii): a commercial invoice must be made out in the name of the applicant.",
    "UCP600-18a-iii": "Art. 18(a)(iii): a commercial invoice must be made out in the same currency as the credit.",
    "UCP600-18b": "Art. 18(b): a bank may refuse an invoice issued for an amount in excess of the amount permitted by the credit.",
    "UCP600-18c": "Art. 18(c): the description of goods in the invoice must correspond with that appearing in the credit.",
    "UCP600-20a-i": "Art. 20(a)(i): a bill of lading must indicate the carrier and be signed by the carrier, master or agent.",
    "UCP600-20a-ii": "Art. 20(a)(ii): a bill of lading must indicate shipment on board a named vessel at the port of loading on a date.",
    "UCP600-20a-iii": "Art. 20(a)(iii): a bill of lading must show shipment from the port of loading to the port of discharge stated in the credit.",
    "UCP600-20c": "Art. 20(c): a bill of lading may indicate transhipment provided the entire carriage is covered by one document.",
    "UCP600-27": "Art. 27: a bank accepts only a clean transport document, one without clauses declaring a defective condition of goods or packaging.",
    "UCP600-28": "Art. 28: insurance documents must appear to be issued by an insurer and cover the credit's risks and amount.",
    "UCP600-30b": "Art. 30(b): a 5 percent tolerance on quantity is allowed unless the credit states quantity in packing units or items.",
    "UCP600-31b": "Art. 31(b): a presentation of several transport documents covering shipment on the same vessel and journey is not partial.",
    "UCP600-32": "Art. 32: if a drawing or shipment by instalments is not made within its period, the credit ceases to be available for that and later instalments.",
    "UCP600-34": "Art. 34: banks assume no liability for the form, accuracy, genuineness or legal effect of any document.",
}


def cite(ref: str) -> str:
    return ARTICLES.get(ref, ref)
