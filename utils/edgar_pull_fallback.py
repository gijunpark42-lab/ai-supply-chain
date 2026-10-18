"""One-off wrapper (nightly 2026-10-14): edgartools' Filing.html() raises when its primary-document lookup returns
None (seen on Micron's 10-K 10-09-2026), so document_text() returned '' and no supplychain / customer paragraphs were
saved. Fall back to the attachment whose document_type equals the form. edgar_pull.py itself is not changed.
Usage: python -X utf8 utils/edgar_pull_fallback.py <keep_customer_paras 0|1> TICKER,TICKER
(1 = the customers file of that filing was already enriched: keep customer paragraphs in the new supplychain file)
Left here UNCOMMITTED by the 2026-10-14 nightly run for the user to review; the durable fix is the same fallback
inside edgar_pull.document_text()."""
import os, sys
ROOT = r"C:\Users\calif\Desktop\earnings-ai"
sys.path.insert(0, ROOT)
os.chdir(ROOT)
import edgar_pull as ep

_orig = ep.document_text

def document_text(doc):
    text = _orig(doc)
    if text or not hasattr(doc, "attachments"):
        return text
    form = str(getattr(doc, "form", "")).upper()
    for a in doc.attachments:
        if str(a.document_type).upper() == form:
            print(f"  fallback: primary document {a.document} ({form})")
            return _orig(a)
    return text

ep.document_text = document_text
if sys.argv[1] == "1":
    # the customers file was already enriched (XBRL only): keep the customer paragraphs in the NEW supplychain file
    ep.customer_paragraphs = lambda text: []
sys.argv = ["edgar_pull.py", "--tickers", sys.argv[2]]
ep.main()
