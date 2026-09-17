# corpus.py -- find documents on disk and tie them to the project's canonical labels.
#
# The project already has a canonical source-label format, fixed in CLAUDE.md:
#     "[Company] Q[N] FY[YYYY] (MM-DD-YYYY)"   e.g. "Rambus Q2 FY2026 (07-27-2026)"
# and a filename convention:
#     transcripts/<category>/<company>_q<N>_<year>.txt
#
# Both encode (company, quarter, fiscal year), so they can be joined without any
# hand-written mapping table. That join is what lets the human labels in
# quant/signal_full_capacity.csv become a gold set for the agent -- see agent/eval/gold.py.

import glob
import os
import re
from typing import Dict, List, NamedTuple, Optional

TRANSCRIPT_GLOB = "transcripts/**/*.txt"

# <company>_q<N>_<year><optional suffix like _earnings_release>
_FILENAME = re.compile(r"^(?P<company>.+?)_q(?P<quarter>\d)_(?:fy)?(?P<year>20\d\d)(?P<suffix>.*)$")
# "[Company] Q[N] FY[YYYY] (MM-DD-YYYY)"
_LABEL = re.compile(r"^(?P<company>.+?)\s+Q(?P<quarter>\d)\s+FY(?P<year>20\d\d)")

# Node names in the graph do not always match the filename token. These are the
# only mismatches found across the 71-call gold universe; each was checked by hand.
COMPANY_ALIASES: Dict[str, str] = {
    "amazonwebservices": "amazon",
    "armholdings": "arm",
    "nvidia": "nvda",
    "asegroup": "ase",
    "amkortechnology": "amkor",
    "ontoinnovation": "onto",
    "ttmtechnologies": "ttm",
    "google": "alphabet",
    "appliedoptoelectronics": "aaoi",
}


def normalize_company(name: str) -> str:
    """Strip everything but letters and digits so 'SK Hynix' == 'sk_hynix'."""
    key = re.sub(r"[^a-z0-9]", "", name.lower())
    return COMPANY_ALIASES.get(key, key)


class Document(NamedTuple):
    path: str
    company_token: str   # normalized company as it appears in the filename
    quarter: int
    year: int
    suffix: str          # "" for a full transcript, "_earnings_release" etc. otherwise

    @property
    def stem(self) -> str:
        return os.path.basename(self.path)[:-4]

    @property
    def is_full_transcript(self) -> bool:
        """A bare <company>_q<N>_<year>.txt is the full call; suffixed files are 8-Ks."""
        return self.suffix == ""

    def read(self) -> str:
        with open(self.path, encoding="utf-8", errors="replace") as handle:
            return handle.read()


def list_documents(pattern: str = TRANSCRIPT_GLOB) -> List[Document]:
    """Every transcript whose filename follows the convention."""
    documents = []
    for path in sorted(glob.glob(pattern, recursive=True)):
        match = _FILENAME.match(os.path.basename(path)[:-4])
        if not match:
            continue   # a few files predate the convention; they have no label to join on
        documents.append(Document(
            path=path.replace("\\", "/"),
            company_token=normalize_company(match.group("company")),
            quarter=int(match.group("quarter")),
            year=int(match.group("year")),
            suffix=match.group("suffix"),
        ))
    return documents


def _tokens_match(label_token: str, file_token: str) -> bool:
    """Loose company match -- one side is a prefix of the other.

    'globalfoundries' vs 'globalfoundries' is exact; 'analogdevices' vs
    'analog_devices' normalises to the same; prefix handling covers cases like
    'micron' vs 'microntechnology'.
    """
    if label_token == file_token:
        return True
    head = min(len(label_token), len(file_token), 7)
    return label_token[:head] == file_token[:head]


def find_document_for_label(label: str,
                            documents: Optional[List[Document]] = None) -> Optional[Document]:
    """Resolve a canonical source label to the full transcript it came from.

    Prefers the full transcript over a same-quarter earnings release.
    Returns None when the corpus has no file for that quarter.
    """
    match = _LABEL.match(label)
    if not match:
        return None
    if documents is None:
        documents = list_documents()

    company = normalize_company(match.group("company"))
    quarter = int(match.group("quarter"))
    year = int(match.group("year"))

    candidates = [d for d in documents
                  if d.quarter == quarter and d.year == year
                  and _tokens_match(company, d.company_token)]
    if not candidates:
        return None
    # The loose prefix match lets 'applieddigital' hit 'appliedmaterials' and 'lumentum' hit
    # 'lumen'. When a file for exactly this company exists, it must win.
    exact = [d for d in candidates if d.company_token == company]
    if exact:
        candidates = exact
    full = [d for d in candidates if d.is_full_transcript]
    return full[0] if full else candidates[0]


def label_for_document(document: Document, company_display: str) -> str:
    """Best-effort canonical label for a document we only know by filename.

    The call DATE is not recoverable from the filename, so this is only used for
    display/provenance on documents that are not part of the labelled gold set.
    """
    return f"{company_display} Q{document.quarter} FY{document.year}"
